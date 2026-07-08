# Tasks — integrate-mqtt-readings-monitoring (Issue #321)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 1,050–1,500 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 → PR 3 → PR 4 |
| Delivery strategy | auto-forecast |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No — owner selected `feature-branch-chain` before PR1 apply.
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

## PR 1 — Core data model, mappings, idempotency, and raw-readability foundations (RED → GREEN → TRIANGULATE → REFACTOR)

**Scope:** `backend/migrations/003_mqtt_monitoring_mapping.cypher`, `backend/repositories/mqtt_mapping_repo.py`, `backend/repositories/mqtt_runtime_status_repo.py`, `backend/models/mqtt_metric_sample_receipt.py`, `backend/models/__init__.py`, `backend/main.py`, `backend/services/mqtt_runtime_status.py`, `backend/tests/test_mqtt_mapping_repo.py`, `backend/tests/test_mqtt_runtime_status_repo.py`.

1. - [x] Add persistence-contract tests for mapping and status stores first
   - Create `backend/tests/test_mqtt_mapping_repo.py` to validate:
     - `create_draft`, `approve` conflict behavior, `revoke`, and explicit status states (`DRAFT`, `APPROVED`, `REVOKED`)
     - source/target existence checks with deterministic query params
   - Create `backend/tests/test_mqtt_runtime_status_repo.py` to validate heartbeat CRUD semantics and stale detection timestamps.
   - Add tests that fail before implementation.

2. - [x] Add mapping schema and repository layer
   - Add `backend/migrations/003_mqtt_monitoring_mapping.cypher` with:
     - `MqttMetricMapping` constraints/indexes exactly matching states/fields from design
     - compatibility checks for no two active approved mappings per `(source_device_id, source_metric_id)` handled at service-level.
   - Implement `backend/repositories/mqtt_mapping_repo.py` with read/write APIs used by services and routers.

3. - [x] Add shared runtime status persistence
   - Add `backend/repositories/mqtt_runtime_status_repo.py` to store:
     - `configured`, `running`, `connected`, `subscribed_patterns`, `last_message_at`, `last_error`, `reason_code`, counters.
   - Implement `backend/services/mqtt_runtime_status.py` as a thin service with atomic counter updates and stale-read helpers.

4. - [x] Add mapped KPI receipt model for idempotency in Postgres
   - Add `backend/models/mqtt_metric_sample_receipt.py` with `idempotency_key` PK and status lifecycle fields.
   - Export from `backend/models/__init__.py`.
   - Ensure `backend/main.py` includes the model in startup metadata registration path (import before `Base.metadata.create_all`) so the table is created consistently on startup.

5. - [x] Verify isolated layer
   - Run focused tests in PR 1 scope only.
   - Confirm migration file is pure and additive (idempotent `IF NOT EXISTS` statements, no data rewrite).
   - If repo/service contracts prove too coupled, split PR 1 into DB bootstrap-only and repository-only slices.

---

## PR 2 — Permission model and explicit authorization entry point (RED → GREEN → TRIANGULATE)

**Scope:** `backend/models/user.py`, `backend/services/mqtt_mapping_service.py`, `backend/tests/test_mqtt_permissions.py`, `backend/seed_roles.py`.

1. - [x] **[RED] Add/lock authorization tests before code changes**
   - Add `backend/tests/test_mqtt_permissions.py` for read/write boundary checks on MQTT read and mapping permission kinds.
   - Include:
     - read paths denied without read permission
     - mapping lifecycle mutation denied without mapping permission
     - compatibility fallback decision path (if enum extension blocked).

2. - [x] **[GREEN] Implement explicit permission surface**
   - Prefer enum extension in `backend/models/user.py`:
     - add `MQTT_READ`
     - add `MQTT_MAPPING_MANAGE`
   - Add centralized compatibility path in `backend/services/mqtt_mapping_service.py` as `require_mqtt_permission(kind, current_user)` and keep route-level code only calling this one helper.
   - Keep compatibility with a single compatibility mapping constant if enum extension is unavailable in environment.

3. - [x] **[GREEN] Seed roles/permission defaults intentionally**
   - Update `backend/seed_roles.py` to include these new perms where operational visibility/mapping is expected (at least `OPERATOR` + any existing admin-like automation roles).
   - Do not implicitly grant by route decorators.

4. - [x] **[TRIANGULATE] Validate auth behavior**
   - Run permission tests and one negative router auth path test.
   - Rollback-safe boundary: if permission behavior is disputed, keep PR 2 limited to helper + enum update only.

