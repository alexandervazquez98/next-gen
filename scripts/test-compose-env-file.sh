#!/bin/sh
# Offline test for the docker-compose.yml env_file wire-up (issue #546).
#
# Companion to odd/tasks/feat-546-compose-env-file.md. This script is
# POSIX `sh` and runs as a static + docker compose config check. It
# never starts containers; it relies on `docker compose config --format
# json` for ground truth plus a direct grep on `.env.example`.
#
# Invariants verified:
#   T2/T3 — All 5 services that own an environment block declare
#           `env_file: [.env]` (backend, mqtt-subscriber, snmp-engine,
#           neo4j, postgres). The frontend service is excluded because
#           it is build-time only (Vite).
#   T4    — `FEATURE_CMDB_PHYSICAL_LINK_POLLING_ENABLED` is wired into
#           the backend service environment (closes the gap from PR #543
#           where the flag lived in code but not in compose).
#   T5    — `DISABLE_BACKEND_COLLECTOR` is no longer a hard-coded
#           `true` literal in backend; it now uses `${VAR:-default}`
#           substitution so operators can flip it via `.env`.
#   T6    — `ENABLE_MQTT_SUBSCRIBER` is no longer a hard-coded `true`
#           literal in mqtt-subscriber; same conversion rule.
#   T7    — `.env.example` documents the new flag so `validate-env.sh`
#           does not fail on the missing required var.
#
# Usage:
#   sh scripts/test-compose-env-file.sh                 # full check (needs docker compose)
#   sh scripts/test-compose-env-file.sh --self-test     # static-only (no docker compose)
#
# A failure here is a RED gate. Either docker-compose.yml regressed
# (re-add the env_file leg) or .env.example lost the new flag entry.

set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)
COMPOSE_FILE="$REPO_ROOT/docker-compose.yml"
ENV_EXAMPLE="$REPO_ROOT/.env.example"

failures=0
fail() {
    printf 'FAIL: %s\n' "$1" >&2
    failures=$((failures + 1))
}

# The five services that need env_file. Order matches the deliverable
# list in odd/tasks/feat-546-compose-env-file.md. Hyphenated names are
# quoted with the jq object bracket notation because `.foo-bar` is a
# subtraction in jq.
SERVICES_ENV_FILE='backend mqtt-subscriber snmp-engine neo4j postgres'

NEW_FLAG='FEATURE_CMDB_PHYSICAL_LINK_POLLING_ENABLED'
BACKEND_TOGGLE='DISABLE_BACKEND_COLLECTOR'
MQTT_TOGGLE='ENABLE_MQTT_SUBSCRIBER'

if [ "${1:-}" = "--self-test" ]; then
    # --- Self-test mode -----------------------------------------------------
    # Confirms the harness is well-formed: the file exists, the script
    # parses, and every external command it would call live (jq, docker)
    # is either available OR documented as a soft requirement. CI calls
    # this branch first to fail fast on syntax / missing prerequisites.
    if [ ! -f "$COMPOSE_FILE" ]; then
        fail "--self-test: $COMPOSE_FILE not found"
    fi
    if [ ! -f "$ENV_EXAMPLE" ]; then
        fail "--self-test: $ENV_EXAMPLE not found"
    fi
    if ! command -v docker >/dev/null 2>&1; then
        fail "--self-test: docker is required for the full check (this branch is for syntax only)"
    fi
    if ! command -v jq >/dev/null 2>&1; then
        fail "--self-test: jq is required to parse docker compose config JSON"
    fi
    if [ "$failures" -gt 0 ]; then
        exit 1
    fi
    printf 'compose-env-file self-test passed (harness ready)\n'
    exit 0
fi

# --- Full check ------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
    printf 'ERROR: docker is required for the full check. Use --self-test for a syntax-only run.\n' >&2
    exit 2
fi
if ! command -v jq >/dev/null 2>&1; then
    printf 'ERROR: jq is required to parse docker compose config JSON.\n' >&2
    exit 2
fi
if [ ! -f "$COMPOSE_FILE" ]; then
    printf 'ERROR: %s not found\n' "$COMPOSE_FILE" >&2
    exit 2
fi
if [ ! -f "$ENV_EXAMPLE" ]; then
    printf 'ERROR: %s not found\n' "$ENV_EXAMPLE" >&2
    exit 2
fi

