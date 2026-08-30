#!/bin/sh
# Operational smoke for mqtt-subscriber (#387).
#
# Closes the gap documented in docs/mqtt-monitoring.md "Known gaps and
# follow-up work" by giving operators one POSIX-portable command that
# proves the subscriber can transition from absent → active by reading
# /api/mqtt/status. Does NOT modify /api/mqtt/status, the subscriber,
# any schema, or .env.example. See
# openspec/changes/feat-mqtt-387-ops-smoke/{proposal,design,spec}.md
# for the contract.
#
# Flow (no destructive subcommand, no volume-removing verb):
#   1. Validate env via scripts/validate-env.sh (NEO4J_*, POSTGRES_*).
#   2. Probe MQTT_BROKER_URL presence via the json output of the
#      config subcommand of the compose plugin.
#   3. GET /api/mqtt/status (cookied); if connected is false, assert
#      last_message_at is null OR older than the stale threshold.
#   4. Bring the subscriber up via the up minus d form of compose.
#   5. Poll /api/mqtt/status until connected is true (bounded) or timeout.
#   6. With --with-fixture: publish a tagged MQTT message and confirm
#      visibility in /api/mqtt/readings (bounded).
#   7. Print rollback block on every exit via the EXIT trap.

set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)
cd "$REPO_ROOT"

