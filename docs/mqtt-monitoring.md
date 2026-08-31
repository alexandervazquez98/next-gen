# MQTT monitoring integration

MQTT monitoring is now integrated as a backend/runtime pipeline: raw MQTT readings remain inspectable as non-KPI telemetry, and only explicitly approved mappings can promote MQTT samples into monitoring metrics and events.

## Current state

| Area | Status | Notes |
| --- | --- | --- |
| Raw MQTT visibility | Available | `/api/mqtt/devices`, `/api/mqtt/devices/{device_id}/metrics`, and `/api/mqtt/readings` return `RAW_MQTT_NON_KPI` data with `kpi_eligible=false`. |
| Permissions | Available | `MQTT_READ` protects read/status APIs; `MQTT_MAPPING_MANAGE` protects mapping and threshold mutations. |
| Mapping lifecycle | Available | Mappings start as `DRAFT`; only `APPROVED` mappings can bridge samples into monitoring. `REVOKED` mappings are fail-closed. |
| Thresholds | Available | Manual thresholds are stored per mapping and included in event evaluation payloads. |
| KPI/event bridge | Available | Approved numeric MQTT samples write Timescale metric values and reuse the existing event writer path. |
| Runtime subscriber | Available | A dedicated `mqtt-subscriber` Compose service runs `python -m scripts.mqtt_subscriber`. |
| Frontend UI | Not implemented | Operators currently use the backend API. |
| Auto-mapping | Not implemented | Mapping is manual by design; no automatic matching is performed. |

## Runtime topology

```text
MQTT broker
  │
  ▼
mqtt-subscriber container
  │ parses topics/payloads
  ▼
raw Device/Metric graph records                 ──► /api/mqtt/readings
  │
  ├─ no approved mapping ──► stop: RAW_MQTT_NON_KPI only
  │
  └─ approved mapping
       │
       ├─ idempotent receipt guard
       ├─ Timescale metric_values write
       └─ existing event_writer threshold path
```

The API container does **not** own the subscriber by default. The dedicated subscriber process is the normal runtime owner. The API process only starts an embedded subscriber when `ENABLE_MQTT_SUBSCRIBER=true` is explicitly set.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MQTT_BROKER_URL` | required in Compose subscriber service | Broker connection URL. Set this explicitly for deployment. |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | empty | Optional broker credentials. |
| `MQTT_CLIENT_ID` | `nexgen_subscriber` in Compose | Subscriber client identity. |
| `MQTT_MAPPING_BRIDGE_ENABLED` | `true` | Enables approved-mapping bridge writes after raw persistence. Set `false` to keep raw ingestion only. |
| `MQTT_SUBSCRIBER_STALE_HEARTBEAT_SECONDS` | `90` | Preferred stale-heartbeat threshold for `/api/mqtt/status`. |
| `MQTT_MAPPING_BRIDGE_MISSED_HEARTBEAT_SECONDS` | compatibility alias | Legacy alias still accepted when the preferred variable is absent. |
| `ENABLE_MQTT_SUBSCRIBER` | `false` for API process, `true` in subscriber service | Prevents accidental duplicate subscriber ownership. |

## API quick path

1. Read raw telemetry:
   - `GET /api/mqtt/devices`
   - `GET /api/mqtt/devices/{device_id}/metrics`
   - `GET /api/mqtt/readings`
2. Create a mapping as draft:
   - `POST /api/mqtt/mappings`
3. Approve the mapping:
   - `POST /api/mqtt/mappings/{mapping_id}/approve`
4. Configure thresholds:
   - `PUT /api/mqtt/mappings/{mapping_id}/thresholds`
5. Check runtime status:
   - `GET /api/mqtt/status`

## Safety rules

- Raw MQTT data is never KPI-eligible by default.
- `DRAFT`, `REVOKED`, unmapped, ambiguous, or non-numeric readings do not write Timescale samples or events.
- Duplicate MQTT payloads are deduplicated by deterministic receipt keys.
- Partial failures retry only the missing step: event retries do not rewrite the metric sample.
- Event writer calls use the existing advisory-lock path to avoid duplicate active events.
- Status-store failures are best-effort and must not stop raw ingestion.

## Deployment checklist

- [ ] Apply Neo4j migrations `003_mqtt_monitoring_mapping.cypher` and `004_mqtt_metric_result_idempotency.cypher`.
- [ ] Ensure PostgreSQL tables for runtime status and sample receipts can be created by the backend role.
- [ ] Set `MQTT_BROKER_URL` explicitly for `mqtt-subscriber`.
- [ ] Start the dedicated subscriber service: `docker compose up -d mqtt-subscriber`.
- [ ] Confirm `/api/mqtt/status` becomes fresh/non-stale after the subscriber connects.
- [ ] Confirm raw readings appear before approving any mapping.
- [ ] Approve one test mapping and verify only that mapping writes monitoring data.

## Operational smoke (#387)

A POSIX `sh` runner closes the #387 follow-up: it proves the subscriber
absent -> active transition is observable through `/api/mqtt/status`
without mutating persistent state. Run it on any host that can reach the
Compose project.

### Prerequisites

- Full stack (`api`, `postgres`, `neo4j`, `mqtt-subscriber`) running on
  `localhost:8000` (or override via `MQTT_SMOKE_STATUS_URL` /
  `MQTT_SMOKE_READINGS_URL`).
- `docker compose v2.x` on PATH.
- An authenticated session with the `MQTT_READ` permission; export
  `COOKIE_JAR=/path/to/cookies.txt`. The script defaults to
  `$HOME/.mqtt_cookie` when `COOKIE_JAR` is unset.
- `.env` populated per `scripts/validate-env.sh`; the validator is
  re-invoked before any status assertion, so missing `NEO4J_*` or
  `POSTGRES_*` aborts the smoke before Docker actions.
- `MQTT_BROKER_URL` set in the resolved Compose config (probed via
  `docker compose config`).

### Smoke flow

```sh
# Default mode: prove the absent branch, activate, prove the active branch.
sh scripts/mqtt-ops-smoke.sh

