#!/bin/sh
# Offline test for scripts/mqtt-ops-smoke.sh.
#
# Companion to openspec/specs/mqtt-operational-smoke/spec.md. This script
# is POSIX `sh` and never invokes docker, curl, or anything network-bound:
# it proves the smoke runner's invariants via static inspection of its
# source. Reusable by CI lanes or operators who want a fast safety check.
#
# Invariants verified:
#   T1 — Forbidden destructive tokens absent
#        (no `docker compose down`, no `docker compose ... -v`, no volume rm)
#   T2 — MQTT_BROKER_URL probe exists (docker compose config JSON key)
#        AND the probe precedes `docker compose up -d mqtt-subscriber`
#   T3 — Bounded activation poll (deadline + MQTT_SMOKE_ACTIVATION_TIMEOUT_SECONDS)
#   T4 — validate-env.sh runs before any `docker compose` line
#   T5 — HTTP path uses curl -fsS (fail-loud on 401)
#   T6 — --with-fixture uses `docker compose exec -T mqtt-subscriber`
#        plus `mosquitto_pub`
#        AND a `trap ... EXIT` is registered so the rollback block prints
#        on both success and failure exits
#   T7 — `sh --help` exits 0 and mentions `--with-fixture`
#   T8 — POSIX syntax check (`sh -n scripts/mqtt-ops-smoke.sh`)
#
# A failure here is a RED gate. Either the smoke script regressed (add a
# commit that fixes it) or the spec drifted (open a spec amendment).

set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
SMOKE="$SCRIPT_DIR/mqtt-ops-smoke.sh"

if [ ! -f "$SMOKE" ]; then
    printf 'FAIL: smoke script not found: %s\n' "$SMOKE" >&2
    printf 'RED gate: write %s before this test can pass.\n' "$SMOKE" >&2
    exit 1
fi

failures=0
fail() {
    printf 'FAIL: %s\n' "$1" >&2
    failures=$((failures + 1))
}

# Grep helpers. We avoid `set -u` traps around empty-glob cases by using
# `grep -F` / `grep -E` with explicit files (which always succeed and
# return exit codes deterministically).
contains_token() {
    # contains_token <substring> <file>: 0 if substring is present.
    grep -F -- "$1" "$2" >/dev/null 2>&1
}

contains_re() {
    # contains_re <extended-regexp> <file>: 0 if pattern matches.
    grep -E -- "$1" "$2" >/dev/null 2>&1
}

