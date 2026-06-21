#!/bin/sh
# RED-first shell tests for scripts/refresh-frontend-deps.sh.
#
# Coverage (per spec R5-R8):
#   * R5: normal execution prints `+ docker compose up -d --force-recreate
#         --renew-anon-volumes frontend` and runs that command
#   * R6: --dry-run prints the command but does NOT exec docker
#   * R7: missing docker exits non-zero with a clear missing-command message
#   * R8: unsupported flag --skip-neo4j exits 2 with usage, no docker exec;
#         -h|--help exits 0
#
# Strict-TDD gate: this file MUST exit non-zero until T5 lands.
# R5 / R6 / R7 / R8 are all RED assertions because the script does not
# exist yet. Stub `docker` via a fake PATH for end-to-end command capture.

set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)
REFRESH_SCRIPT="$SCRIPT_DIR/refresh-frontend-deps.sh"

failures=0
fail() {
    printf 'FAIL: %s\n' "$1" >&2
    failures=$((failures + 1))
}

# RED-gate: the script-under-test must exist. If T5 has not landed yet,
# this exits non-zero and the rest of the test file is not exercised —
# but every requirement below also fails because the script does not exist.
if [ ! -f "$REFRESH_SCRIPT" ]; then
    printf 'FAIL: refresh-frontend-deps.sh not found at %s\n' "$REFRESH_SCRIPT" >&2
    printf 'FAIL: R5: refresh script must run `docker compose up -d --force-recreate --renew-anon-volumes frontend`\n' >&2
    printf 'FAIL: R6: refresh script must support --dry-run without exec\n' >&2
    printf 'FAIL: R7: refresh script must fail clearly when docker is missing\n' >&2
    printf 'FAIL: R8: refresh script must reject unsupported flags\n' >&2
    exit 1
fi

# Sandbox for stub docker + captured command log.
WORK=$(mktemp -d -t refresh-frontend-deps.XXXXXX)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"

# Stub docker. Logs every invocation; compose ps -q returns a fake id;
# everything else returns 0.
cat >"$WORK/bin/docker" <<STUB
#!/bin/sh
echo "\$*" >> "$WORK/docker.log"
case "\$*" in
    "compose ps -q "*)
        printf 'fake-container-id\n'
        exit 0
        ;;
esac
exit 0
STUB
chmod +x "$WORK/bin/docker"

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
    # Return the captured streams via globals for follow-up checks.
    LAST_OUT=$out
    LAST_ERR=$err
}

# --- R5: normal execution runs the frontend-scoped renew command ---
: > "$WORK/docker.log"
assert_exit 0 'R5: normal run exits 0' \
    sh -c 'cd "$1" && PATH="$2/bin:$PATH" sh "$3"' \
    sh "$REPO_ROOT" "$WORK" "$REFRESH_SCRIPT"
if [ "$failures" -eq 0 ]; then
    if ! grep -q -- 'compose up -d --force-recreate --renew-anon-volumes frontend' "$WORK/docker.log"; then
        fail "R5: must exec 'docker compose up -d --force-recreate --renew-anon-volumes frontend'; log: $(cat "$WORK/docker.log")"
    else
        last_line=$(awk 'END{print}' "$WORK/docker.log")
        last_token=$(printf '%s\n' "$last_line" | awk '{print $NF}')
        if [ "$last_token" != "frontend" ]; then
            fail "R5: renew command final arg must be 'frontend', got '$last_token'"
        fi
    fi
    if ! printf '%s\n' "$LAST_OUT" | grep -q -- '+ docker compose up -d --force-recreate --renew-anon-volumes frontend'; then
        fail "R5: must print '+ docker compose up -d --force-recreate --renew-anon-volumes frontend'; out: $LAST_OUT"
    fi
fi

# --- R6: --dry-run prints but does not exec docker ---
: > "$WORK/docker.log"
assert_exit 0 'R6: --dry-run exits 0' \
    sh -c 'cd "$1" && PATH="$2/bin:$PATH" sh "$3" --dry-run' \
    sh "$REPO_ROOT" "$WORK" "$REFRESH_SCRIPT"
if [ -s "$WORK/docker.log" ]; then
    fail "R6: --dry-run must not exec docker; log: $(cat "$WORK/docker.log")"
fi
if ! printf '%s\n' "$LAST_OUT" | grep -q -- '+ docker compose up -d --force-recreate --renew-anon-volumes frontend'; then
    fail "R6: --dry-run must print '+ docker compose up -d --force-recreate --renew-anon-volumes frontend'; out: $LAST_OUT"
fi

# --- R7: missing docker exits non-zero with missing-command message ---
# Run the script with PATH set to a directory that does NOT contain docker.
# Place a sh symlink in the empty dir so the script's interpreter can still
# be located; this isolates the failure to `docker` being absent.
EMPTY_PATH=$(mktemp -d -t refresh-empty.XXXXXX)
trap 'rm -rf "$WORK" "$EMPTY_PATH"' EXIT
SH_PATH=$(command -v sh)
ln -s "$SH_PATH" "$EMPTY_PATH/sh"
set +e
( PATH="$EMPTY_PATH" sh "$REFRESH_SCRIPT" ) >"$WORK/out" 2>"$WORK/err"
rc=$?
set -e
out=$(cat "$WORK/out" 2>/dev/null || printf '')
err=$(cat "$WORK/err" 2>/dev/null || printf '')
if [ "$rc" -eq 0 ]; then
    fail "R7: missing docker must exit non-zero, got exit 0"
fi
combined="$out
$err"
case "$combined" in
    *docker*|*Docker*) ;;
    *) fail "R7: missing-docker failure must mention docker; got out=$out err=$err" ;;
esac

# --- R8: unsupported flag --skip-neo4j exits 2, no docker exec ---
: > "$WORK/docker.log"
assert_exit 2 'R8: --skip-neo4j exits 2' \
    sh -c 'PATH="$1/bin:$PATH" sh "$2" --skip-neo4j' \
    sh "$WORK" "$REFRESH_SCRIPT"
if [ -s "$WORK/docker.log" ]; then
    fail "R8: --skip-neo4j must not exec docker; log: $(cat "$WORK/docker.log")"
fi
if [ -z "$LAST_ERR" ]; then
    fail "R8: --skip-neo4j must print usage to stderr"
fi

# --- R8 (help): -h and --help exit 0 ---
assert_exit 0 'R8: -h exits 0' \
    sh -c 'PATH="$1/bin:$PATH" sh "$2" -h' \
    sh "$WORK" "$REFRESH_SCRIPT"
assert_exit 0 'R8: --help exits 0' \
    sh -c 'PATH="$1/bin:$PATH" sh "$2" --help' \
    sh "$WORK" "$REFRESH_SCRIPT"

# ---------------------------------------------------------------------------

if [ "$failures" -gt 0 ]; then
    printf 'refresh-frontend-deps tests FAILED (%d failure(s))\n' "$failures" >&2
    exit 1
fi

printf 'refresh-frontend-deps tests passed\n'