# Design: MQTT readings monitoring integration

## Decision

Implement the MVP as a backend/API-first bridge from raw MQTT `Device`/`Metric` telemetry into the existing CI/`MetricDef`, Timescale `metric_values`, and event evaluation path. The bridge is fail-closed: MQTT data is always stored and queryable as raw telemetry, but it can reach KPI history or events only when an explicit operator-owned mapping rule is in `APPROVED` state.

There is no first-slice UI. Operators interact through API endpoints and can verify ingestion, subscriber health, mappings, thresholds, bridge outcomes, and audit records from backend responses.

## Current architecture anchors

| Area | Existing anchor | Design implication |
|------|-----------------|--------------------|
| Raw MQTT ingestion | `backend/services/mqtt/subscriber.py` persists parsed readings through `DeviceMetricRepo` into `(:Device)-[:HAS_METRIC]->(:Metric)` | Keep raw persistence unchanged; add a bridge after raw persistence, not inside parsers. |
| Raw MQTT storage | `backend/repositories/device_metric_repo.py` supports device upsert, metric upsert, device lookup, and metric listing | Extend with list/status APIs; do not overload raw `Metric` nodes with KPI semantics. |
| Monitoring model | `(:CI)-[:HAS_METRIC]->(:MetricDef)` powers existing collection/event queries | Mapping rules resolve MQTT source identifiers to this model explicitly. |
| KPI history | `backend/models/timescale_models.py::MetricValue` writes `metric_values(time, node_id, metric_id, value)` | Mapped MQTT samples must be written using target `ci_id` as `node_id` and target `metric_def_id` as `metric_id`. |
| Event evaluation | `backend/polling/event_writer.py::build_event_rows` evaluates thresholds from envelope `metadata` and `batch_update_events` updates Neo4j events | Reuse normalized envelope semantics rather than creating a separate MQTT event model. |
| Runtime | `backend/main.py` starts background SNMP collector; compose has no MQTT subscriber service | Add explicit MQTT subscriber runtime mode and health/status reporting. |
| Audit | `backend/services/audit_service.py` persists critical changes with actor, target, outcome, context | Mapping and threshold lifecycle changes must use this service. |

Note: CodeGraph was requested by workspace guidance for structural analysis, but no CodeGraph tool or shell execution was available in this delegated context. I confirmed `.codegraph/README.md` was absent and used targeted file reads/greps as fallback.

## Scope boundaries

### In scope

- Raw MQTT read/status API.
- Operator-managed mapping rules from MQTT source to CI/MetricDef.
- Mapping lifecycle: `DRAFT`, `APPROVED`, `REVOKED`.
- Hard gate before Timescale/event writes.
- Manual thresholds for mapped MQTT metrics.
- Explicit subscriber runtime wiring and API health/status.
- Audit records for mapping and threshold changes.

### Out of scope

- Frontend/UI mapping workflow.
- Auto-mapping, suggestions, or inferred approvals.
- Historical backfill from raw MQTT to Timescale.
- Redesigning the existing monitoring/event domain.
- Tenant-wide policy engine for mapping approval.

## Proposed modules and boundaries

### New modules

| Module | Responsibility | Boundary rule |
|--------|----------------|---------------|
| `backend/repositories/mqtt_mapping_repo.py` | Persist and query mapping rules and mapping audit snapshots in Neo4j | Repository only; no event/Timescale writes. |
| `backend/services/mqtt_mapping_service.py` | Validate lifecycle operations, enforce authorization-facing invariants, assemble API responses | Owns mapping state transitions and audit calls. |
| `backend/services/mqtt_bridge_service.py` | Resolve raw readings to approved mappings and emit normalized monitoring envelopes | Only service allowed to transform MQTT raw telemetry into KPI candidates. |
| `backend/services/mqtt_threshold_service.py` | Read/update manual threshold metadata for mapped MQTT rules | Must require an approved mapping before threshold updates affect events. |
| `backend/repositories/mqtt_runtime_status_repo.py` | Persist subscriber heartbeat, connection state, bridge counters, and last outcome in shared storage visible to both subscriber and API processes | Required when using a dedicated subscriber process; no in-memory-only health for cross-process status. |
| `backend/services/mqtt_runtime_status.py` | Read/write subscriber running/connected/error state and bridge counters through the shared status repository | API status reads persisted heartbeat/counters; subscriber updates them on connect/message/error/bridge outcome. |
| `backend/routers/mqtt.py` | API-first raw readings, status, mappings, thresholds, bridge diagnostics | No UI concerns; mounted under `/api/mqtt`. |
| `backend/scripts/mqtt_subscriber.py` or equivalent module entrypoint | Dedicated process entrypoint for compose/runtime | Starts `mqtt_subscriber_loop()` explicitly, no import side effects. |