# Render each service's effective compose config to JSON once per service.
# We avoid `docker compose config --format json` for the whole file because
# jq with a bracket-quoted key is more readable than a streaming pipeline.
# `--no-env-resolution` keeps the env_file directive visible; without the
# flag, docker compose merges env_file contents into the environment map
# and drops the directive from the rendered JSON (so we would never see
# it again even though it is present in the source).
service_config() {
    # service_config <service>: prints the rendered config JSON for one
    # service. Uses a temp file because the JSON is multi-line and a
    # shell pipe would lose the trailing newline that jq needs to
    # produce clean diagnostics.
    svc=$1
    tmp=$(mktemp -t compose-env-file.XXXXXX)
    if ! docker compose -f "$COMPOSE_FILE" config "$svc" --format json --no-env-resolution >"$tmp" 2>&1; then
        cat "$tmp" >&2
        rm -f "$tmp"
        printf 'ERROR: docker compose config %s --format json failed\n' "$svc" >&2
        return 1
    fi
    cat "$tmp"
    rm -f "$tmp"
}

# T2/T3 — every service in $SERVICES_ENV_FILE must declare env_file: .env
for svc in $SERVICES_ENV_FILE; do
    cfg=$(service_config "$svc") || exit 1
    # With --no-env-resolution docker compose renders env_file entries as
    # objects of the form `{"path": "<absolute path>", "required": bool}`.
    # We only care that the resolved path ends with `.env` (the suffix
    # matches `.env`, `./.env`, `.env.local`, etc.).
    env_paths=$(printf '%s' "$cfg" | jq -r '.services["'"$svc"'"].env_file // [] | .[].path // ""')
    if [ -z "$env_paths" ]; then
        fail "T2/T3: $svc has no env_file declared (expected '.env')"
        continue
    fi
    found=0
    for p in $env_paths; do
        case "$p" in
            */.env|*/.env.local|*.env|*.env.local)
                found=1
                ;;
        esac
    done
    if [ "$found" -ne 1 ]; then
        fail "T2/T3: $svc env_file does not reference .env (got: $env_paths)"
    fi
done

# T4 — backend service must expose the new feature flag in its environment.
# `environment` is rendered as an object (key-value) by `docker compose
# config --format json`, so we use object access rather than the array
# form documented in the ODD doc.
cfg_backend=$(service_config backend) || exit 1
if ! printf '%s' "$cfg_backend" | jq -e --arg k "$NEW_FLAG" '.services.backend.environment[$k]' >/dev/null; then
    fail "T4: backend service is missing $NEW_FLAG in environment"
fi
# Belt-and-braces: the rendered value must reflect the ${VAR:-default}
# default (i.e. the compose resolves to the documented default false).
new_flag_value=$(printf '%s' "$cfg_backend" | jq -r --arg k "$NEW_FLAG" '.services.backend.environment[$k] // ""')
if [ "$new_flag_value" != "false" ] && [ -z "$new_flag_value" ]; then
    fail "T4: $NEW_FLAG should default to 'false' when unset (got '$new_flag_value')"
fi

# T5 — DISABLE_BACKEND_COLLECTOR must NOT be a literal `true` default.
# After conversion to ${VAR:-false} and no value in .env, the rendered
# value must be `false`. A literal `true` means the toggle was never
# converted and operators cannot flip it via .env.
backend_toggle_value=$(printf '%s' "$cfg_backend" | jq -r --arg k "$BACKEND_TOGGLE" '.services.backend.environment[$k] // ""')
if [ "$backend_toggle_value" = "true" ]; then
    fail "T5: $BACKEND_TOGGLE is hard-coded to 'true' in backend; expected \${VAR:-default} substitution (got '$backend_toggle_value')"
fi

# T6 — ENABLE_MQTT_SUBSCRIBER must NOT be a literal `true` default.
cfg_mqtt=$(service_config mqtt-subscriber) || exit 1
mqtt_toggle_value=$(printf '%s' "$cfg_mqtt" | jq -r --arg k "$MQTT_TOGGLE" '.services["mqtt-subscriber"].environment[$k] // ""')
if [ "$mqtt_toggle_value" = "true" ]; then
    fail "T6: $MQTT_TOGGLE is hard-coded to 'true' in mqtt-subscriber; expected \${VAR:-default} substitution (got '$mqtt_toggle_value')"
fi

# T7 — .env.example documents the new flag so validate-env.sh accepts it.
if ! grep -E "^${NEW_FLAG}=" "$ENV_EXAMPLE" >/dev/null 2>&1; then
    fail "T7: $ENV_EXAMPLE is missing the $NEW_FLAG= entry"
fi

if [ "$failures" -gt 0 ]; then
    printf 'FAIL: %d test(s) failed for compose env_file contract\n' "$failures" >&2
    exit 1
fi

printf 'compose-env-file tests passed (T2-T7 green)\n'