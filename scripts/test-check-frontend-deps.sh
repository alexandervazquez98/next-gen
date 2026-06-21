#!/usr/bin/env bash
# RED-first bash tests for scripts/check-frontend-deps.sh
# Scenarios:
#   1. recovery:        script auto-installs when sonner is missing
#   2. no-op sentinel:  script exits cleanly when sentinel matches and imports resolve
#   3. install failure: script propagates non-zero exit when install fails
#
# Run from the repo root: `bash scripts/test-check-frontend-deps.sh`

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SCRIPT_UNDER_TEST="$REPO_ROOT/scripts/check-frontend-deps.sh"

# ---- harness ---------------------------------------------------------------

TEMP_DIRS=()
cleanup_all() {
  local D
  for D in "${TEMP_DIRS[@]:-}"; do
    [[ -n "$D" ]] && rm -rf "$D" 2>/dev/null || true
  done
}
trap cleanup_all EXIT

TOTAL=0
PASSED=0
FAILED_NAMES=()

record_pass() { PASSED=$((PASSED + 1)); printf '  PASS: %s\n' "$1"; }
record_fail() {
  FAILED_NAMES+=("$1")
  printf '  FAIL: %s\n' "$1" >&2
}

# Build a fixture under $1. Copies tracked files + the script-under-test
# (if it exists; RED phase proves we need the script). Pre-creates
# node_modules stubs for every tracked import EXCEPT `sonner` so the only
# missing package the script can detect is sonner itself.
setup_fixture() {
  local DIR="$1"
  mkdir -p "$DIR/frontend/context"
  mkdir -p "$DIR/frontend/node_modules"
  mkdir -p "$DIR/scripts"

  cp "$REPO_ROOT/frontend/pnpm-lock.yaml" "$DIR/frontend/"
  cp "$REPO_ROOT/frontend/package.json"    "$DIR/frontend/"
  cp "$REPO_ROOT/frontend/context/AuthContext.tsx" "$DIR/frontend/context/"
  cp "$REPO_ROOT/frontend/App.tsx"         "$DIR/frontend/"

  if [[ -f "$SCRIPT_UNDER_TEST" ]]; then
    cp "$SCRIPT_UNDER_TEST" "$DIR/scripts/"
    chmod +x "$DIR/scripts/check-frontend-deps.sh"
  fi

  # Pre-populate stubs for every import except sonner
  local IMPORTS_RAW
  IMPORTS_RAW=$(grep -hoE "from ['\"][^./][^'\"]*['\"]" \
    "$DIR/frontend/context/AuthContext.tsx" \
    "$DIR/frontend/App.tsx" 2>/dev/null || true)
  local IMP TOP
  for IMP in $IMPORTS_RAW; do
    IMP="${IMP#from }"
    IMP="${IMP#[\"\'\`]}"; IMP="${IMP%[\"\'\`}]"
    if [[ "$IMP" == @* ]]; then
      TOP=$(echo "$IMP" | cut -d/ -f1-2)
    else
      TOP=$(echo "$IMP" | cut -d/ -f1)
    fi
    if [[ -z "$TOP" || "$TOP" == "sonner" ]]; then
      continue
    fi
    mkdir -p "$DIR/frontend/node_modules/$TOP"
    printf '{"name":"%s","version":"0.0.0"}\n' "$TOP" \
      > "$DIR/frontend/node_modules/$TOP/package.json"
  done
}

# Build a PATH shim that simulates `corepack pnpm install` behaviour.
# $1 = behaviour ("success" or "failure")
# $2 = path where the shim marker file should live
# Writes the shim directory to stdout.
setup_shim() {
  local BEHAVIOR="$1"
  local SHIM_DIR
  SHIM_DIR=$(mktemp -d)
  TEMP_DIRS+=("$SHIM_DIR")

  cat > "$SHIM_DIR/corepack" <<EOSHIM
#!/usr/bin/env bash
# test shim — simulates \`corepack pnpm install\` behaviour
MARKER="$SHIM_DIR/.invoked"
touch "\$MARKER"
case "$BEHAVIOR" in
  success)
    mkdir -p "\$PWD/node_modules/sonner"
    printf '{"name":"sonner","version":"2.0.7"}\n' \\
      > "\$PWD/node_modules/sonner/package.json"
    exit 0
    ;;
  failure)
    echo "Simulated install failure" >&2
    exit 1
    ;;
esac
EOSHIM
  chmod +x "$SHIM_DIR/corepack"
  printf '%s\n' "$SHIM_DIR"
}

# Compute lockfile SHA-256 (matches the implementation's sentinel hash).
lockfile_hash() {
  sha256sum "$1" | awk '{print $1}'
}

