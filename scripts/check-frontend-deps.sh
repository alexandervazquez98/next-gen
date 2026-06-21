#!/usr/bin/env bash
# Pre-flight check for the frontend dependency tree.
#
# Why this exists
#   Vite resolves imports from node_modules at startup. If a developer
#   clones the repo and runs `pnpm dev` outside Docker without first
#   running `corepack pnpm install --frozen-lockfile`, Vite fails with
#   "Failed to resolve import \"sonner\" from context/AuthContext.tsx".
#   This script gives that path an opt-in recovery: a SHA-256 sentinel
#   of frontend/pnpm-lock.yaml plus a small import scan guards against
#   drift and missing critical packages.
#
# What it does
#   1. Hash frontend/pnpm-lock.yaml with SHA-256.
#   2. If frontend/.frontend-deps-ok matches the hash AND every non-
#      relative `from 'pkg'` import in frontend/context/AuthContext.tsx
#      and frontend/App.tsx is present in frontend/node_modules — exit 0.
#   3. Otherwise run `corepack pnpm install --frozen-lockfile` inside
#      frontend/, write the new hash to the sentinel, and exit with the
#      install result.
#
# Usage
#   bash scripts/check-frontend-deps.sh
#   corepack pnpm --dir frontend run check:deps

set -euo pipefail

# Resolve REPO_ROOT from this script's location so the script behaves
# correctly whether invoked from the real repo or from a test fixture.
SCRIPT_PATH="${BASH_SOURCE[0]}"
REPO_ROOT="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"

FRONTEND_DIR="$REPO_ROOT/frontend"
LOCK="$FRONTEND_DIR/pnpm-lock.yaml"
SENTINEL="$FRONTEND_DIR/.frontend-deps-ok"
AUTH_CONTEXT="$FRONTEND_DIR/context/AuthContext.tsx"
APP_TSX="$FRONTEND_DIR/App.tsx"

log()  { printf '[check-frontend-deps] %s\n' "$*"; }
fail() { printf '[check-frontend-deps] %s\n' "$*" >&2; }

# Compute the lockfile SHA-256.
lock_hash() {
  sha256sum "$LOCK" | awk '{print $1}'
}

# Return 0 if every non-relative `from 'pkg'` import in the two tracked
# files is present in frontend/node_modules. Prints the first missing
# package on stderr.
verify_tracked_imports() {
  local FILE LINE IMP TOP
  for FILE in "$AUTH_CONTEXT" "$APP_TSX"; do
    [[ -f "$FILE" ]] || continue

    # Extract `from 'pkg'` style imports; skip relative paths (./foo, ../foo).
    # `|| true` prevents `set -e` from aborting on grep no-match.
    # Iterate line-by-line so we don't accidentally word-split the package name.
    while IFS= read -r LINE; do
      [[ -z "$LINE" ]] && continue

      # `LINE` looks like `from 'pkg'` or `from "pkg"`. Strip the `from `
      # prefix, then the surrounding quotes.
      IMP="${LINE#from }"
      IMP=$(printf '%s' "$IMP" | sed -E "s/^['\"\`]+//; s/['\"\`]+$//")

      if [[ "$IMP" == @* ]]; then
        TOP=$(echo "$IMP" | cut -d/ -f1-2)
      else
        TOP=$(echo "$IMP" | cut -d/ -f1)
      fi

      [[ -z "$TOP" || "$TOP" == "from" ]] && continue
      if [[ ! -e "$FRONTEND_DIR/node_modules/$TOP" ]]; then
        fail "Missing tracked import '$TOP' (from $FILE)"
        return 1
      fi
    done < <(grep -hoE "from ['\"][^./][^'\"]*['\"]" "$FILE" 2>/dev/null || true)
  done
  return 0
}

main() {
  if [[ ! -f "$LOCK" ]]; then
    fail "Lockfile not found at $LOCK"
    exit 1
  fi

  local HASH SENTINEL_VALUE
  HASH=$(lock_hash)
  SENTINEL_VALUE=""
  if [[ -f "$SENTINEL" ]]; then
    SENTINEL_VALUE=$(cat "$SENTINEL" 2>/dev/null || true)
    SENTINEL_VALUE="${SENTINEL_VALUE%$'\n'}"
  fi

  if [[ "$SENTINEL_VALUE" == "$HASH" ]] && verify_tracked_imports; then
    log "All tracked imports resolved; sentinel up to date."
    exit 0
  fi

  if [[ "$SENTINEL_VALUE" != "$HASH" ]]; then
    log "Sentinel missing or stale; running install..."
  else
    log "Sentinel matches but tracked imports missing; reinstalling..."
  fi

  if ( cd "$FRONTEND_DIR" && corepack pnpm install --frozen-lockfile ); then
    printf '%s\n' "$HASH" > "$SENTINEL"
    log "Install complete; sentinel updated."
    exit 0
  else
    fail "Install failed; sentinel not updated."
    exit 1
  fi
}

main "$@"