WITH_FIXTURE=0
STATUS_URL=${MQTT_SMOKE_STATUS_URL:-http://localhost:8000/api/mqtt/status}
READINGS_URL=${MQTT_SMOKE_READINGS_URL:-http://localhost:8000/api/mqtt/readings?limit=50}

usage() {
    cat <<'USAGE'
Usage: sh scripts/mqtt-ops-smoke.sh [--with-fixture] [-h|--help]

Operator smoke for the mqtt-subscriber Compose service (#387). The script
proves that the absent -> active transition is observable through
/api/mqtt/status without mutating persistent state.

Environment variables:
  COOKIE_JAR                                 Path to a cookie jar holding an
                                             authenticated session with the
                                             MQTT_READ permission. Defaults to
                                             $HOME/.mqtt_cookie when set.
  MQTT_SUBSCRIBER_STALE_HEARTBEAT_SECONDS    Seconds used to define a "stale"
                                             last_message_at when the subscriber
                                             is absent. Default: 90.
  MQTT_SMOKE_ACTIVATION_TIMEOUT_SECONDS      Max seconds to wait for the
                                             subscriber to report connected=true
                                             after Step 4 brings it up.
                                             Default: 60.
  MQTT_SMOKE_FIXTURE_TIMEOUT_SECONDS         Max seconds to wait for the fixture
                                             tag to appear in /api/mqtt/readings.
                                             Default: 30.
  MQTT_SMOKE_STATUS_URL                      Override the status endpoint.
                                             Default: http://localhost:8000/api/mqtt/status
  MQTT_SMOKE_READINGS_URL                    Override the readings endpoint.
                                             Default: http://localhost:8000/api/mqtt/readings?limit=50
  MQTT_BROKER_HOST                           Hostname for mosquitto_pub during
                                             fixture publishing. Default: broker.

Options:
  --with-fixture   After activation, publish a uniquely tagged MQTT
                   message and confirm it appears in /api/mqtt/readings.
  -h, --help       Print this help and exit 0.

Exit codes:
  0   success (subscriber confirmed active; optional fixture visible)
  1   validation failed or assertions failed (rollback printed via trap)
  2   usage error

The script NEVER uses destructive verbs (down, rm, the volume flag, or
any other volume-removing verb). Verify with:
  sh scripts/test-mqtt-ops-smoke.sh
USAGE
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --with-fixture)
            WITH_FIXTURE=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
    shift
done

# Rollback block printed on every exit via the EXIT trap below. Failure
# scripts reference this as the operator's recovery path. Do not edit
# without re-reading docs/mqtt-monitoring.md "Operational smoke (#387)".
rollback_message() {
    cat <<'ROLLBACK'

Rollback (mqtt operational smoke -- #387):
  docker compose stop mqtt-subscriber    # stops container, preserves data

DO NOT use the destructive subcommand or any volume-removing verb.
This script never executes those operations; the offline test
(bash scripts/test-mqtt-ops-smoke.sh) enforces that as a static
invariant.
ROLLBACK
}

trap rollback_message EXIT
trap 'exit 1' INT TERM

fail() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 1
}

# Portable ISO8601 -> epoch. Tries GNU `date -d`, then BSD `date -j -f`,
# then python3 via a temporary helper file. POSIX `sh` does not
# standardize a date-parsing utility, so we accept whichever helper
# exists on the host operator and degrade gracefully. Returns the epoch
# on stdout and exits non-zero on parse failure.
iso_to_epoch() {
    iso=$1
    # GNU date accepts the full ISO8601 string unchanged.
    e=$(date -u -d "$iso" +%s 2>/dev/null) || e=
    if [ -n "$e" ]; then
        printf '%s\n' "$e"
        return 0
    fi
    # BSD date (macOS) needs -j -f with a format string. Strip fractional
    # seconds and trailing Z/tz for the simplified format attempts.
    short=$(printf '%s' "$iso" \
        | sed -E 's/\.[0-9]+//;s/Z$//')
    if e=$(date -j -f "%Y-%m-%dT%H:%M:%S%z" "$short" +%s 2>/dev/null) \
        && [ -n "$e" ]; then
        printf '%s\n' "$e"
        return 0
    fi
    if e=$(date -j -f "%Y-%m-%dT%H:%M:%S" "$short" +%s 2>/dev/null) \
        && [ -n "$e" ]; then
        printf '%s\n' "$e"
        return 0
    fi
    # python3 fallback. Write the helper to a temp file instead of
    # embedding a heredoc inside the command substitution (some `sh -n`
    # implementations mis-parse function-call syntax inside `$()`).
    if command -v python3 >/dev/null 2>&1; then
        tmp_py=$(mktemp -t iso-to-epoch.XXXXXX)
        # shellcheck disable=SC2068
        cat >"$tmp_py" <<'PY_EOF'
import datetime, sys
ts = sys.argv[1].replace("Z", "+00:00")
print(int(datetime.datetime.fromisoformat(ts).timestamp()))
PY_EOF
        if e=$(python3 "$tmp_py" "$iso" 2>/dev/null) && [ -n "$e" ]; then
            rm -f "$tmp_py"
            printf '%s\n' "$e"
            return 0
        fi
        rm -f "$tmp_py"
    fi
    return 1
}

# Cookie jar -- we do not test the absence of auth (operators own their
# session); we fail loud when the call returns non-zero (401 / network).
COOKIE_JAR_DEFAULT="$HOME/.mqtt_cookie"
if [ -n "${COOKIE_JAR:-}" ]; then
    : # honor explicit override
elif [ -r "$COOKIE_JAR_DEFAULT" ]; then
    COOKIE_JAR=$COOKIE_JAR_DEFAULT
fi
if [ -z "${COOKIE_JAR:-}" ] || [ ! -r "${COOKIE_JAR:-/nonexistent}" ]; then
    fail "auth required: set COOKIE_JAR to a readable file with an MQTT_READ cookie"
fi

# Step 1: credential contract via the shared validator.
sh scripts/validate-env.sh

# Step 2: broker URL probe -- authoritative because it reflects the
# final resolved Compose project (incl. ${VAR} interpolation).
broker_json=$(docker compose config --format json 2>/dev/null) \
    || fail 'docker compose config failed; is the stack reachable?'
case "$broker_json" in
    *'"MQTT_BROKER_URL"'*|*'"MQTT_BROKER_URL":'*)
        : # present (allow unresolved ${...} placeholders to remain)
        ;;
    *)
        fail 'missing env: MQTT_BROKER_URL (not present in docker compose config)'
        ;;
esac
broker_url_value=$(printf '%s\n' "$broker_json" \
    | sed -n 's/.*"MQTT_BROKER_URL":[[:space:]]*"\([^"]*\)".*/\1/p')
[ -n "$broker_url_value" ] || broker_url_value=${MQTT_BROKER_URL:-}

# Step 3: read the status. curl -fsS is non-zero on HTTP >= 400 so 401 is
# fail-loud, matching the 401 -> fail-loud contract.
status=$(curl -fsS -b "$COOKIE_JAR" "$STATUS_URL") \
    || fail "auth/HTTP error: GET $STATUS_URL returned non-zero (likely 401 or unavailable)"

# Step 3a: absent branch. Soft check: if already active, skip the
# absent-state assertion entirely (mirrors Scenario: subscriber already
# active at start in spec/mqtt-operational-smoke).
if printf '%s' "$status" | grep -qE '"connected":[[:space:]]*false'; then
    case "$status" in
        *'"last_message_at":null'*|*'"last_message_at":null,'*)
            printf 'absent branch: connected=false, last_message_at=null\n'
            ;;
        *)
            last=$(printf '%s' "$status" \
                | sed -n 's/.*"last_message_at":"\([^"]*\)".*/\1/p')
            [ -n "$last" ] || fail 'status JSON missing last_message_at string value'
            last_epoch=$(iso_to_epoch "$last") \
                || fail "could not parse last_message_at ISO8601: $last"
            now_epoch=$(date -u +%s)
            age=$(( now_epoch - last_epoch ))
            threshold=${MQTT_SUBSCRIBER_STALE_HEARTBEAT_SECONDS:-90}
            if [ "$age" -lt "$threshold" ]; then
                fail "absent branch stale too recent: age=${age}s < threshold=${threshold}s; last=$last"
            fi
            printf 'absent branch: connected=false, last_message_at age=%ss (>=%ss)\n' "$age" "$threshold"
            ;;
    esac
