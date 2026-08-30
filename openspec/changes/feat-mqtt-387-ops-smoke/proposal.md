# Proposal: MQTT Monitoring Operational Smoke (#387)

## Intent

`docs/mqtt-monitoring.md` lists `#387 — Production smoke automation for absent-vs-active subscriber status` as a known gap. Today operators reconstruct prose steps to prove `mqtt-subscriber` publishes heartbeats into `/api/mqtt/status`. Make it a safe, repeatable script.

## Scope

### In Scope
- `scripts/mqtt-ops-smoke.sh` — POSIX `sh` smoke: validates `MQTT_BROKER_URL` via `docker compose config` and `NEO4J_*` / `POSTGRES_*` via `scripts/validate-env.sh`; asserts `mqtt-subscriber` absent → `/api/mqtt/status` shows `connected=false` and stale `last_message_at` (threshold `MQTT_SUBSCRIBER_STALE_HEARTBEAT_SECONDS`, default 90s); runs `docker compose up -d mqtt-subscriber` (no `-v`, no `down`); polls status until `connected=true`; `--with-fixture` publishes a test message and confirms `/api/mqtt/readings` visibility; prints rollback on exit.
- `scripts/test-mqtt-ops-smoke.sh` — offline test; greps forbid `-v` and `compose down`.
- New runbook section in `docs/mqtt-monitoring.md` (or new `docs/mqtt-operational-smoke-runbook.md`).
- New OpenSpec capability `mqtt-operational-smoke`.

### Out of Scope
- Adding `MQTT_BROKER_URL` to `.env.example` (separate concern).
- Auto-remediation on smoke failure — script reports only.
- Wiring smoke into GitHub Actions CD lane.
- Changes to `/api/mqtt/status` contract or subscriber behavior.

## Capabilities

### New Capabilities
- `mqtt-operational-smoke`: Operator smoke proving `mqtt-subscriber` heartbeat absent-vs-active through `/api/mqtt/status`.

### Modified Capabilities
- None.

## Approach

Mirror `scripts/validate-env.sh` and `scripts/ci-cd-check-runner-contract.sh`: POSIX `sh`, `set -eu`, header comment, fail-loud. Reuse `validate-env.sh` for credentials; add a Compose-config probe for `MQTT_BROKER_URL`. Only `docker compose up -d <service>` and `docker compose stop <service>`. Auth via existing `MQTT_READ` cookie. Spec encodes smoke steps as Given/When/Then in `specs/mqtt-operational-smoke/spec.md`.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `scripts/mqtt-ops-smoke.sh` | New | POSIX smoke runner |
| `scripts/test-mqtt-ops-smoke.sh` | New | Offline test (forbids `-v`, `down`) |
| `docs/mqtt-monitoring.md` | Modified | Add Operational smoke section |
| `specs/mqtt-operational-smoke/spec.md` | New | Delta spec |

## Risks

| Risk | Mitigation |
|---|---|
| Smoke runs destructive Compose path | Only `up -d` / `stop`; test greps for `-v` and `compose down` |
| `.env.example` lacks `MQTT_BROKER_URL` | Probe via `docker compose config` |
| Stale normalization hides disconnect | Assert `connected=false` AND stale `last_message_at` before start |
| `/api/mqtt/status` auth → 401 | Document auth in runbook; 401 = fail-loud |

## Rollback Plan

Script only runs `up -d` and `stop` — no state mutation. To revert: delete the two scripts, the runbook section, and the spec file. If aborted mid-run, the rollback printout runs `docker compose stop mqtt-subscriber`; volumes are untouched.

## Dependencies

- `scripts/validate-env.sh`; `/api/mqtt/status` from `backend/routers/mqtt.py` (unchanged); `docker compose` v2.

## Success Criteria

- [ ] `sh scripts/mqtt-ops-smoke.sh` exits non-zero when subscriber absent, zero when active.
- [ ] Smoke never invokes `docker compose down` or `-v` (test enforces).
- [ ] Runbook section documents absent-vs-active flow + rollback.
- [ ] Capability `mqtt-operational-smoke` archives into `openspec/specs/mqtt-operational-smoke/spec.md`.