### Existing modules to extend

| Module | Change |
|--------|--------|
| `backend/services/mqtt/subscriber.py` | After raw `DeviceMetricRepo` persistence succeeds, call `mqtt_bridge_service.process_reading(reading)`. ACK behavior remains based on raw persistence; bridge failures are recorded as observable outcomes and must not poison raw ingestion unless a database transaction failure makes state unknowable. |
| `backend/repositories/device_metric_repo.py` | Add read methods for raw device/metric listing, latest metric detail, and mapping-status joins if needed by API. |
| `backend/main.py` | Include `routers.mqtt` and expose status endpoint. Do not silently start the subscriber unless an explicit env flag is selected. |
| `docker-compose.yml` | Add an explicit `mqtt-subscriber` service or explicit backend env flag. Preferred MVP: separate service for clearer liveness and failure ownership. |
| `backend/models/user.py` | Add `MQTT_MAPPING_MANAGE` for mapping/threshold mutations and `MQTT_READ` for raw/status read APIs, or map them centrally to existing permissions only if the enum cannot be extended in the same slice. | The design decision is explicit: do not use broad `CI_EDIT` directly at route call sites. All `/api/mqtt/*` authorization goes through `mqtt_mapping_service.require_mqtt_permission(kind)`. |

## Data model and migrations

### Neo4j mapping model

Add migration `backend/migrations/003_mqtt_monitoring_mapping.cypher`.

```cypher
(:MqttMetricMapping {
  id: string,                         // stable UUID
  source_device_id: string,           // Device.id
  source_metric_id: string,           // Metric.id, e.g. device/metric_name
  source_metric_name: string,
  target_ci_id: string,               // CI.id
  target_metric_def_id: string,       // MetricDef.id
  status: 'DRAFT'|'APPROVED'|'REVOKED',
  warning: float?,
  critical: float?,
  operator: string?,                  // >=, <=, ==, !=
  created_by: string,
  created_at: datetime,
  updated_by: string?,
  updated_at: datetime?,
  approved_by: string?,
  approved_at: datetime?,
  revoked_by: string?,
  revoked_at: datetime?,
  version: integer
})

(:Device)-[:HAS_MQTT_MAPPING]->(:MqttMetricMapping)
(:Metric)-[:HAS_MQTT_MAPPING]->(:MqttMetricMapping)
(:MqttMetricMapping)-[:TARGETS_CI]->(:CI)
(:MqttMetricMapping)-[:TARGETS_METRIC_DEF]->(:MetricDef)
```

Constraints/indexes:

```cypher
CREATE CONSTRAINT mqtt_metric_mapping_id_unique IF NOT EXISTS
FOR (m:MqttMetricMapping) REQUIRE m.id IS UNIQUE;

CREATE INDEX mqtt_metric_mapping_source IF NOT EXISTS
FOR (m:MqttMetricMapping) ON (m.source_device_id, m.source_metric_id, m.status);

CREATE INDEX mqtt_metric_mapping_target IF NOT EXISTS
FOR (m:MqttMetricMapping) ON (m.target_ci_id, m.target_metric_def_id, m.status);
```

Rule: at most one `APPROVED` mapping may exist for the same `(source_device_id, source_metric_id)` at a time. Neo4j cannot express this partial uniqueness portably in current migration style, so `MqttMappingRepo.approve_mapping()` must enforce it transactionally by revoking/rejecting conflicting approved mappings before approval. Prefer rejection in MVP to avoid surprising operators.

### Audit persistence

Use existing Postgres `AuditEvent` via `services.audit_service` for every mapping/threshold mutation:

- `MQTT_MAPPING_CREATE`
- `MQTT_MAPPING_APPROVE`
- `MQTT_MAPPING_UPDATE`
- `MQTT_MAPPING_REVOKE`
- `MQTT_MAPPING_THRESHOLD_UPDATE`

