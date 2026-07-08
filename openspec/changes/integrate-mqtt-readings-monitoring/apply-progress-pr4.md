# Apply Progress — integrate-mqtt-readings-monitoring (PR4 scope)

## Scope

PR4 implements fail-closed MQTT→monitoring bridge behavior, idempotent receipt-driven deduplication, and failure-safe subscriber wiring.

## Completed tasks (PR4)

- [x] Add/extend bridge contract tests for unmapped/invalid mappings, approved write path, idempotency, and partial event failure retry behavior.
- [x] Implement `backend/services/mqtt_bridge_service.py` with:
  - approved-only mapping gate
  - deterministic idempotency keys + mapped sample receipts
  - metric write + event write sequencing
  - status-aware retry only on event step
- [x] Invoke bridge service from `backend/services/mqtt/subscriber.py` after raw persistence with non-fatal failure handling.
- [x] Extend `/api/mqtt/status` endpoint to expose runtime bridge counters.
- [x] Add regression tests proving approved-only KPI writes, threshold propagation, and subscriber/raw-bridge isolation.

## Files changed

- `backend/services/mqtt_bridge_service.py`
- `backend/services/mqtt/subscriber.py`
- `backend/polling/event_writer.py`
- `backend/repositories/mqtt_mapping_repo.py`
- `backend/repositories/mqtt_metric_sample_receipt_repo.py`
- `backend/migrations/004_mqtt_metric_result_idempotency.cypher`
- `backend/routers/mqtt.py`
- `backend/tests/test_mqtt_bridge_service.py`
- `backend/tests/test_mqtt_mapped_event_flow.py`
- `backend/tests/test_mqtt_kpi_gate_regression.py`
- `backend/tests/test_mqtt_subscriber_bridge_integration.py`
- `backend/tests/test_polling_event_writer.py`
- `backend/tests/test_mqtt_router.py`
- `openspec/changes/integrate-mqtt-readings-monitoring/apply-progress-pr4.md`

## Verification

### TDD evidence

| Phase | Command | Result |
|---|---|---|
| RED | `./backend/.venv/bin/pytest backend/tests/test_mqtt_bridge_service.py` (before implementation snapshot) | New gate-path tests added first |
| GREEN | `./backend/.venv/bin/pytest backend/tests/test_mqtt_bridge_service.py backend/tests/test_mqtt_mapped_event_flow.py backend/tests/test_mqtt_kpi_gate_regression.py backend/tests/test_mqtt_subscriber_bridge_integration.py` | PASS |
| TRIANGULATE | Cross-verified with existing router/subscriber/runtime suites: `./backend/.venv/bin/pytest backend/tests/test_mqtt_router.py backend/tests/test_mqtt_subscriber_loop.py backend/tests/test_mqtt_runtime_status_service.py backend/tests/test_mqtt_runtime_status_repo.py` | PASS |
| SAFETY NET | `cd backend && ../backend/.venv/bin/python -m pytest` | Known-baseline unrelated failures: 2 auth cookie-domain assertions and 4 Docker/testcontainers advisory-lock failures; PR4 focused suites pass. |
| REFACTOR | Formatting / lint pass: `ruff`, `black` on touched files | PASS |

### TDD Cycle Evidence

