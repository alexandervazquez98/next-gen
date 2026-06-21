#!/bin/sh
# RED-first shell tests for frontend anonymous-volume renewal in
# scripts/safe-rebuild.sh.
#
# Coverage:
#   Helpers (source-library mode):
#     * compute_frontend_lockfile_hash returns sha256sum of frontend/pnpm-lock.yaml
#     * frontend_lockfile_changed returns 0 (changed) / 1 (unchanged)
#     * maybe_renew_frontend_anonymous_volume calls docker compose up -d
#       --force-recreate --renew-anon-volumes frontend only when changed
#
#   End-to-end (sandbox + stub docker, per spec R1-R4):
#     * R1: unchanged sentinel -> no --renew-anon-volumes
#     * R2: changed sentinel  -> renew command scoped to `frontend` (final arg)
#     * R3: --dry-run         -> prints renew command, does not exec docker
#     * R4: any path          -> no `docker compose down -v` and no `docker volume rm`
#
# Strict-TDD gate: this file MUST exit non-zero until T3 (helpers) and T4
# (wiring) land. Helper existence + end-to-end R2 / R3 are the RED
# assertions; R1 / R4 act as regression guards.

set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)
SAFE_REBUILD="$SCRIPT_DIR/safe-rebuild.sh"
VALIDATE_ENV="$SCRIPT_DIR/validate-env.sh"
PRE_REBUILD_BACKUP="$SCRIPT_DIR/pre-rebuild-backup.sh"

if [ ! -f "$SAFE_REBUILD" ]; then
    printf 'FAIL: safe-rebuild.sh not found at %s\n' "$SAFE_REBUILD" >&2
    exit 1
fi

failures=0
fail() {
    printf 'FAIL: %s\n' "$1" >&2
    failures=$((failures + 1))
}

# Sandbox paths used by trap cleanup. Initialised early so the trap never
# sees an unbound variable under `set -u`.
HB_SANDBOX=
HB_STUBDIR=
E2E_SB=
E2E_SB2=
E2E_SB3=
cleanup_all() {
    [ -n "$HB_SANDBOX" ] && rm -rf "$HB_SANDBOX" 2>/dev/null || true
    [ -n "$HB_STUBDIR" ] && rm -rf "$HB_STUBDIR" 2>/dev/null || true
    [ -n "$E2E_SB" ]   && rm -rf "$E2E_SB"   2>/dev/null || true
    [ -n "$E2E_SB2" ]  && rm -rf "$E2E_SB2"  2>/dev/null || true
    [ -n "$E2E_SB3" ]  && rm -rf "$E2E_SB3"  2>/dev/null || true
}
trap cleanup_all EXIT

# ---------------------------------------------------------------------------
# Phase 1: source library via SAFE_REBUILD_LIB_ONLY=1 and assert helpers
# ---------------------------------------------------------------------------

SAFE_REBUILD_LIB_ONLY=1
export SAFE_REBUILD_LIB_ONLY
# shellcheck source=scripts/safe-rebuild.sh
. "$SAFE_REBUILD"

if ! type compute_frontend_lockfile_hash >/dev/null 2>&1; then
    fail 'helper compute_frontend_lockfile_hash is not defined'
fi
if ! type frontend_lockfile_changed >/dev/null 2>&1; then
    fail 'helper frontend_lockfile_changed is not defined'
fi
if ! type maybe_renew_frontend_anonymous_volume >/dev/null 2>&1; then
    fail 'helper maybe_renew_frontend_anonymous_volume is not defined'
fi

helpers_ok=0
if type compute_frontend_lockfile_hash >/dev/null 2>&1 \
    && type frontend_lockfile_changed >/dev/null 2>&1 \
    && type maybe_renew_frontend_anonymous_volume >/dev/null 2>&1; then
    helpers_ok=1
fi

# ---------------------------------------------------------------------------
# Phase 2: helper behavior tests (skip until helpers are defined)
# ---------------------------------------------------------------------------

if [ "$helpers_ok" -eq 1 ]; then
    HB_SANDBOX=$(mktemp -d -t safe-rebuild-helper.XXXXXX)
    HB_STUBDIR=$(mktemp -d -t safe-rebuild-stub.XXXXXX)

    mkdir -p "$HB_SANDBOX/frontend"
    printf 'lockfileVersion: "9.0"\n' > "$HB_SANDBOX/frontend/pnpm-lock.yaml"
    expected_hash=$(sha256sum "$HB_SANDBOX/frontend/pnpm-lock.yaml" | awk '{print $1}')

    cat >"$HB_STUBDIR/docker" <<STUB
