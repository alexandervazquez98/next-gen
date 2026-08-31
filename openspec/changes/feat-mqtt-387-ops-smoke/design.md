# Design: MQTT Monitoring Operational Smoke (#387)

## Context

`docs/mqtt-monitoring.md` lists `#387` as a known gap: operators reconstruct prose steps to prove `mqtt-subscriber` heartbeats flow through `/api/mqtt/status`. The change ships one POSIX `sh` script, one offline test, and a runbook section. No backend/router/schema/`.env.example` edits.

## Goals / Non-Goals

**Goals** — `sh scripts/mqtt-ops-smoke.sh` asserts absent → starts subscriber via `docker compose up -d` → asserts active heartbeat. Fail-loud on missing `MQTT_BROKER_URL`, missing DB credentials, or 401. `--with-fixture` publishes a tagged message and confirms `/api/mqtt/readings` visibility. Rollback printout on every exit.

**Non-Goals** — no changes to `/api/mqtt/status`, subscriber, schema, or `.env.example`; no CI wiring; no auto-remediation.

## Architecture

```
scripts/mqtt-ops-smoke.sh (POSIX sh, set -eu)
  1. validate-env.sh              → NEO4J_*, POSTGRES_*
  2. docker compose config        → MQTT_BROKER_URL present
  3. GET /api/mqtt/status         → connected=false + stale (absent branch)
  4. docker compose up -d mqtt-subscriber
  5. poll /api/mqtt/status        → connected=true + fresh
  6. --with-fixture: publish + poll /api/mqtt/readings
  7. trap EXIT → print rollback block (docker compose stop)
```

Reuses `scripts/validate-env.sh`; `docker compose config` is the broker-URL probe. Auth assumed (operator holds `MQTT_READ` cookie).

## Architecture Decisions

| ID | Choice | Rejected | Rationale |
|----|--------|----------|-----------|
| D1 | Single POSIX `sh`, `set -eu`, fail-loud | Python wrapper; bash-only | Mirrors existing scripts; POSIX portability. |
| D2 | `MQTT_BROKER_URL` via `docker compose config` | Read `.env` directly | Matches deployed resolution (incl. `${VAR}`); `.env.example` lacks the key. |
| D3 | `up -d` + `stop` only | `restart`, `down`, `--force-recreate` | Spec forbids `down`/`-v`/`rm`; stop preserves container for retry. |
| D4 | Bounded activation poll (default 60s) | Single GET after `up -d` | Subscriber needs 5–30s; loop is bounded for fail-fast. |
| D5 | Auth assumed; 401 → fail-loud | Script-driven cookie jar | Cookie lifecycle is operator-scoped. |
| D6 | Runbook appended to `docs/mqtt-monitoring.md` | New `docs/mqtt-operational-smoke-runbook.md` | Gap and closure live in the same doc operators open during incident. |
| D7 | Offline grep test for forbidden tokens | AST-level bash parse | Static invariant; grep is the simplest proof. |

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `scripts/mqtt-ops-smoke.sh` | Create | POSIX `sh` smoke runner. |
| `scripts/test-mqtt-ops-smoke.sh` | Create | Offline grep test (forbidden + positive tokens). |
| `docs/mqtt-monitoring.md` | Modify | Append `## Operational smoke (#387)`; remove `#387` from `## Known gaps`. |

## Script Flow (pseudo-Bash)

```sh
#!/bin/sh
set -eu
cd "$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"

WITH_FIXURE=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --with-fixture) WITH_FIXURE=1 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac; shift
done

# 1. Credentials contract
sh scripts/validate-env.sh

# 2. MQTT_BROKER_URL present in resolved compose config
docker compose config --format json \
    | grep -q '"MQTT_BROKER_URL"' \
    || { printf 'ERROR: missing env: MQTT_BROKER_URL\n' >&2; exit 1; }

# 3. Absent branch (soft check; skip if already active)
status=$(curl -fsS -b "$COOKIE_JAR" http://localhost:8000/api/mqtt/status) || {
    printf 'ERROR: auth required: GET /api/mqtt/status returned non-zero\n' >&2; exit 1; }
if ! printf '%s' "$status" | grep -q '"connected":[[:space:]]*true'; then
    # Assert last_message_at older than stale threshold (or null)
    case "$status" in
        *'"last_message_at":null'*) ;;
        *) last=$(printf '%s' "$status" \
                | sed -n 's/.*"last_message_at":"\([^"]*\)".*/\1/p')
           age=$(( $(date +%s) - $(date -u -d "$last" +%s 2>/dev/null || echo 0) ))
           [ "$age" -ge "${MQTT_SUBSCRIBER_STALE_HEARTBEAT_SECONDS:-90}" ] \
               || { printf 'ERROR: last_message_at fresh but connected=false\n' >&2; exit 1; } ;;
    esac
fi

# 4-5. Activate + poll
docker compose up -d mqtt-subscriber
deadline=$(( $(date +%s) + ${MQTT_SMOKE_ACTIVATION_TIMEOUT_SECONDS:-60} ))
while [ "$(date +%s)" -lt "$deadline" ]; do
    s=$(curl -fsS -b "$COOKIE_JAR" http://localhost:8000/api/mqtt/status) || true
    printf '%s' "$s" | grep -q '"connected":[[:space:]]*true' && break
    sleep 2
done
[ "$(date +%s)" -lt "$deadline" ] \
    || { printf 'ERROR: activation timeout; last=%s\n' "$s" >&2; exit 1; }

# 6. Optional fixture
[ "$WITH_FIXURE" -eq 1 ] && {
    TAG="smoke-$(date +%s)-$$"
    docker compose exec -T mqtt-subscriber \
        mosquitto_pub -h "${MQTT_BROKER_HOST:-broker}" -t "smoke/$TAG" -m "$TAG"
    # poll /api/mqtt/readings for TAG (bounded)
}

# 7. Rollback printout — trap guarantees it runs on every exit
print_rollback() {
    cat <<'RB'
Rollback:
  docker compose stop mqtt-subscriber    # never use 'down' or '-v'
RB
}
trap 'print_rollback' EXIT
```