# ---- assertion helpers -----------------------------------------------------

assert_file_exists() {
  local FILE="$1"; local MSG="$2"
  if [[ -f "$FILE" ]]; then
    return 0
  fi
  printf '    assertion failed: %s (missing: %s)\n' "$MSG" "$FILE" >&2
  return 1
}

assert_file_absent() {
  local FILE="$1"; local MSG="$2"
  if [[ ! -e "$FILE" ]]; then
    return 0
  fi
  printf '    assertion failed: %s (present: %s)\n' "$MSG" "$FILE" >&2
  return 1
}

assert_eq() {
  local EXPECT="$1"; local ACTUAL="$2"; local MSG="$3"
  if [[ "$EXPECT" == "$ACTUAL" ]]; then
    return 0
  fi
  printf '    assertion failed: %s (expected %q, got %q)\n' \
    "$MSG" "$EXPECT" "$ACTUAL" >&2
  return 1
}

# ---- tests -----------------------------------------------------------------

test_recovery_path() {
  local NAME="recovery: missing sonner -> install + sentinel + exit 0"
  TOTAL=$((TOTAL + 1))

  local FIXTURE SHIM_DIR SCRIPT SENTINEL HASH OUT ERR EXIT_CODE TARGET SENTINEL_VALUE
  FIXTURE=$(mktemp -d); TEMP_DIRS+=("$FIXTURE")
  SHIM_DIR=$(setup_shim success)
  setup_fixture "$FIXTURE"
  SCRIPT="$FIXTURE/scripts/check-frontend-deps.sh"
  SENTINEL="$FIXTURE/frontend/.frontend-deps-ok"
  HASH=$(lockfile_hash "$FIXTURE/frontend/pnpm-lock.yaml")

  # Pre-condition: sentinel absent, sonner absent
  if [[ ! -f "$SCRIPT" ]]; then
    record_fail "$NAME (script under test missing: $SCRIPT)"
    return
  fi
  assert_file_absent "$SENTINEL" "pre: sentinel must be absent" || {
    record_fail "$NAME"; return; }

  OUT=$(mktemp); ERR=$(mktemp); TEMP_DIRS+=("$OUT" "$ERR")
  ( cd "$FIXTURE" && PATH="$SHIM_DIR:$PATH" bash "$SCRIPT" ) >"$OUT" 2>"$ERR"
  EXIT_CODE=$?

  if ! assert_eq 0 "$EXIT_CODE" "exit code"; then
    record_fail "$NAME"; printf '    stdout: %s\n    stderr: %s\n' \
      "$(cat "$OUT")" "$(cat "$ERR")" >&2; return
  fi
  if ! assert_file_exists "$SENTINEL" "sentinel written"; then
    record_fail "$NAME"; return
  fi
  SENTINEL_VALUE=$(cat "$SENTINEL" 2>/dev/null || true)
  SENTINEL_VALUE="${SENTINEL_VALUE%$'\n'}"
  if ! assert_eq "$HASH" "$SENTINEL_VALUE" "sentinel matches lockfile SHA-256"; then
    record_fail "$NAME"; return
  fi
  if ! assert_file_exists \
       "$FIXTURE/frontend/node_modules/sonner/package.json" \
       "sonner populated"; then
    record_fail "$NAME"; return
  fi
  if [[ ! -f "$SHIM_DIR/.invoked" ]]; then
    printf '    assertion failed: shim was not invoked\n' >&2
    record_fail "$NAME"; return
  fi

  record_pass "$NAME"
}

