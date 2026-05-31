#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

SAFE_REBUILD_LIB_ONLY=1
export SAFE_REBUILD_LIB_ONLY
# shellcheck source=scripts/safe-rebuild.sh
. "$SCRIPT_DIR/safe-rebuild.sh"

failures=0

fail() {
    printf 'FAIL: %s\n' "$1" >&2
    failures=$((failures + 1))
}

assert_normalized() {
    input=$1
    expected=$2
    actual=$(normalize_backup_dir_for_check "$input")
    if [ "$actual" != "$expected" ]; then
        fail "normalize '$input': expected '$expected', got '$actual'"
    fi
}

assert_refused() {
    input=$1
    if ( refuse_unsafe_backup_dir "$input" ) >/tmp/safe-rebuild-test-out.$$ 2>/tmp/safe-rebuild-test-err.$$; then
        fail "expected unsafe BACKUP_DIR to be refused: $input"
    fi
    rm -f /tmp/safe-rebuild-test-out.$$ /tmp/safe-rebuild-test-err.$$
}

assert_allowed() {
    input=$1
    if ! ( refuse_unsafe_backup_dir "$input" ) >/tmp/safe-rebuild-test-out.$$ 2>/tmp/safe-rebuild-test-err.$$; then
        fail "expected BACKUP_DIR to be allowed: $input"
    fi
    rm -f /tmp/safe-rebuild-test-out.$$ /tmp/safe-rebuild-test-err.$$
}

assert_normalized './..' '..'
assert_normalized '/tmp/../tmp' '/tmp'
assert_normalized '/var/../tmp' '/tmp'
assert_normalized '/private/tmp/../tmp' '/private/tmp'
assert_normalized '.docker/../.docker/backups' '.docker/backups'
assert_normalized 'foo\\bar//baz/./qux' 'foo/bar/baz/qux'

assert_refused './..'
assert_refused '/tmp/../tmp'
assert_refused '/var/../tmp'
assert_refused '/private/tmp/../tmp'
assert_refused '/foo/../../tmp'
assert_allowed '.docker/backups'
assert_allowed './.docker/../.docker/backups'
assert_allowed 'backups/ci'

if [ "$failures" -gt 0 ]; then
    exit 1
fi

printf 'safe-rebuild path validation tests passed\n'
