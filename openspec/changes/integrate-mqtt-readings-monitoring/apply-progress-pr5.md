# PR5 Apply Progress

## Completed tasks

- [x] Add runtime wiring tests for PR5 (`backend/tests/test_mqtt_runtime_entrypoint.py`, `backend/tests/test_mqtt_runtime_status.py`).
- [x] Implement dedicated subscriber process entrypoint (`backend/scripts/mqtt_subscriber.py`).
- [x] Wire runtime configurability (`backend/config.py`, `backend/main.py`).
- [x] Add `mqtt-subscriber` docker-compose service (`docker-compose.yml`).
- [x] Triangulate observability behavior with runtime status unit/service tests and subscriber-loop status update coverage.

## Files changed

- `backend/config.py`
- `backend/services/mqtt_runtime_status.py`
- `backend/services/mqtt/subscriber.py`
- `backend/main.py`
- `backend/scripts/mqtt_subscriber.py`
- `backend/tests/test_mqtt_runtime_entrypoint.py`
- `backend/tests/test_mqtt_runtime_status.py`
- `docker-compose.yml`
- `openspec/changes/integrate-mqtt-readings-monitoring/tasks.md`
- `openspec/changes/integrate-mqtt-readings-monitoring/apply-progress-pr5.md`

## TDD Cycle Evidence

| Task | RED test added | GREEN implementation | Triangulate check |
|------|----------------|---------------------|------------------|
| Runtime entrypoint contract | `backend/tests/test_mqtt_runtime_entrypoint.py` | `backend/scripts/mqtt_subscriber.py` | `./backend/.venv/bin/python -m pytest backend/tests/test_mqtt_runtime_entrypoint.py ...` passed |
| Runtime status transitions | `backend/tests/test_mqtt_runtime_status.py` | `backend/services/mqtt_runtime_status.py` | Runtime status focused suite passed |
| Subscriber loop ownership/status safety | Existing subscriber loop smoke test exposed DB-status coupling; fixed with best-effort `_safe_status_update` guard | `backend/services/mqtt/subscriber.py` records status without letting status-store failures kill subscriber liveness | Subscriber loop suite passed |
| Runtime formatting/lint safety net | Ruff/Black run after implementation | Touched runtime files formatted | Ruff and Black check passed |

## Verification evidence

```bash
./backend/.venv/bin/python -m pytest backend/tests/test_mqtt_runtime_entrypoint.py backend/tests/test_mqtt_runtime_status.py backend/tests/test_mqtt_runtime_status_service.py backend/tests/test_mqtt_runtime_status_repo.py backend/tests/test_mqtt_subscriber_loop.py -q
# 30 passed, 7 warnings

./backend/.venv/bin/ruff check backend/config.py backend/main.py backend/services/mqtt/subscriber.py backend/services/mqtt_runtime_status.py backend/scripts/mqtt_subscriber.py backend/tests/test_mqtt_runtime_entrypoint.py backend/tests/test_mqtt_runtime_status.py
# All checks passed

./backend/.venv/bin/black --check backend/config.py backend/main.py backend/services/mqtt/subscriber.py backend/services/mqtt_runtime_status.py backend/scripts/mqtt_subscriber.py backend/tests/test_mqtt_runtime_entrypoint.py backend/tests/test_mqtt_runtime_status.py
# 8 files would be left unchanged
```

## Test commands attempted

- Initial subagent environment lacked pytest, but parent reran all PR5 focused tests through `backend/.venv` successfully.

## Deviations / notes

- Runtime status service now defaults stale heartbeat threshold from `MQTT_MAPPING_BRIDGE_MISSED_HEARTBEAT_SECONDS` via `get_mqtt_runtime_settings()`.
- Subscriber loop now records running/connected/heartbeat to shared status store and uses `MQTT_MAPPING_BRIDGE_ENABLED` as a soft-fail gate for KPI bridge side effects.
- Runtime status updates are best-effort in both the dedicated entrypoint and shared loop so status-store failure cannot prevent raw subscriber liveness.
- Focused regression tests cover disabled-by-default backend ownership, explicit embedded subscriber enablement, env-var parsing contracts, idle heartbeat emission without reconnect churn, and bridge-disabled raw persistence.
- The compose `mqtt-subscriber` service no longer commits a fallback database password or fake broker hostname; those values must come from the environment.
- Main startup now only starts an in-process MQTT subscriber when `ENABLE_MQTT_SUBSCRIBER=true`.
- Compose service uses `python -m scripts.mqtt_subscriber` and explicit env controls.

## Remaining tasks

- [ ] Optional manual compose smoke after PR review: confirm `/api/mqtt/status` stale/disconnected behavior with dedicated subscriber absent vs active in a real compose environment.
- [x] Startup contract documented in tests and compose command (`python -m scripts.mqtt_subscriber`).