# End-to-end fixture: publish a tagged MQTT message and confirm it
# appears in /api/mqtt/readings (adds ~30s to the run).
sh scripts/mqtt-ops-smoke.sh --with-fixture
```

What the script does, in order:

1. Validates the credential contract via `scripts/validate-env.sh`.
   Exits non-zero (and never reaches Docker) when any required env var
   is missing or matches a `.env.example` placeholder.
2. Probes `MQTT_BROKER_URL` presence in the resolved `docker compose
   config` JSON output; exits non-zero with `missing env:
   MQTT_BROKER_URL` when unset.
3. Reads `/api/mqtt/status` over an authenticated session. If the
   subscriber reports `connected=false`, asserts `last_message_at` is
   null OR older than `MQTT_SUBSCRIBER_STALE_HEARTBEAT_SECONDS`
   (default 90). If `connected=true`, skips the absent assertion
   (Scenario: subscriber already active at start).
4. Brings the subscriber up via the `up -d` form of compose (NEVER the
   destructive verb, NEVER the volume flag).
5. Bounded-polls `/api/mqtt/status` until `connected=true` (default
   timeout: `MQTT_SMOKE_ACTIVATION_TIMEOUT_SECONDS` = 60s). Exits
   non-zero on timeout with the last payload captured.
6. With `--with-fixture`, publishes a uniquely tagged MQTT message via
   `mosquitto_pub` inside the `mqtt-subscriber` container and bounded-
   polls `/api/mqtt/readings` until the tag appears (default timeout:
   `MQTT_SMOKE_FIXTURE_TIMEOUT_SECONDS` = 30s).
7. Prints a rollback block on every exit path (success and failure)
   via a `trap ... EXIT` registration.

### Rollback

The script is non-destructive: it only ever calls the `up -d` form of
compose and the `stop` form. To revert after a successful run:

```sh
docker compose stop mqtt-subscriber
```

Never use `docker compose down`, `-v`, `rm`, or any volume-removing
verb to roll back this smoke. The offline test
(`sh scripts/test-mqtt-ops-smoke.sh`) forbids those tokens as a
static invariant; do not weaken the test.

### Configuration knobs

| Variable | Default | Purpose |
| --- | --- | --- |
| `COOKIE_JAR` | `$HOME/.mqtt_cookie` when readable | Holds an authenticated session with `MQTT_READ`. |
| `MQTT_SUBSCRIBER_STALE_HEARTBEAT_SECONDS` | 90 | Threshold that defines a "stale" `last_message_at` when `connected=false`. |
| `MQTT_SMOKE_ACTIVATION_TIMEOUT_SECONDS` | 60 | Max wait for the subscriber to report `connected=true` after the `up -d` invocation. |
| `MQTT_SMOKE_FIXTURE_TIMEOUT_SECONDS` | 30 | Max wait for the fixture tag to appear in `/api/mqtt/readings`. |
| `MQTT_SMOKE_STATUS_URL` | `http://localhost:8000/api/mqtt/status` | Override the status endpoint. |
| `MQTT_SMOKE_READINGS_URL` | `http://localhost:8000/api/mqtt/readings?limit=50` | Override the readings endpoint. |
| `MQTT_BROKER_HOST` | `broker` | Hostname for `mosquitto_pub` during fixture publishing. |

### Static safety invariant

`sh scripts/test-mqtt-ops-smoke.sh` proves the smoke runner never
invokes destructive Docker Compose verbs (down, `-v`, rm, volume
removal) and that all required tokens are present. Run it before
merging changes to `scripts/mqtt-ops-smoke.sh`.

## Known gaps and follow-up work

- Frontend UX for mapping review/approval is tracked in [#385](https://github.com/alexandervazquez98/next-gen/issues/385).
- Mapping/threshold audit trail and operator-facing audit views are tracked in [#386](https://github.com/alexandervazquez98/next-gen/issues/386).