#!/bin/sh
echo "\$*" >> "$HB_SANDBOX/docker.log"
case "\$*" in
    "compose ps -q "*)
        printf 'fake-container-id\n'
        exit 0
        ;;
esac
exit 0
STUB
    chmod +x "$HB_STUBDIR/docker"
    : > "$HB_SANDBOX/docker.log"

    (
        export PATH="$HB_STUBDIR:$PATH"
        cd "$HB_SANDBOX"
        backup_dir="$HB_SANDBOX"
        dry_run=0
        frontend_lockfile_hash=

        # compute_frontend_lockfile_hash returns the SHA-256 of the lockfile.
        actual_hash=$(compute_frontend_lockfile_hash)
        if [ "$actual_hash" != "$expected_hash" ]; then
            fail "compute_frontend_lockfile_hash: expected $expected_hash, got $actual_hash"
        fi

        # Matching sentinel -> frontend_lockfile_changed returns 1 (unchanged).
        printf '%s\n' "$expected_hash" > "$HB_SANDBOX/frontend-pnpm-lock.sha256"
        set +e
        frontend_lockfile_changed
        rc=$?
        set -e
        if [ "$rc" -ne 1 ]; then
            fail "frontend_lockfile_changed: matching sentinel must return 1 (no change), got $rc"
        fi

        # Missing sentinel -> frontend_lockfile_changed returns 0 (changed).
        rm -f "$HB_SANDBOX/frontend-pnpm-lock.sha256"
        set +e
        frontend_lockfile_changed
        rc=$?
        set -e
        if [ "$rc" -ne 0 ]; then
            fail "frontend_lockfile_changed: missing sentinel must return 0 (changed), got $rc"
        fi

        # Stale sentinel -> frontend_lockfile_changed returns 0 (changed).
        printf 'stale-hash\n' > "$HB_SANDBOX/frontend-pnpm-lock.sha256"
        set +e
        frontend_lockfile_changed
        rc=$?
        set -e
        if [ "$rc" -ne 0 ]; then
            fail "frontend_lockfile_changed: stale sentinel must return 0 (changed), got $rc"
        fi

        # maybe_renew_frontend_anonymous_volume with matching sentinel: no renew.
        : > "$HB_SANDBOX/docker.log"
        printf '%s\n' "$expected_hash" > "$HB_SANDBOX/frontend-pnpm-lock.sha256"
        set +e
        maybe_renew_frontend_anonymous_volume
        rc=$?
        set -e
        if [ "$rc" -ne 0 ]; then
            fail "maybe_renew_frontend_anonymous_volume: matching sentinel must return 0, got $rc"
        fi
        if grep -q -- '--renew-anon-volumes' "$HB_SANDBOX/docker.log" 2>/dev/null; then
            fail 'maybe_renew_frontend_anonymous_volume: matching sentinel must not invoke --renew-anon-volumes'
        fi
        if [ -s "$HB_SANDBOX/docker.log" ]; then
            fail "maybe_renew_frontend_anonymous_volume: matching sentinel must not exec docker; log: $(cat "$HB_SANDBOX/docker.log")"
        fi

        # maybe_renew_frontend_anonymous_volume with stale sentinel: emits renew
        # command scoped to `frontend`, updates sentinel after success.
        : > "$HB_SANDBOX/docker.log"
        printf 'stale-hash\n' > "$HB_SANDBOX/frontend-pnpm-lock.sha256"
        set +e
        maybe_renew_frontend_anonymous_volume
        rc=$?
        set -e
        if [ "$rc" -ne 0 ]; then
            fail "maybe_renew_frontend_anonymous_volume: stale sentinel must return 0, got $rc"
        fi
        if ! grep -q 'compose up -d --force-recreate --renew-anon-volumes frontend' "$HB_SANDBOX/docker.log"; then
            fail "maybe_renew_frontend_anonymous_volume: stale sentinel must exec 'docker compose up -d --force-recreate --renew-anon-volumes frontend'; log: $(cat "$HB_SANDBOX/docker.log")"
        fi
        # The final arg of the renew command MUST be `frontend`.
        last_line=$(awk 'END{print}' "$HB_SANDBOX/docker.log")
        last_token=$(printf '%s\n' "$last_line" | awk '{print $NF}')
        if [ "$last_token" != "frontend" ]; then
            fail "maybe_renew_frontend_anonymous_volume: renew command final arg must be 'frontend', got '$last_token'"
        fi
        # Sentinel must be updated to the current hash after a successful renew.
        new_sentinel=$(cat "$HB_SANDBOX/frontend-pnpm-lock.sha256" 2>/dev/null || printf '')
        new_sentinel=$(printf '%s\n' "$new_sentinel" | sed 's/[[:space:]]*$//')
        if [ "$new_sentinel" != "$expected_hash" ]; then
            fail "maybe_renew_frontend_anonymous_volume: sentinel must equal current hash after renew; expected $expected_hash, got $new_sentinel"
        fi

        # maybe_renew_frontend_anonymous_volume in dry-run: prints renew but
        # does NOT exec docker and does NOT write sentinel.
        : > "$HB_SANDBOX/docker.log"
        rm -f "$HB_SANDBOX/frontend-pnpm-lock.sha256"
        printf 'stale-hash\n' > "$HB_SANDBOX/frontend-pnpm-lock.sha256"
        dry_run=1
        set +e
        maybe_renew_frontend_anonymous_volume
        rc=$?
        set -e
        dry_run=0
        if [ "$rc" -ne 0 ]; then
            fail "maybe_renew_frontend_anonymous_volume: dry-run must return 0, got $rc"
        fi
        if [ -s "$HB_SANDBOX/docker.log" ]; then
            fail "maybe_renew_frontend_anonymous_volume: dry-run must not exec docker; log: $(cat "$HB_SANDBOX/docker.log")"
        fi
        if [ -f "$HB_SANDBOX/frontend-pnpm-lock.sha256" ]; then
            stale=$(cat "$HB_SANDBOX/frontend-pnpm-lock.sha256" 2>/dev/null || printf '')
            if [ "$stale" != "stale-hash" ]; then
                fail "maybe_renew_frontend_anonymous_volume: dry-run must not update sentinel"
            fi
        fi
    )