---

## PR 3 — Raw MQTT API visibility and mapping/threshold CRUD API (RED → GREEN → TRIANGULATE → REFACTOR)

**Scope:** `backend/repositories/device_metric_repo.py`, `backend/services/mqtt_raw_reading_service.py`, `backend/services/mqtt_mapping_service.py`, `backend/models/mqtt.py`, `backend/routers/mqtt.py`, `backend/main.py`, `backend/tests/test_mqtt_router.py`, `backend/tests/test_mqtt_mapping_service.py`.

1. **[RED] Add raw/mapper API tests and schema tests first**
   - Add `backend/tests/test_mqtt_router.py` and `backend/tests/test_mqtt_mapping_service.py` for:
     - raw devices + latest metric endpoints return `RAW_MQTT_NON_KPI`, `kpi_eligible=false`
     - mapping status values `UNMAPPED|DRAFT|APPROVED|REVOKED`
     - threshold CRUD read path for mapped records only
     - deny-list behavior for unauthorized access.

2. **[GREEN] Extend raw read model and router layer**
   - Add lightweight response DTOs in `backend/models/mqtt.py` (raw reading, mapping summary, threshold payloads).
   - Extend `backend/repositories/device_metric_repo.py` with API-specific read queries for latest per-metric sample and per-device listing that include mapping status if available.
   - Implement `backend/services/mqtt_raw_reading_service.py` (or equivalent) to join mapping state + raw reading view and annotate non-KPI.
   - Add `backend/routers/mqtt.py` endpoints under `/api/mqtt`:
     - `GET /status`
     - `GET /devices`
     - `GET /devices/{device_id}/metrics`
     - `GET /readings`
     - `GET /mappings`, `POST`, `PUT`, `/approve`, `/revoke`, `/audit`
     - threshold read/update endpoints.
   - Register `backend/routers/mqtt.py` in `backend/main.py`.

3. **[GREEN] Manual-threshold behavior contracts**
   - Ensure `MQTT mapping threshold` read/update operations persist operator, warning, critical, status, and versions to mapping records and return them in API responses.
   - Enforce that updates are rejected for non-APPROVED mappings without affecting raw visibility.

4. **[TRIANGULATE] Lock API contract**
   - Validate router-level request/response schema with strict tests.
   - Add negative tests for malformed threshold payloads and invalid CI/MetricDef linkage.

5. **[REFACTOR] Keep API contract stable**
   - Keep `classification` field explicit and stable across raw endpoints.
   - Ensure payloads always include non-KPI evidence when raw endpoints are queried.

---

## PR 4 — Fail-closed bridge gating + idempotent KPI write/event path (RED → GREEN → TRIANGULATE → REFACTOR)

**Scope:** `backend/services/mqtt_bridge_service.py`, `backend/services/mqtt/subscriber.py`, `backend/services/mqtt_mapping_service.py`, `backend/repositories/mqtt_mapping_repo.py`, `backend/repositories/mqtt_runtime_status_repo.py`, `backend/polling/event_writer.py` (call site only), `backend/repositories/metric_repo.py` (shared write path if needed), `backend/tests/test_mqtt_bridge_service.py`, `backend/tests/test_mqtt_mapped_event_flow.py`, `backend/tests/test_mqtt_kpi_gate_regression.py`, `backend/tests/test_mqtt_subscriber_bridge_integration.py`.

1. - [x] **[RED] Add negative/positive bridge tests first**
   - Add/extend:
     - `backend/tests/test_mqtt_bridge_service.py` for outcomes:
       - unmapped, `DRAFT`, `REVOKED`, ambiguous mapping -> no Timescale/event writes
       - approved + valid mapping + matching target -> writes exactly once
       - duplicate payload/idempotency -> skip duplicate writes
       - partial failure after metric persistence retries only event step.

2. - [x] **[GREEN] Add fail-closed bridge service**
   - Implement `backend/services/mqtt_bridge_service.py`:
     - resolve approved mapping only
     - map raw samples to `(ci_id, metric_id)`
     - produce deterministic idempotency key
     - insert/read `mqtt_metric_sample_receipts`
     - write Timescale only when mapping `APPROVED` and no duplicate/active conflict.
   - Insert metric via existing Timescale path (`metric_repo.insert_metric_value`) and call `polling.event_writer.batch_update_events()` only through bridge envelope.
   - Preserve source-to-history: raw data is already persisted regardless of bridge outcome.