Audit context must include source device/metric IDs, target CI/MetricDef IDs, previous state, next state, and mapping version. Do not store MQTT payloads or secrets in audit context.

### Timescale model and mandatory idempotency

No `metric_values` schema change is required for MVP. Mapped MQTT writes use the existing `MetricValue` shape:

```text
MetricValue.time      = reading.timestamp
MetricValue.node_id   = mapping.target_ci_id
MetricValue.metric_id = mapping.target_metric_def_id
MetricValue.value     = numeric reading value
```

MQTT KPI bridge writes MUST be idempotent. MQTT redelivery, subscriber restart, and retry after partial failure are expected paths, not edge cases. Add a dedicated Postgres receipt table/model, for example `mqtt_metric_sample_receipts`, instead of treating idempotency as optional:

```text
idempotency_key text primary key
mapping_id text not null
source_device_id text not null
source_metric_id text not null
observed_at timestamptz not null
value_hash text not null
timescale_written_at timestamptz?
event_written_at timestamptz?
status text not null              -- PENDING_EVENT | COMPLETE | FAILED
last_error text?
created_at timestamptz not null
updated_at timestamptz not null
```

Deterministic key:

```text
mqtt:{mapping_id}:{source_metric_id}:{timestamp}:{value_hash}
```

Bridge algorithm:

1. Create/read receipt by idempotency key before writing KPI data.
2. If receipt is `COMPLETE`, skip duplicate work and report `SKIPPED_DUPLICATE`.
3. If receipt has `timescale_written_at` but no `event_written_at`, retry only the event writer path.
4. If no Timescale write exists, write `MetricValue` first, mark `timescale_written_at`, then call event writer and mark `event_written_at`/`COMPLETE`.
5. Do not create events without a successful sample write.

Do not add raw MQTT samples to `metric_values` without an approved mapping.

## API contract summary

Mount a new router under `/api/mqtt`.

### Raw telemetry and status

| Method/path | Purpose | Notes |
|-------------|---------|-------|
| `GET /api/mqtt/status` | Subscriber and bridge health | Requires `MQTT_READ`; reads shared persisted heartbeat/counters; returns running/connected/subscribed patterns/last message/last bridge outcome/counters/reason code. |
| `GET /api/mqtt/devices` | List raw MQTT devices | Requires `MQTT_READ`; include `kpi_eligible: false` by default and mapping counts. |
| `GET /api/mqtt/devices/{device_id}/metrics` | List latest raw metrics for a device | Requires `MQTT_READ`; include mapping status per metric: `UNMAPPED`, `DRAFT`, `APPROVED`, `REVOKED`. |
| `GET /api/mqtt/readings` | Query latest raw readings snapshot, not full raw history | Requires `MQTT_READ`; operator/internal endpoint; explicitly labels samples as raw/non-KPI. MVP uses latest-value storage unless a later slice adds raw history retention. |

Example raw metric response:

```json
{
  "device_id": "rtu-01",
  "metric_id": "rtu-01/temperature",
  "name": "temperature",
  "last_value": 42.3,
  "unit": "C",
  "last_ts": "2026-07-06T12:00:00Z",
  "classification": "RAW_MQTT_NON_KPI",
  "kpi_eligible": false,
  "mapping_status": "UNMAPPED"
}
```

### Mapping lifecycle

| Method/path | Purpose |
|-------------|---------|
| `GET /api/mqtt/mappings` | Requires `MQTT_READ`; list mappings by source, target, status. |
| `POST /api/mqtt/mappings` | Requires `MQTT_MAPPING_MANAGE`; create a `DRAFT` mapping from source Device/Metric to target CI/MetricDef. |
| `PUT /api/mqtt/mappings/{mapping_id}` | Requires `MQTT_MAPPING_MANAGE`; update draft mapping fields or thresholds. Reject target/source changes for `APPROVED` mappings unless first revoked. |
| `POST /api/mqtt/mappings/{mapping_id}/approve` | Requires `MQTT_MAPPING_MANAGE`; approve mapping after validating source and target exist and no conflicting approved mapping exists. |
| `POST /api/mqtt/mappings/{mapping_id}/revoke` | Requires `MQTT_MAPPING_MANAGE`; revoke mapping; future samples are blocked from KPI/event paths. |
| `GET /api/mqtt/mappings/{mapping_id}/audit` | Requires `MQTT_READ`; return audit records for mapping lifecycle. |