fi

# ---------------------------------------------------------------------------
# Phase 3: end-to-end tests (sandbox + stub docker)
# ---------------------------------------------------------------------------

setup_sandbox() {
    local SB="$1"
    mkdir -p "$SB/scripts" "$SB/frontend" "$SB/.docker/backups" "$SB/.stub-bin"
    # A valid .env so validate-env.sh passes. Copy .env.example for the
    # contract (it diffs both files) but provide safe-secret values for
    # sensitive vars so validate-env.sh does not reject placeholders.
    cp "$REPO_ROOT/.env.example" "$SB/.env.example"
    cat >"$SB/.env" <<'ENVEOF'
NEO4J_USER=neo4j
NEO4J_PASSWORD='production-safe-neo4j-pass-1234'
POSTGRES_USER=nexgen_admin
POSTGRES_PASSWORD='production-safe-postgres-pass-1234'
POSTGRES_DB=nexgen_auth
NEO4J_URI=bolt://neo4j:7687
POSTGRES_HOST=postgres
POSTGRES_INTERNAL_PORT=5432
POSTGRES_EXTERNAL_PORT=5432
BACKUP_DIR=.docker/backups
JWT_SECRET_KEY='production-safe-jwt-secret-key-1234567890abcdef'
COOKIE_SECURE=false
VITE_API_TARGET=http://backend:8000
FRONTEND_ORIGIN=http://localhost:5173
SNMP_DEFAULT_COMMUNITY=public
POLLING_CYCLE_SECONDS=10
ICMP_LATENCY_WARNING_MS=100
ICMP_LATENCY_CRITICAL_MS=500
POLLING_PIPELINE_OBSERVE_ONLY=false
POLLING_PG_QUEUE_ENABLED=false
POLLING_SNMP_LEASED_WORKER=false
POLLING_DB_WRITER_ENABLED=false
POLLING_BACKPRESSURE_ENABLED=false
POLLING_METADATA_CACHE_ENABLED=false
POLLING_TARGET_CYCLE_SECONDS=900
POLLING_WORKERS=8
POLLING_DB_WRITERS=1
POLLING_TASK_BATCH_SIZE=100
POLLING_RESULT_BATCH_SIZE=500
POLLING_BACKPRESSURE_MAX_TASK_QUEUE_DEPTH=100000
POLLING_BACKPRESSURE_MAX_WRITER_LAG_SECONDS=120
POLLING_BACKPRESSURE_RETRY_MAX_ATTEMPTS=5
POLLING_METADATA_CACHE_TTL_SECONDS=300
POLLING_BENCHMARK_CI_COUNT=8000
POLLING_BENCHMARK_METRICS_PER_CI=35
POLLING_BENCHMARK_DURATION_SECONDS=0
POLLING_BENCHMARK_PROTOCOL_MIX=ICMP:0.15,SNMP:0.55,CLI:0.15,REST:0.10,MQTT_STUB:0.05
POLLING_BENCHMARK_SINK=synthetic
LM_STUDIO_ENABLED=false
LM_STUDIO_BASE_URL=http://host.docker.internal:1234/v1
LM_STUDIO_MODEL=local-model
LM_STUDIO_TIMEOUT_SECONDS=15
AI_PROMPTS_DIR=
AI_PROMPTS_DIR_HOST=.docker/ai
CLI_DEFAULT_USER=
CLI_DEFAULT_PASS=
CLI_ENABLE_PASS=
ENVEOF
    cp "$SAFE_REBUILD" "$SB/scripts/safe-rebuild.sh"
    cp "$VALIDATE_ENV" "$SB/scripts/validate-env.sh"
    cp "$PRE_REBUILD_BACKUP" "$SB/scripts/pre-rebuild-backup.sh"
    chmod +x "$SB/scripts/safe-rebuild.sh" "$SB/scripts/validate-env.sh" "$SB/scripts/pre-rebuild-backup.sh"
    cp "$REPO_ROOT/frontend/pnpm-lock.yaml" "$SB/frontend/pnpm-lock.yaml"

    # Stub docker. Logs every invocation to docker.log for assertion;
    # `compose ps -q <svc>` returns a fake id so require_running_service passes.
    cat >"$SB/.stub-bin/docker" <<STUB
#!/bin/sh
echo "\$*" >> "$SB/docker.log"
case "\$*" in
    "compose ps -q "*)
        printf 'fake-container-id\n'
        exit 0
        ;;