3. - [x] **[GREEN] Wire fail-closed path in subscriber ingestion**
   - Update `backend/services/mqtt/subscriber.py:_persist_reading` to invoke bridge service after successful raw write.
   - Ensure bridge failures are observable and do not block raw ACK policy for raw raw persistence failures.

4. - [x] **[GREEN] Add idempotency/state updates and outcome surfacing**
   - Use receipt status transitions to support:
     - `PENDING_EVENT`, `COMPLETE`, `FAILED`
   - On `TIMESCALE_WRITE` success and event failure, persist `PENDING_EVENT` and retry only event generation on the next cycle.
   - Expose outcome counters in `mqtt/status`.

5. - [x] **[TRIANGULATE] Regression and safety proof**
   - Add `backend/tests/test_mqtt_kpi_gate_regression.py` proving unmapped/unapproved reads cannot alter `metric_values`, `/api/metrics/.../history`, or event write rows.
   - Add `backend/tests/test_mqtt_mapped_event_flow.py` proving mapped writes evaluate thresholds through existing event path and threshold updates apply without remapping.

6. - [x] **[REFACTOR] Tighten edge handling**
   - Normalize ambiguous mapping behavior to explicit fail-closed outcomes (`SKIPPED_UNMAPPED`, `BLOCKED_AMBIGUOUS_MAPPING`, etc.).
   - Keep raw path unchanged for ingestion observability.

---

## PR 5 — Runtime subscriber topology and operational proof (RED → GREEN → TRIANGULATE)

**Scope:** `backend/scripts/mqtt_subscriber.py`, `backend/config.py`, `backend/main.py`, `docker-compose.yml`, `backend/repositories/mqtt_runtime_status_repo.py`, `backend/services/mqtt_runtime_status.py`, `backend/tests/test_mqtt_runtime_entrypoint.py`, `backend/tests/test_mqtt_runtime_status.py`.

1. - [x] **[RED] Add runtime wiring tests first**
   - Add `backend/tests/test_mqtt_runtime_entrypoint.py` for startup command behavior and explicit entrypoint semantics.
   - Add `backend/tests/test_mqtt_runtime_status.py` for heartbeat freshness and transition states (`running` true/false, stale heartbeat, disconnect error reason).

2. - [x] **[GREEN] Add dedicated subscriber process entrypoint**
   - Implement `backend/scripts/mqtt_subscriber.py` that imports and runs the shared mqtt loop.
   - Ensure status service updates `running/connected` and heartbeat timestamps to shared store.

3. - [x] **[GREEN] Wire runtime configurability**
   - Add config flags in `backend/config.py` for `MQTT_MAPPING_BRIDGE_ENABLED` and `MQTT_MAPPING_BRIDGE_MISSED_HEARTBEAT_SECONDS` (or equivalent).
   - In `backend/main.py`, avoid implicit in-process subscriber startup; route process ownership to explicit flags/services.

4. - [x] **[GREEN] Add deployment wiring**
   - Add `mqtt-subscriber` service in `docker-compose.yml` (explicit command `python -m scripts.mqtt_subscriber`).

5. **[TRIANGULATE] Verify observability behavior end-to-end**
   - Confirm `/api/mqtt/status` reports stale/disconnected state when dedicated subscriber is absent and non-stale when running.
   - Validate startup contract in compose/manual smoke check notes.

## Risks and dependencies

- PR 1 (mapping repo + idempotency models) is prerequisite for PR 3/4.
- PR 2 (permission service) is prerequisite for PR 3/4 router enforcement.
- PR 3 (mapping CRUD + raw endpoints) should be reviewed before PR 4 (bridge) so API/API-logic expectations are stable.
- PR 5 can run after PR 4 has basic bridge status counters implemented (for meaningful status payload).

## Rollback guidance (per PR)

- PR 1 rollback: drop/ignore new migration + repos/files; leave existing raw MQTT path unchanged.
- PR 2 rollback: remove permission enum+helper and restore previous route-level checks.
- PR 3 rollback: keep raw read path untouched by reverting router/model additions only.
- PR 4 rollback: remove bridge call from subscriber and disable bridge path; raw persistence remains.
- PR 5 rollback: stop/retain compose service and restore main/runtime default state without dedicated process.

## Delivery recommendation

Given estimated size and cross-layer coupling, **CHAINED PRs are recommended** before apply. Chain strategy remains **pending** until the team selects `stacked-to-main` or `feature-branch-chain`.