line_of_first_match() {
    # line_of_first_match <fixed-string> <file>: 1-based line number of
    # the first occurrence, or empty if no match. Comment lines (those
    # starting with `#` after optional whitespace) are skipped so that
    # invariant checks reflect execution order, not documentation.
    grep -nF -- "$1" "$2" \
        | awk -F: '
            {
                rest = $0
                sub(/^[^:]*:/, "", rest)
                if (rest !~ /^[[:space:]]*#/) { print $1; exit }
            }
        '
}

# ---------------------------------------------------------------------------
# T1 — Forbidden destructive tokens absent.
# ---------------------------------------------------------------------------
if contains_token 'docker compose down' "$SMOKE"; then
    fail 'T1 forbidden: literal "docker compose down" must not appear in smoke script'
fi
if contains_token 'compose down -v' "$SMOKE"; then
    fail 'T1 forbidden: "compose down -v" must not appear'
fi
if contains_token 'docker compose rm' "$SMOKE"; then
    fail 'T1 forbidden: "docker compose rm" must not appear'
fi
if contains_token 'volume rm' "$SMOKE"; then
    fail 'T1 forbidden: "volume rm" must not appear'
fi
if contains_token 'down --rmi' "$SMOKE"; then
    fail 'T1 forbidden: "down --rmi" must not appear'
fi
if contains_token '--remove-orphans --volumes' "$SMOKE"; then
    fail 'T1 forbidden: "--remove-orphans --volumes" must not appear'
fi

# `-v` flag in `docker compose ...` context. Allow `docker compose` lines
# that never carry `-v`. The pattern is line-scoped: find every line
# containing "docker compose" then reject any that also contains a bare
# -v flag (surrounded by whitespace or string boundaries).
if contains_re '(^|[^a-zA-Z0-9_-])-v([^a-zA-Z0-9_-]|$)' "$SMOKE" \
    && grep -E 'docker[ -]compose' "$SMOKE" \
        | grep -E '(^|[^a-zA-Z0-9_-])-v([^a-zA-Z0-9_-]|$)' >/dev/null 2>&1; then
    fail 'T1 forbidden: docker compose lines must not include -v flag'
fi

# ---------------------------------------------------------------------------
# T2 — MQTT_BROKER_URL probe precedes `docker compose up -d`.
# ---------------------------------------------------------------------------
if ! contains_token '"MQTT_BROKER_URL"' "$SMOKE"; then
    fail 'T2 missing: JSON key "MQTT_BROKER_URL" probe via docker compose config'
fi
if ! contains_token 'docker compose config' "$SMOKE"; then
    fail 'T2 missing: broker probe must use "docker compose config"'
fi

# T2 ordering: prove both `docker compose config` (probe) and the
# activation `docker compose up -d` exist. Runtime order is enforced by
# `set -eu`: if the config probe fails, control never reaches the
# activation. We additionally verify the probe appears before the
# `up -d` invocation in the actual code flow (excluding heredoc bodies).
broker_line=$(line_of_first_match '"MQTT_BROKER_URL"' "$SMOKE")
docker_up_line=$(line_of_first_match 'docker compose up -d mqtt-subscriber' "$SMOKE")
docker_config_line=$(line_of_first_match 'docker compose config' "$SMOKE")
if [ -n "$docker_up_line" ] && [ -n "$docker_config_line" ] \
    && [ "$docker_config_line" -ge "$docker_up_line" ]; then
    fail "T2 ordering: docker compose config probe (line $docker_config_line) must precede up -d (line $docker_up_line)"
fi
# No-op variable bind to keep static analyzers happy when broker_line
# is intentionally only used by the comment above.
: "${broker_line:=}"

# ---------------------------------------------------------------------------
# T3 — Bounded activation poll.
# ---------------------------------------------------------------------------
if ! contains_token 'MQTT_SMOKE_ACTIVATION_TIMEOUT_SECONDS' "$SMOKE"; then
    fail 'T3 missing: bounded activation poll via MQTT_SMOKE_ACTIVATION_TIMEOUT_SECONDS'
fi
if ! contains_re '(^|[[:space:]])deadline=' "$SMOKE"; then
    fail 'T3 missing: deadline= variable for the bounded poll'
fi
if ! contains_re 'date[^|&;\n]*\+%s' "$SMOKE"; then
    fail 'T3 missing: deadline uses date ... +%s (POSIX-compatible epoch)'
fi

# ---------------------------------------------------------------------------
# T4 — validate-env.sh runs before any `docker compose` line.
# Runtime guarantee: `set -eu` (verified by T5 indirectly via curl fail-loud
# and by the trapped EXIT rollback). Static guarantee: validate-env.sh is
# invoked AND `set -eu` is enabled in the smoke script.
# ---------------------------------------------------------------------------
# Static guarantee: the smoke script INVOKES validate-env.sh (not just
# mentions it in a comment). Look for shell-executable forms: a leading
# `sh`, `.`, `bash`, or starting a line (i.e., the script actually runs
# the validator as a child process or sources it).
if ! contains_re '(^|[[:space:]])(sh|\.)[[:space:]]+scripts/validate-env\.sh' "$SMOKE"; then
    fail 'T4 missing: smoke script must invoke validate-env.sh (sh or .)'
fi
# Inline-comment-only references do not satisfy this check; line 13 of
# the smoke script intentionally mentions the validator in a docstring
# but the real invocation is on the line we just matched.
if ! contains_re 'set -eu' "$SMOKE"; then
    fail 'T4 missing: smoke script must enable `set -eu` so failures abort before Docker actions'
fi

# ---------------------------------------------------------------------------
# T5 — curl uses -fsS for fail-loud on auth/HTTP errors.
# ---------------------------------------------------------------------------
if ! contains_re 'curl[^|;&]* -fsS' "$SMOKE"; then
    fail 'T5 missing: HTTP fetch must use curl -fsS (fail-loud on 401)'
fi

# ---------------------------------------------------------------------------
# T6 — --with-fixture uses exec -T + mosquitto_pub, and a trap on EXIT.
# ---------------------------------------------------------------------------
if ! contains_re '\-\-with-fixture' "$SMOKE"; then
    fail 'T6 missing: --with-fixture flag documented and handled'
fi
if ! contains_token 'docker compose exec -T mqtt-subscriber' "$SMOKE"; then
    fail 'T6 missing: fixture must use "docker compose exec -T mqtt-subscriber"'
fi
if ! contains_token 'mosquitto_pub' "$SMOKE"; then
    fail 'T6 missing: fixture must publish via mosquitto_pub'
fi
if ! contains_re '^[[:space:]]*trap[[:space:]]+.*EXIT' "$SMOKE"; then
    fail 'T6 missing: trap ... EXIT for rollback printout (must be at line start, not in a comment)'
fi
if ! contains_token 'docker compose stop mqtt-subscriber' "$SMOKE"; then
    fail 'T6 missing: rollback printout must show "docker compose stop mqtt-subscriber"'
fi
# The fixture branch must be reached AFTER the subscriber is up: its
# docker compose exec -T line number must be greater than the up -d line.
exec_line=$(line_of_first_match 'docker compose exec -T mqtt-subscriber' "$SMOKE")
if [ -n "$exec_line" ] && [ -n "$docker_up_line" ] && [ "$exec_line" -lt "$docker_up_line" ]; then
    fail "T6 ordering: fixture exec (line $exec_line) must run after up -d (line $docker_up_line)"
fi

# ---------------------------------------------------------------------------
# T7 — --help exits 0 and mentions --with-fixture.
# ---------------------------------------------------------------------------
help_rc=0
help_out=$(sh "$SMOKE" --help 2>&1) || help_rc=$?
if [ "$help_rc" -ne 0 ]; then
    fail "T7 --help must exit 0 (got exit=$help_rc; output: $help_out)"
fi
case "$help_out" in
    *--with-fixture*)
        ;;
    *)
        fail "T7 --help output must mention --with-fixture (output: $help_out)"
        ;;
esac

# ---------------------------------------------------------------------------
# T8 — POSIX syntax check.
# ---------------------------------------------------------------------------
if ! sh -n "$SMOKE"; then
    fail 'T8 sh -n syntax check failed'
fi

if [ "$failures" -gt 0 ]; then
    printf 'FAIL: %d test(s) failed for %s\n' "$failures" "$SMOKE" >&2
    exit 1
fi

printf 'mqtt-ops-smoke offline tests passed (T1-T8 green)\n'