test_no_op_sentinel_path() {
  local NAME="no-op: matching sentinel + resolved imports -> exit 0, no install"
  TOTAL=$((TOTAL + 1))

  local FIXTURE SHIM_DIR SCRIPT SENTINEL HASH OUT ERR EXIT_CODE BEFORE_MTIME AFTER_MTIME SENTINEL_VALUE
  FIXTURE=$(mktemp -d); TEMP_DIRS+=("$FIXTURE")
  SHIM_DIR=$(setup_shim success)
  setup_fixture "$FIXTURE"
  SCRIPT="$FIXTURE/scripts/check-frontend-deps.sh"
  SENTINEL="$FIXTURE/frontend/.frontend-deps-ok"
  HASH=$(lockfile_hash "$FIXTURE/frontend/pnpm-lock.yaml")

  if [[ ! -f "$SCRIPT" ]]; then
    record_fail "$NAME (script under test missing: $SCRIPT)"
    return
  fi

  # Pre-create sentinel + sonner stub to simulate "everything already resolved"
  printf '%s\n' "$HASH" > "$SENTINEL"
  local BEFORE_MTIME
  BEFORE_MTIME=$(stat -c '%Y.%N' "$SENTINEL" 2>/dev/null || stat -f '%m' "$SENTINEL")
  mkdir -p "$FIXTURE/frontend/node_modules/sonner"
  printf '{"name":"sonner","version":"2.0.7"}\n' \
    > "$FIXTURE/frontend/node_modules/sonner/package.json"
  # Sleep so any rewrite would change mtime
  sleep 1.1

  OUT=$(mktemp); ERR=$(mktemp); TEMP_DIRS+=("$OUT" "$ERR")
  ( cd "$FIXTURE" && PATH="$SHIM_DIR:$PATH" bash "$SCRIPT" ) >"$OUT" 2>"$ERR"
  EXIT_CODE=$?

  if ! assert_eq 0 "$EXIT_CODE" "exit code"; then
    record_fail "$NAME"; printf '    stdout: %s\n    stderr: %s\n' \
      "$(cat "$OUT")" "$(cat "$ERR")" >&2; return
  fi
  if [[ -f "$SHIM_DIR/.invoked" ]]; then
    printf '    assertion failed: shim was invoked (install ran on no-op path)\n' >&2
    record_fail "$NAME"; return
  fi
  AFTER_MTIME=$(stat -c '%Y.%N' "$SENTINEL" 2>/dev/null || stat -f '%m' "$SENTINEL")
  if ! assert_eq "$BEFORE_MTIME" "$AFTER_MTIME" "sentinel mtime preserved"; then
    record_fail "$NAME"; return
  fi
  SENTINEL_VALUE=$(cat "$SENTINEL" 2>/dev/null || true)
  SENTINEL_VALUE="${SENTINEL_VALUE%$'\n'}"
  if ! assert_eq "$HASH" "$SENTINEL_VALUE" "sentinel value preserved"; then
    record_fail "$NAME"; return
  fi

  record_pass "$NAME"
}

test_install_failure_path() {
  local NAME="install-failure: shim returns non-zero -> non-zero exit, no sentinel"
  TOTAL=$((TOTAL + 1))

  local FIXTURE SHIM_DIR SCRIPT SENTINEL OUT ERR EXIT_CODE
  FIXTURE=$(mktemp -d); TEMP_DIRS+=("$FIXTURE")
  SHIM_DIR=$(setup_shim failure)
  setup_fixture "$FIXTURE"
  SCRIPT="$FIXTURE/scripts/check-frontend-deps.sh"
  SENTINEL="$FIXTURE/frontend/.frontend-deps-ok"

  if [[ ! -f "$SCRIPT" ]]; then
    record_fail "$NAME (script under test missing: $SCRIPT)"
    return
  fi
  assert_file_absent "$SENTINEL" "pre: sentinel must be absent" || {
    record_fail "$NAME"; return; }

  OUT=$(mktemp); ERR=$(mktemp); TEMP_DIRS+=("$OUT" "$ERR")
  ( cd "$FIXTURE" && PATH="$SHIM_DIR:$PATH" bash "$SCRIPT" ) >"$OUT" 2>"$ERR"
  EXIT_CODE=$?

  if [[ "$EXIT_CODE" -eq 0 ]]; then
    printf '    assertion failed: expected non-zero exit, got 0\n' >&2
    record_fail "$NAME"; printf '    stdout: %s\n    stderr: %s\n' \
      "$(cat "$OUT")" "$(cat "$ERR")" >&2; return
  fi
  if ! assert_file_absent "$SENTINEL" "sentinel must NOT be written on failure"; then
    record_fail "$NAME"; return
  fi
  # Sanity: the shim was actually invoked (otherwise we'd be testing the wrong thing)
  if [[ ! -f "$SHIM_DIR/.invoked" ]]; then
    printf '    assertion failed: shim was not invoked\n' >&2
    record_fail "$NAME"; return
  fi
  # Sanity: stderr contains a meaningful install-failure message
  if ! grep -qi 'install\|fail\|error' "$ERR"; then
    printf '    assertion failed: stderr lacks install/failure keyword\n' >&2
    record_fail "$NAME"; printf '    stderr: %s\n' "$(cat "$ERR")" >&2; return
  fi

  record_pass "$NAME"
}

# ---- main ------------------------------------------------------------------

printf 'Running RED-first bash tests for scripts/check-frontend-deps.sh\n'
test_recovery_path
test_no_op_sentinel_path
test_install_failure_path

printf '\n%d/%d passed\n' "$PASSED" "$TOTAL"

if [[ "$PASSED" -ne "$TOTAL" ]]; then
  printf 'FAILURES:\n' >&2
  for NAME in "${FAILED_NAMES[@]}"; do
    printf '  - %s\n' "$NAME" >&2
  done
  exit 1
fi

exit 0