esac
exit 0
STUB
    chmod +x "$SB/.stub-bin/docker"
    : > "$SB/docker.log"
}

run_safe_rebuild() {
    # Args: SB EXTRA_ARGS...
    # Does NOT override BACKUP_DIR env so .docker/backups (relative) resolves
    # in the sandbox and passes refuse_unsafe_backup_dir.
    local SB="$1"
    shift
    set +e
    ( cd "$SB" && PATH="$SB/.stub-bin:$PATH" \
        sh scripts/safe-rebuild.sh "$@" ) >"$SB/safe-rebuild.out" 2>"$SB/safe-rebuild.err"
    local rc=$?
    set -e
    return $rc
}

# --- R1: unchanged sentinel -> no --renew-anon-volumes ---
E2E_SB=$(mktemp -d -t safe-rebuild-e2e-r1.XXXXXX)
# Unset SAFE_REBUILD_LIB_ONLY so the sandbox runs the full main flow,
# not the library short-circuit.
unset SAFE_REBUILD_LIB_ONLY
setup_sandbox "$E2E_SB"
matching_hash=$(sha256sum "$E2E_SB/frontend/pnpm-lock.yaml" | awk '{print $1}')
printf '%s\n' "$matching_hash" > "$E2E_SB/.docker/backups/frontend-pnpm-lock.sha256"

if run_safe_rebuild "$E2E_SB"; then
    if grep -q -- '--renew-anon-volumes' "$E2E_SB/docker.log" 2>/dev/null; then
        fail 'R1: matching sentinel must not produce any --renew-anon-volumes command'
    fi
    # R4 regression guard: only inspect actually-executed docker commands
    # (docker.log), not the script's informational output which mentions
    # the destructive commands as warnings to operators.
    if grep -q -- 'docker compose down -v' "$E2E_SB/docker.log"; then
        fail 'R4: safe-rebuild must never exec `docker compose down -v`'
    fi
    if grep -q -- 'docker volume rm' "$E2E_SB/docker.log"; then
        fail 'R4: safe-rebuild must never exec `docker volume rm`'
    fi