else
    if printf '%s' "$status" | grep -qE '"connected":[[:space:]]*true'; then
        printf 'subscriber already active; skipping absent assertion\n'
    else
        fail 'status JSON missing expected `connected` field'
    fi
fi

# Step 4: bring the subscriber up via the safe subcommand. NEVER the
# destructive verb, NEVER the volume-removing flag.
docker compose up -d mqtt-subscriber

# Step 5: bounded poll for connected=true.
activation_timeout=${MQTT_SMOKE_ACTIVATION_TIMEOUT_SECONDS:-60}
deadline=$(( $(date -u +%s) + activation_timeout ))
last_payload=
while :; do
    now=$(date -u +%s)
    if [ "$now" -ge "$deadline" ]; then
        fail "activation timeout after ${activation_timeout}s; last status: ${last_payload:-<empty>}"
    fi
    s=$(curl -fsS -b "$COOKIE_JAR" "$STATUS_URL" 2>/dev/null) || s=
    last_payload=$s
    if printf '%s' "$s" | grep -qE '"connected":[[:space:]]*true'; then
        printf 'active branch confirmed\n'
        break
    fi
    sleep 2
done

# Step 6: optional fixture. Only after activation.
if [ "$WITH_FIXTURE" -eq 1 ]; then
    tag="smoke-$(date -u +%s)-$$"
    broker_host=${MQTT_BROKER_HOST:-broker}
    # The subscriber container reaches the broker via docker network DNS.
    docker compose exec -T mqtt-subscriber \
        mosquitto_pub -h "$broker_host" -t "smoke/$tag" -m "$tag" \
        || fail "fixture publish via mosquitto_pub failed (broker_host=$broker_host)"

    fixture_timeout=${MQTT_SMOKE_FIXTURE_TIMEOUT_SECONDS:-30}
    fixture_deadline=$(( $(date -u +%s) + fixture_timeout ))
    found=0
    while [ "$(date -u +%s)" -lt "$fixture_deadline" ]; do
        body=$(curl -fsS -b "$COOKIE_JAR" "$READINGS_URL" 2>/dev/null) || body=
        if printf '%s' "$body" | grep -F "$tag" >/dev/null 2>&1; then
            found=1
            break
        fi
        sleep 2
    done
    if [ "$found" -ne 1 ]; then
        fail "fixture timeout after ${fixture_timeout}s; tag $tag not visible"
    fi
    printf 'fixture confirmed: tag=%s visible in /api/mqtt/readings\n' "$tag"
fi

# Step 7: success terminal. The EXIT trap prints the rollback block.
exit 0