Create mapping request:

```json
{
  "source_device_id": "rtu-01",
  "source_metric_id": "rtu-01/temperature",
  "target_ci_id": "ci-router-01",
  "target_metric_def_id": "temperature_c",
  "thresholds": {
    "operator": ">=",
    "warning": 70,
    "critical": 85
  }
}
```

Approve response:

```json
{
  "id": "map-uuid",
  "status": "APPROVED",
  "approved_by": "operator@example.com",
  "approved_at": "2026-07-06T12:10:00Z",
  "kpi_gate": "OPEN_FOR_APPROVED_MAPPING_ONLY"
}
```

### Threshold management

| Method/path | Purpose |
|-------------|---------|
| `GET /api/mqtt/mappings/{mapping_id}/thresholds` | Requires `MQTT_READ`; return thresholds for a mapped MQTT metric. |
| `PUT /api/mqtt/mappings/{mapping_id}/thresholds` | Requires `MQTT_MAPPING_MANAGE`; update manual thresholds. Requires mapping to exist; event application only occurs for `APPROVED` mappings. |

Thresholds are stored on `MqttMetricMapping` for MVP. The bridge copies them into event envelope `metadata` so `polling.event_writer.build_event_rows()` evaluates them the same way as other metric samples.

## Bridge flow

### Happy path: approved mapping

```text
MQTT message
  -> TopicRouter parser
  -> Reading(device_id, metrics[], timestamp, source_topic)
  -> DeviceMetricRepo.upsert_device/upsert_metric       [raw store]
  -> MqttBridgeService.process_reading(reading)
      -> for each metric:
          source_metric_id = f"{device_id}/{metric.name}"
          mapping = MqttMappingRepo.get_approved(source_device_id, source_metric_id)
          if none: record SKIPPED_UNMAPPED and continue
          validate target CI and MetricDef still exist
          build monitoring envelope and deterministic idempotency key
          create/read mqtt_metric_sample_receipt
          persist MetricValue in Timescale only if receipt is not already written
          call polling.event_writer.batch_update_events(..., lock_db=timescale_db) only after sample write
          mark receipt COMPLETE and record BRIDGED success outcome
  -> ACK original MQTT message once raw persistence succeeds
```

Envelope shape for event writer:

```json
{
  "idempotency_key": "mqtt:map-uuid:rtu-01/temperature:2026-07-06T12:00:00Z:hash",
  "protocol": "MQTT",
  "ci_id": "ci-router-01",
  "metric_id": "temperature_c",
  "observed_at": "2026-07-06T12:00:00Z",
  "value": 42.3,
  "status": "OK",
  "metadata": {
    "name": "temperature",
    "operator": ">=",
    "warning": 70,
    "critical": 85,
    "source_protocol": "MQTT",
    "mqtt_mapping_id": "map-uuid",
    "mqtt_source_device_id": "rtu-01",
    "mqtt_source_metric_id": "rtu-01/temperature"
  }
}
```

### Fail-closed paths

| Condition | Required behavior |
|-----------|-------------------|
| No mapping | Do not write Timescale; do not call event writer; record `SKIPPED_UNMAPPED`. |
| Mapping is `DRAFT` | Do not write Timescale/events; record `SKIPPED_UNAPPROVED`. |
| Mapping is `REVOKED` | Do not write Timescale/events; record `SKIPPED_REVOKED`. |
| Source has multiple approved mappings | Do not choose one; record `BLOCKED_AMBIGUOUS_MAPPING`; alert/status should be degraded. |
| Target CI/MetricDef missing | Do not write; record `BLOCKED_TARGET_NOT_FOUND`; mapping status remains but health exposes drift. |
| Non-numeric value for thresholded metric | Raw persistence remains; KPI bridge skips with `SKIPPED_NON_NUMERIC` unless later metric type support is explicitly designed. |
| Timescale write fails | Record bridge failure and expose degraded status; do not create event without the sample write. |
| Event writer fails after Timescale insert | Mark receipt `PENDING_EVENT`, expose degraded status, and retry event writer only. Do not duplicate Timescale samples on retry. |

