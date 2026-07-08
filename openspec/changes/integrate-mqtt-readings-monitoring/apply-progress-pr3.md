# Apply Progress — integrate-mqtt-readings-monitoring (PR3 scope)

## Scope

PR3 implements raw MQTT API visibility plus mapping/threshold CRUD API foundations only.

## Files changed

- `backend/models/mqtt.py`
- `backend/repositories/device_metric_repo.py`
- `backend/repositories/mqtt_mapping_repo.py`
- `backend/services/mqtt_raw_reading_service.py`
- `backend/services/mqtt_mapping_service.py`
- `backend/routers/mqtt.py`
- `backend/main.py`
- `backend/tests/test_mqtt_router.py`
- `backend/tests/test_mqtt_mapping_service.py`

## TDD evidence

- RED tests were added for raw non-KPI visibility, permission-gated router access, mapping CRUD/approve/revoke endpoints, threshold validation, and service-level permission/error translation.
- GREEN implementation adds models, raw read service, router registration, mapping service CRUD wrappers, and repository read/update support.

## Verification

Completed:

```bash
cd backend && . .venv/bin/activate && ruff check --config ruff.toml --fix models/mqtt.py repositories/device_metric_repo.py repositories/mqtt_mapping_repo.py services/mqtt_raw_reading_service.py services/mqtt_mapping_service.py routers/mqtt.py main.py tests/test_mqtt_router.py tests/test_mqtt_mapping_service.py tests/test_mqtt_mapping_repo.py
# All checks passed

python -m black models/mqtt.py repositories/device_metric_repo.py repositories/mqtt_mapping_repo.py services/mqtt_raw_reading_service.py services/mqtt_mapping_service.py routers/mqtt.py main.py tests/test_mqtt_router.py tests/test_mqtt_mapping_service.py tests/test_mqtt_mapping_repo.py
# 2 files reformatted, 8 files left unchanged

ruff check --config ruff.toml models/mqtt.py repositories/device_metric_repo.py repositories/mqtt_mapping_repo.py services/mqtt_raw_reading_service.py services/mqtt_mapping_service.py routers/mqtt.py main.py tests/test_mqtt_router.py tests/test_mqtt_mapping_service.py tests/test_mqtt_mapping_repo.py
# All checks passed

python -m pytest tests/test_mqtt_router.py tests/test_mqtt_mapping_service.py tests/test_auth_extended.py::TestPermissionSecurity::test_permission_enum_completeness tests/test_mqtt_permissions.py tests/test_mqtt_mapping_repo.py tests/test_mqtt_runtime_status_repo.py tests/test_mqtt_runtime_status_service.py -q
# 49 passed, 2 warnings
```

## Out of scope

- PR4 bridge/KPI writes/event path.
- PR5 subscriber runtime entrypoint/compose wiring.
- MQTT runtime/status API surface.
- Mapping audit API surface until audit records are implemented.

## Review remediation

- Raw MQTT queries are scoped to source-topic devices to avoid exposing ordinary device metrics as raw MQTT telemetry.
- Raw service maps repository `id` fields to public `device_id` / `metric_id` response fields.
- Source metric relationship validation prevents mappings to nonexistent or unrelated raw metrics.
- Partial mapping updates preserve existing thresholds when thresholds are omitted.
- Threshold updates are accepted only for `APPROVED` mappings to preserve lifecycle boundaries.