| PR4 task | RED evidence | GREEN evidence | TRIANGULATE evidence | SAFETY NET evidence | REFACTOR evidence |
|---|---|---|---|---|---|
| Fail-closed bridge gate | Added `test_mqtt_bridge_service.py` cases for unmapped, `DRAFT`, `REVOKED`, ambiguous, and non-numeric readings before bridge implementation. | `MqttBridgeService.process_reading()` resolves approved mappings only and returns `SKIPPED_UNMAPPED`, `SKIPPED_DRAFT`, `SKIPPED_REVOKED`, `BLOCKED_AMBIGUOUS_MAPPING`, or `SKIPPED_NON_NUMERIC` before metric/event calls. | `test_mqtt_kpi_gate_regression.py` proves unapproved readings do not call KPI/event writers. | Focused PR4 bridge/regression command passed; full suite failures are existing auth cookie/Docker testcontainers issues outside PR4 files. | Ruff/Black passed on bridge, repository, router, subscriber, and test files. |
| Idempotent KPI write and event path | Added approved mapping, duplicate payload, and partial event failure retry tests before receipt-driven implementation. | `mqtt_metric_sample_receipt_repo.py` plus bridge receipt state transitions implement `PENDING_EVENT`, `COMPLETE`, and `FAILED` semantics. | `test_mqtt_mapped_event_flow.py` proves threshold metadata reaches the event writer; duplicate and partial retry tests prove no duplicate sample writes. | Focused bridge + mapped event suites passed. | Formatting/lint completed after implementation. |
| Subscriber bridge integration | Added subscriber integration test proving bridge failures do not break raw persistence/ACK behavior. | `services/mqtt/subscriber.py` invokes the bridge after raw persistence and catches/logs bridge failures. | Existing subscriber loop tests passed alongside PR4 integration tests. | Router/subscriber/runtime focused command passed. | Ruff/Black passed. |
| Bridge outcome counters | Added/extended router status tests for bridge counters. | `/api/mqtt/status` exposes runtime status plus `mapped_writes_total`, `unmapped_skips_total`, and `failed_writes_total`. | Runtime status service/repo tests passed with router tests. | Focused router/runtime command passed. | Formatting/lint completed. |
| PR4 blocker remediation (locking + idempotent MetricResult) | Added lock-factory and idempotent row regression coverage before blocker-fix implementation. | Subscriber now passes `SessionLocal` into `get_mqtt_bridge_service(event_writer_lock_db=...)`; `polling.event_writer` merges `MetricResult`, `HAS_RESULT`, and `FOR_METRIC` for idempotent rows keyed by `idempotency_key`; migration `004_mqtt_metric_result_idempotency.cypher` adds a uniqueness guard. | `test_polling_event_writer.py` and `test_mqtt_subscriber_bridge_integration.py` validate dedupe behavior, replay-safe relationships, uniqueness guard, and lock propagation. | Focused blocker tests: 32 passed. | Ruff/Black completed on touched files. |

### Focused test evidence

```bash
./backend/.venv/bin/pytest backend/tests/test_mqtt_bridge_service.py \
  backend/tests/test_mqtt_mapped_event_flow.py \
  backend/tests/test_mqtt_kpi_gate_regression.py \
  backend/tests/test_mqtt_subscriber_bridge_integration.py
# 20 passed

./backend/.venv/bin/pytest backend/tests/test_mqtt_router.py \
  backend/tests/test_mqtt_subscriber_loop.py \
  backend/tests/test_mqtt_runtime_status_service.py \
  backend/tests/test_mqtt_runtime_status_repo.py
# 27 passed
```

```bash
./backend/.venv/bin/ruff check --fix backend/services/mqtt_bridge_service.py backend/services/mqtt/subscriber.py backend/routers/mqtt.py backend/tests/test_mqtt_bridge_service.py backend/tests/test_mqtt_mapped_event_flow.py backend/tests/test_mqtt_kpi_gate_regression.py backend/tests/test_mqtt_subscriber_bridge_integration.py backend/repositories/mqtt_metric_sample_receipt_repo.py backend/repositories/mqtt_mapping_repo.py
# All checks passed

./backend/.venv/bin/black backend/services/mqtt_bridge_service.py backend/services/mqtt/subscriber.py backend/tests/test_mqtt_bridge_service.py backend/tests/test_mqtt_mapped_event_flow.py backend/tests/test_mqtt_subscriber_bridge_integration.py backend/repositories/mqtt_metric_sample_receipt_repo.py backend/repositories/mqtt_mapping_repo.py
# Reformatted/normalized files
```

## Remaining tasks

- [ ] None (PR4 scope completed).

## Workload / PR boundary