## Runtime wiring

Preferred MVP wiring is a dedicated container/process:

```yaml
mqtt-subscriber:
  build: ./backend
  command: ["python", "-m", "scripts.mqtt_subscriber"]
  depends_on:
    neo4j:
      condition: service_healthy
    postgres:
      condition: service_healthy
  environment:
    - MQTT_BROKER_URL=${MQTT_BROKER_URL:-mqtt://mqtt:1883}
    - MQTT_WILDCARD_TOPIC=${MQTT_WILDCARD_TOPIC:-rtu/+/+/telemetry}
    - MQTT_MAPPING_BRIDGE_ENABLED=${MQTT_MAPPING_BRIDGE_ENABLED:-true}
```

Because the preferred MVP uses a separate subscriber process, `GET /api/mqtt/status` MUST read subscriber state from shared persistence, not process-local memory. The subscriber entrypoint updates heartbeat/connection/last-message/last-error/bridge counters through `mqtt_runtime_status_repo`; the API marks subscriber `running=false` when the heartbeat is absent or stale beyond a configured timeout.

`GET /api/mqtt/status` must prove wiring by returning at least:

```json
{
  "subscriber": {
    "configured": true,
    "running": true,
    "connected": true,
    "client_id": "rtu-telemetry-subscriber",
    "subscribed_patterns": ["rtu/+/+/telemetry"],
    "last_message_at": "2026-07-06T12:00:00Z",
    "last_error": null,
    "reason_code": "OK"
  },
  "bridge": {
    "enabled": true,
    "last_outcome": "SKIPPED_UNMAPPED",
    "mapped_writes_total": 10,
    "unmapped_skips_total": 4,
    "failed_writes_total": 0
  }
}
```

If the project chooses in-process startup instead, the startup path must be explicit, e.g. `ENABLE_MQTT_SUBSCRIBER=true` in `backend/main.py`, and tests must prove disabled-by-default behavior plus enabled startup. Do not rely on importing `services.mqtt.subscriber` to start work.

## Audit and authorization

- Read endpoints (`status`, raw devices, latest readings, mapping list/audit, threshold reads) require `MQTT_READ` through centralized dependency/service checks.
- Mapping and threshold mutation endpoints require `MQTT_MAPPING_MANAGE` through centralized dependency/service checks.
- If the permission enum cannot be extended in the implementation slice, the temporary mapping to existing permissions must be declared in one place only (`mqtt_mapping_service.require_mqtt_permission(kind)`) and tested; route handlers must not call broad permissions directly.
- Every denied mutation records an audit denial through `audit_service.record_denied` where feasible.
- Every successful or validation-failed mutation records `audit_service.record_critical_change` with before/after state.
- Bridge runtime outcomes are operational telemetry, not immutable audit events. Persist recent outcomes/counters through `mqtt_runtime_status_repo` and mapping/source status fields; reserve audit events for human/operator changes.

## Testing strategy under strict TDD

Strict TDD is active. Write failing tests before implementation and keep tests with each behavior work unit.

### Unit tests

| Test file | Required coverage |
|-----------|-------------------|
| `backend/tests/test_mqtt_mapping_repo.py` | Create mapping, approve, revoke, conflict rejection, target/source existence checks, no duplicate approved mapping. |
| `backend/tests/test_mqtt_mapping_service.py` | Lifecycle validation, permission checks, audit calls, before/after snapshots. |
| `backend/tests/test_mqtt_bridge_service.py` | Approved mapping emits one Timescale sample and event envelope; unmapped/draft/revoked/ambiguous/missing target are blocked and observable; duplicate idempotency keys do not duplicate sample/event writes. |
| `backend/tests/test_mqtt_threshold_service.py` | Threshold update persists to mapping, audit emitted, subsequent bridge envelope includes updated thresholds. |
| `backend/tests/test_mqtt_runtime_status.py` | Shared persisted heartbeat/status transitions for starting, connected, stale heartbeat, disconnected, last error, counters. |

### Router tests

| Test file | Required coverage |
|-----------|-------------------|
| `backend/tests/test_mqtt_router.py` | Raw endpoints label data as non-KPI and enforce `MQTT_READ`; mapping CRUD/approve/revoke endpoints enforce `MQTT_MAPPING_MANAGE`; status endpoint reports absent/running/stale subscriber states from shared persistence. |

