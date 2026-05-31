#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$REPO_ROOT"

failures=0

fail() {
    printf 'FAIL: %s\n' "$1" >&2
    failures=$((failures + 1))
}

assert_exit_code() {
    expected=$1
    shift
    set +e
    "$@" >/tmp/neo4j-offline-test-out.$$ 2>/tmp/neo4j-offline-test-err.$$
    actual=$?
    set -e
    rm -f /tmp/neo4j-offline-test-out.$$ /tmp/neo4j-offline-test-err.$$
    if [ "$actual" -ne "$expected" ]; then
        fail "expected exit $expected from: $*; got $actual"
    fi
}

assert_help_contains() {
    script=$1
    if ! sh "$script" --help | grep -q -- '--neo4j-offline'; then
        fail "$script help should document --neo4j-offline"
    fi
}

assert_help_contains scripts/pre-rebuild-backup.sh
assert_help_contains scripts/safe-rebuild.sh
assert_exit_code 2 sh scripts/pre-rebuild-backup.sh --skip-neo4j --neo4j-offline
assert_exit_code 2 sh scripts/safe-rebuild.sh --skip-neo4j --neo4j-offline
assert_exit_code 2 sh scripts/pre-rebuild-backup.sh --unknown-option
assert_exit_code 2 sh scripts/safe-rebuild.sh --unknown-option

if [ "${PRE_REBUILD_BACKUP_LIB_ONLY:-}" = "1" ]; then
    fail 'test should not inherit PRE_REBUILD_BACKUP_LIB_ONLY'
fi

if [ "$failures" -gt 0 ]; then
    exit 1
fi

printf 'neo4j offline backup flag tests passed\n'
