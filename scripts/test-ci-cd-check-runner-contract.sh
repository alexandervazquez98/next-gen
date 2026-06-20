#!/bin/sh
# Test: scripts/ci-cd-check-runner-contract.sh
#
# T6.5 strict-TDD evidence for the runner contract script invoked by
# .github/workflows/cd.yml (commit C). Mirrors the SAFE_REBUILD_LIB_ONLY
# pattern used by scripts/test-safe-rebuild-path-validation.sh.
#
# Test coverage (per the user's task contract):
#   (a) docker unusable          -> exit 1
#   (b) missing BACKUP_DIR       -> exit 1
#   (c) all conditions mocked    -> exit 0
#
# Strategy: create a temporary sandbox, install stub docker/gh binaries
# on a fake PATH that takes priority over the real /usr/bin, and run the
# contract script with controlled inputs.
#
# Note on test (a): "docker missing" is simulated with a stub docker that
# exits 127 with no output. On a host where /usr/bin and /bin are
# symlinked (Arch, NixOS, etc.), it is impractical to remove the real
# docker binary from PATH without also removing sh itself. An
# exit-127/no-output stub is functionally equivalent: the contract's
# `command -v docker` finds the stub, then `docker compose version`
# fails with no v2 banner, and the contract exits 1 — exactly the
# observable behavior of a runner where docker is not installed.

set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
CONTRACT="$SCRIPT_DIR/ci-cd-check-runner-contract.sh"

if [ ! -f "$CONTRACT" ]; then
    printf 'FAIL: contract script not found: %s\n' "$CONTRACT" >&2
    printf 'RED gate: write %s before this test can pass.\n' "$CONTRACT" >&2
    exit 1
fi

WORK=$(mktemp -d -t runner-contract-test.XXXXXX)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"

# Stub docker (a): exits 127 with no output — emulates "docker missing"
# in a way that is observable by the contract script.
cat >"$WORK/bin/docker" <<'STUB'
#!/bin/sh
exit 127
STUB
chmod +x "$WORK/bin/docker"

failures=0

assert_exit() {
    expected=$1
    label=$2
    shift 2
    set +e
    ( "$@" ) >"$WORK/out" 2>"$WORK/err"
    actual=$?
    set -e
    out=$(cat "$WORK/out" 2>/dev/null || printf '')
    err=$(cat "$WORK/err" 2>/dev/null || printf '')
    if [ "$actual" -ne "$expected" ]; then
        printf 'FAIL: %s\n' "$label" >&2
        printf '  expected exit %d, got %d\n' "$expected" "$actual" >&2
        printf '  stdout: %s\n' "$out" >&2
        printf '  stderr: %s\n' "$err" >&2
        failures=$((failures + 1))
    fi
}

# Pre-flight: place .env + a writable BACKUP_DIR in the sandbox.
touch "$WORK/.env"
mkdir -p "$WORK/backups"

# (a) docker exits 127 with no output -> contract exits 1.
#     We rely on the stub taking precedence on PATH.
assert_exit 1 'docker missing/broken -> exit 1' \
    sh -c 'cd "$1" && PATH="$2/bin:$PATH" BACKUP_DIR="$2/backups" sh "$3"' \
    sh "$WORK" "$WORK" "$CONTRACT"

# (b) Swap to a working docker stub + gh stub, then point BACKUP_DIR at
#     a nonexistent path -> contract exits 1.
cat >"$WORK/bin/docker" <<'STUB'
#!/bin/sh
case "$1 $2" in
    "compose version")
        printf 'Docker Compose version v2.27.0\n'
        exit 0
        ;;
esac
exit 0
STUB
chmod +x "$WORK/bin/docker"

cat >"$WORK/bin/gh" <<'STUB'
#!/bin/sh
if [ "$1" = "auth" ] && [ "$2" = "status" ]; then
    printf 'Logged in to github.com as next-gen-deploy-bot\n'
    exit 0
fi
exit 0
STUB
chmod +x "$WORK/bin/gh"

assert_exit 1 'missing BACKUP_DIR -> exit 1' \
    sh -c 'cd "$1" && PATH="$2/bin:$PATH" BACKUP_DIR="$2/no-such-dir" sh "$3"' \
    sh "$WORK" "$WORK" "$CONTRACT"

# (c) all conditions mocked -> exit 0.
assert_exit 0 'all conditions mocked -> exit 0' \
    sh -c 'cd "$1" && PATH="$2/bin:$PATH" BACKUP_DIR="$2/backups" sh "$3"' \
    sh "$WORK" "$WORK" "$CONTRACT"

if [ "$failures" -gt 0 ]; then
    printf 'FAIL: %d runner-contract test(s) failed\n' "$failures" >&2
    exit 1
fi

printf 'runner contract tests passed (a) docker broken (b) BACKUP_DIR missing (c) all mocked\n'