Use `TestClient` patterns already present in router tests and override dependencies for auth/DB where possible.

### Integration/regression tests

| Test file | Required coverage |
|-----------|-------------------|
| `backend/tests/test_mqtt_subscriber_bridge_integration.py` | `_persist_reading` still stores raw data first, then invokes bridge; bridge skip does not prevent ACK after raw persistence; raw persistence failure still NACKs. |
| `backend/tests/test_mqtt_kpi_gate_regression.py` | Unmapped MQTT reading does not alter `metric_values`, `/api/metrics/.../history`, or event writer calls. |
| `backend/tests/test_mqtt_mapped_event_flow.py` | Approved mapping writes `MetricValue` and derives threshold breach/recovery through `polling.event_writer`; partial Timescale-success/event-failure retry does not duplicate samples. |
| `backend/tests/test_mqtt_runtime_entrypoint.py` | Dedicated entrypoint starts `mqtt_subscriber_loop()` and compose/service config is detectable in code-level smoke tests. |

### Negative tests are mandatory

The gate is the feature. These must fail before implementation and pass after:

- No approved mapping means no Timescale write.
- `DRAFT` mapping means no Timescale write.
- `REVOKED` mapping means no Timescale write.
- Ambiguous approved mappings mean no Timescale write.
- Non-numeric value does not enter threshold event path.
- Target CI/MetricDef deletion after approval blocks bridge writes.
- Threshold update changes next event evaluation without recreating mapping.
- Duplicate MQTT delivery with the same idempotency key does not duplicate Timescale samples or events.
- Stale/missing subscriber heartbeat makes `/api/mqtt/status` report non-running/degraded state.
- Raw/status endpoints reject callers without `MQTT_READ`; mapping/threshold mutations reject callers without `MQTT_MAPPING_MANAGE`.

## Rollout and rollback

### Rollout

1. Ship migrations and repository/service tests first.
2. Add read-only raw MQTT APIs and status endpoint.
3. Add mapping lifecycle APIs with audit.
4. Add bridge behind `MQTT_MAPPING_BRIDGE_ENABLED=false` initially if operators need staged deployment.
5. Wire dedicated subscriber runtime and status checks.
6. Enable bridge in a controlled environment and verify raw, unmapped, mapped, Timescale, and event outputs.

### Rollback

1. Set `MQTT_MAPPING_BRIDGE_ENABLED=false` or revoke mappings to stop new KPI writes.
2. Keep raw MQTT ingestion running if useful for troubleshooting.
3. Leave Timescale historical samples intact; they were created only from approved mappings.
4. Re-enable after fixing mappings or runtime issues.

## Workload and slicing guidance

Review budget is 1000 changed lines, but this change crosses ingestion, APIs, persistence, audit, runtime, and tests. Keep slices reviewable by behavior, not file type.

Recommended work units:

1. **Mapping persistence and lifecycle**: migration, repo, service, audit unit tests.
2. **Raw/status APIs**: router, raw read repository methods, runtime status object tests.
3. **Bridge gate**: bridge service and strict negative tests proving unmapped/unapproved data cannot write KPI/event paths.
4. **Thresholds and event reuse**: manual threshold API plus event envelope tests.
5. **Runtime wiring**: subscriber entrypoint/compose/main router inclusion and health verification tests.
6. **End-to-end regression**: mapped/unmapped integration tests and runbook notes if tasks include docs.

If implementation exceeds the line budget or touches unrelated monitoring internals, split after work unit 3. The bridge gate is the safest first merge boundary because it delivers the core risk control before runtime enablement.

## Acceptance checklist

- [ ] Raw MQTT remains queryable as `RAW_MQTT_NON_KPI`.
- [ ] Only `APPROVED` mappings can produce Timescale samples or events.
- [ ] Mapping lifecycle is explicit and audited.
- [ ] Manual thresholds are stored per mapping and applied in existing event evaluation.
- [ ] Subscriber runtime has explicit startup wiring and API-visible health.
- [ ] No first-slice UI or auto-mapping is introduced.
- [ ] Strict TDD tests cover positive and negative gate behavior.