else
    fail "R1: safe-rebuild.sh exited non-zero (rc=$?); see $E2E_SB/safe-rebuild.err"
fi

# --- R2: stale sentinel -> renew command scoped to frontend ---
E2E_SB2=$(mktemp -d -t safe-rebuild-e2e-r2.XXXXXX)
setup_sandbox "$E2E_SB2"
printf 'stale-hash-from-previous-deploy\n' > "$E2E_SB2/.docker/backups/frontend-pnpm-lock.sha256"

if run_safe_rebuild "$E2E_SB2"; then
    renew_line=$(grep 'compose up -d --force-recreate --renew-anon-volumes' "$E2E_SB2/docker.log" 2>/dev/null || true)
    if [ -z "$renew_line" ]; then
        fail "R2: stale sentinel must produce 'docker compose up -d --force-recreate --renew-anon-volumes'; docker.log: $(cat "$E2E_SB2/docker.log")"
    else
        last_token=$(printf '%s\n' "$renew_line" | awk '{print $NF}')
        if [ "$last_token" != "frontend" ]; then
            fail "R2: renew command final arg must be 'frontend', got '$last_token'"
        fi
    fi
    if grep -q -- 'docker compose down -v' "$E2E_SB2/docker.log"; then
        fail 'R4: safe-rebuild must never exec `docker compose down -v`'
    fi
    if grep -q -- 'docker volume rm' "$E2E_SB2/docker.log"; then
        fail 'R4: safe-rebuild must never exec `docker volume rm`'
    fi
    # After a successful renew, the sentinel must equal the current hash.
    new_sentinel=$(cat "$E2E_SB2/.docker/backups/frontend-pnpm-lock.sha256" 2>/dev/null || printf '')
    expected=$(sha256sum "$E2E_SB2/frontend/pnpm-lock.yaml" | awk '{print $1}')
    if [ "$new_sentinel" != "$expected" ]; then
        fail "R2: sentinel must equal current hash after successful renew; expected $expected, got $new_sentinel"
    fi
else
    fail "R2: safe-rebuild.sh exited non-zero; see $E2E_SB2/safe-rebuild.err"
fi

# --- R3: --dry-run prints renew but does not exec docker ---
E2E_SB3=$(mktemp -d -t safe-rebuild-e2e-r3.XXXXXX)
setup_sandbox "$E2E_SB3"
printf 'stale-hash-from-previous-deploy\n' > "$E2E_SB3/.docker/backups/frontend-pnpm-lock.sha256"

if run_safe_rebuild "$E2E_SB3" --dry-run; then
    if ! grep -q -- 'docker compose up -d --force-recreate --renew-anon-volumes frontend' "$E2E_SB3/safe-rebuild.out"; then
        fail "R3: --dry-run must print the frontend renew command; out: $(cat "$E2E_SB3/safe-rebuild.out")"
    fi
    if [ -s "$E2E_SB3/docker.log" ]; then
        fail "R3: --dry-run must not exec docker; docker.log: $(cat "$E2E_SB3/docker.log")"
    fi
    # R4 regression guard for dry-run path: inspect only the planned
    # commands (lines starting with '+ ' from the run() wrapper), not the
    # informational warning text at the end of safe-rebuild.sh.
    if grep -q -- '^+ .*docker compose down -v' "$E2E_SB3/safe-rebuild.out"; then
        fail 'R4: dry-run must not plan `docker compose down -v`'
    fi
    if grep -q -- '^+ .*docker volume rm' "$E2E_SB3/safe-rebuild.out"; then
        fail 'R4: dry-run must not plan `docker volume rm`'
    fi
else
    fail "R3: safe-rebuild.sh --dry-run exited non-zero; see $E2E_SB3/safe-rebuild.err"
fi

# ---------------------------------------------------------------------------

if [ "$failures" -gt 0 ]; then
    printf 'safe-rebuild frontend-volume tests FAILED (%d failure(s))\n' "$failures" >&2
    exit 1
fi

printf 'safe-rebuild frontend-volume tests passed\n'