## Interfaces / Contracts

Read-only `/api/mqtt/status` (unchanged): `{ "connected": bool, "last_message_at": ISO8601|null, "broker_url": "...", "subscriber_state": "RUNNING" }`. Absent = `connected=false` AND `last_message_at` older than `MQTT_SUBSCRIBER_STALE_HEARTBEAT_SECONDS` (default 90). Active = `connected=true` AND fresh.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Offline | Forbidden tokens absent (`-v`, `compose down`, `compose rm`, `volume rm`) | `test-mqtt-ops-smoke.sh` greps source; fails on match. |
| Offline | Required tokens present (`up -d mqtt-subscriber`, `stop mqtt-subscriber`) | Positive grep assertions. |
| Offline | `--help` exits 0; documents `--with-fixture` | Spawn script with flag; assert exit + usage. |
| Manual | Absent → active on real Compose | Run against stopped subscriber (expect fail), `up -d`, re-run (expect 0). |
| Manual | `--with-fixture` publishes + sees tag in `/api/mqtt/readings` | Run with flag; expect 0 + tag echoed. |
| CI | Out of scope per proposal | Future change. |

## Threat Matrix

Applicable (shell + subprocess + Docker Compose). N/A rows require no task.

| Boundary | Case | App | Response + RED test |
|---|---|:---:|---|
| Compose flags | `down -v`, `down`, `rm`, `volume rm` | Y | `up -d` + `stop` only; `trap` rollback; grep fails on forbidden tokens. RED: inject each token; assert non-zero. |
| Broker URL | `MQTT_BROKER_URL` unset/empty | Y | `docker compose config --format json` is authoritative; never `eval`. RED: stub config to omit key; assert `missing env`. |
| Partial state | Activated but poll never reaches active | Y | Bounded poll 60s; on timeout prints status + rollback. RED: `up -d` then block port; assert non-zero. |
| Env spoofing | Shell exports one value; compose resolves another | Y | Compare env vs `docker compose config` parsed value; mismatch → fail-loud. RED: stub mismatch; assert non-zero. |
| Auth failure | `MQTT_READ` cookie absent → 401 | Y | `curl -fsS` non-zero on HTTP error; prints auth-required + rollback. RED: stub curl → 22; assert non-zero. |
| Container exec | `docker compose exec -T` in non-running container | Y | Poll BEFORE fixture; `set -eu` propagates failure. RED: stop subscriber + `--with-fixture`; assert non-zero before exec. |
| Git selection | no `git -C` | N/A | — | N/A |
| Commit/push | no VCS automation | N/A | — | N/A |
| PR cmds | no `gh` calls | N/A | — | N/A |
| Doc-like paths | only `scripts/*.sh` | N/A | — | N/A |

## Migration / Rollout

No migration. The script is the kill-switch — opt-in; nothing fires automatically. To revert: delete the two scripts and the runbook section.

## Risks & Mitigations

- **Non-default stack** → runbook documents prerequisites: stack up on `:8000`, authenticated session, `MQTT_READ` permission.
- **False negative when already active** → absent branch is soft: if `connected=true`, skip absent assertion and continue.
- **`${VAR}` placeholders flagged by compose config** → probe greps JSON keys, not values; unresolved placeholders still match.
- **Offline test satisfied by a comment** → forbidden tokens checked as whole words (`grep -w`); comments containing the token still fail.

## Open Questions

None.