- Chained PR mode is in effect for this issue (`feature-branch-chain` in change tasks).
- PR4 remains the bridge/fail-closed slice boundary.

## Continuation: PR4 blocker remediation

- [x] Restore `backend/services/mqtt_bridge_service.py` after prior refactor corruption and keep it stable.
- [x] Keep `list_mappings_for_source` as primary method and retain compatibility fallback to `list_approved_mappings_for_source` for legacy tests/callers.
- [x] Normalize receipt lifecycle states with explicit `PENDING_METRIC`, `PENDING_EVENT`, `COMPLETE`, and `FAILED` transitions.
- [x] Add/extend edge-case tests for:
  - idempotent metric writer handling on `IntegrityError`
  - event-only retry path (including `PENDING_EVENT` replays)
  - lock-db writer path and pending-event counter semantics
- [x] Keep counter semantics so event-only pending outcomes are tracked as failed-write counters.
- [x] Add Neo4j uniqueness guard for `MetricResult.idempotency_key` and make idempotent replay use `MERGE` for `FOR_METRIC` relationships.

### Continuation evidence

```bash
./backend/.venv/bin/pytest backend/tests/test_mqtt_bridge_service.py backend/tests/test_mqtt_mapped_event_flow.py backend/tests/test_mqtt_kpi_gate_regression.py backend/tests/test_mqtt_subscriber_bridge_integration.py
# 20 passed

./backend/.venv/bin/pytest backend/tests/test_polling_event_writer.py backend/tests/test_mqtt_subscriber_bridge_integration.py
# 32 passed (includes new PR4 blocker coverage)

./backend/.venv/bin/python -m pytest backend/tests/test_mqtt_bridge_service.py backend/tests/test_mqtt_mapped_event_flow.py backend/tests/test_mqtt_kpi_gate_regression.py backend/tests/test_mqtt_subscriber_bridge_integration.py backend/tests/test_polling_event_writer.py backend/tests/test_mqtt_router.py backend/tests/test_mqtt_subscriber_loop.py backend/tests/test_mqtt_runtime_status_service.py backend/tests/test_mqtt_runtime_status_repo.py -q
# 78 passed, 2 warnings

./backend/.venv/bin/ruff check backend/services/mqtt_bridge_service.py backend/services/mqtt/subscriber.py backend/routers/mqtt.py backend/polling/event_writer.py backend/repositories/mqtt_metric_sample_receipt_repo.py backend/repositories/mqtt_mapping_repo.py backend/tests/test_mqtt_bridge_service.py backend/tests/test_mqtt_mapped_event_flow.py backend/tests/test_mqtt_kpi_gate_regression.py backend/tests/test_mqtt_subscriber_bridge_integration.py backend/tests/test_polling_event_writer.py backend/tests/test_mqtt_router.py
# All checks passed

./backend/.venv/bin/black --check backend/services/mqtt_bridge_service.py backend/services/mqtt/subscriber.py backend/routers/mqtt.py backend/polling/event_writer.py backend/repositories/mqtt_metric_sample_receipt_repo.py backend/repositories/mqtt_mapping_repo.py backend/tests/test_mqtt_bridge_service.py backend/tests/test_mqtt_mapped_event_flow.py backend/tests/test_mqtt_kpi_gate_regression.py backend/tests/test_mqtt_subscriber_bridge_integration.py backend/tests/test_polling_event_writer.py backend/tests/test_mqtt_router.py
# 12 files would be left unchanged
```

## Continuation risks / notes

- PR4 blocker remediation is complete for this slice:
  - subscriber now injects caller-owned SQLAlchemy lock session into bridge calls
  - metric-result write path now deduplicates idempotent payloads and preserves MQTT replay semantics via idempotency_key MERGE
  - subscriber integration test now validates lock factory propagation (`event_writer_lock_db`)
  - event_writer idempotent duplicate test added
- No new blockers identified.

## Risks / Notes

- None blocking; remaining work is PR5 runtime entrypoint and runtime-status behavior hardening.
