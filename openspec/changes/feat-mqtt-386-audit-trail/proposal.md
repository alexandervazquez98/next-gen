# Proposal: MQTT Mapping Lifecycle Audit Trail

## Intent

MQTT mapping lifecycle ops (`create`, `update`, `approve`, `revoke`, `update_thresholds`) gate which raw MQTT sources produce official CI/MetricDef KPIs. Today the lifecycle mutates silently — no audit row emitted. Reuse the existing audit pipeline to persist a versioned, sensitive-field-safe row per action and denied attempt.

## Scope

### In Scope
- Emit audit rows for 5 lifecycle events (`MQTT_MAPPING_CREATE` / `_UPDATE` / `_APPROVE` / `_REVOKE` / `_THRESHOLD_UPDATE`) — success, validation, denied.
- Extend `AUDIT_CONTEXT_ALLOWED_KEYS` with mapping context keys (source/target ids, previous_state, next_state, version, changed_fields).
- Backend tests for emission + sensitive-field exclusion.
- Verify `GET /audit/events` + `AuditLogPage` render mapping rows via `target_type`/`target_id`.

### Out of Scope
- New MQTT mapping detail UI (none exists; AuditLogPage is sufficient).
- MQTT payload retention/replay; threshold semantics; auto-mapping; retention/cleanup changes.

## Capabilities

### New Capabilities
- `mqtt-mapping-lifecycle`: lifecycle rules + audit emission + redaction.

### Modified Capabilities
- `audit-logging`: extend allow-list; require mapping lifecycle events use `target_type=mqtt_mapping`.

## Approach

1. **Reuse, do not duplicate.** Rows flow through `audit_service.record_critical_change` / `record_denied` into the existing `audit_events` table.
2. **Extend allow-list** in `backend/services/audit_service.py`: `source_device_id`, `source_metric_id`, `target_ci_id`, `target_metric_def_id`, `previous_status`, `next_status`, `version`, `changed_fields`. `sanitize_context` strips token/cookie/body.
3. **Emit at the service layer** (`backend/services/mqtt_mapping_service.py`). `previous_status` from `self._repo.get_mapping` pre-mutation; `next_status` action-derived (`CREATE→DRAFT`, `APPROVE→APPROVED`, `REVOKE→REVOKED`; `UPDATE→DRAFT`; `THRESHOLD_UPDATE→APPROVED`). `record_denied` before `HTTPException`.
4. **Surface via existing API/UI** — no new endpoint/screen.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/services/audit_service.py` | Modified | Extend allow-list (+8 keys). |
| `backend/services/mqtt_mapping_service.py` | Modified | Emit rows from 5 mutations. |
| `backend/tests/test_mqtt_mapping_service.py` | Modified | Emission + redaction tests. |
| `backend/tests/test_audit_service.py` | Modified | Allow-list + redaction. |
| `openspec/specs/audit-logging/spec.md` | Delta | Lifecycle requirement. |
| `openspec/specs/mqtt-mapping-lifecycle/spec.md` | New | Lifecycle + emission. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Emission fails silently | Low | `_persist_event` swallows errors with warning. |
| Payload/credential leak | Low | `sanitize_context` strips token/body/cookie/password. |
| Row volume strains retention | Low | ~600B/row; existing 90-day window. |
| Allow-list breaks other events | Low | Additive keys. |

## Rollback Plan

1. Revert emission in `mqtt_mapping_service.py`.
2. Revert allow-list extension.
3. Drop new capability; revert `audit-logging` delta.
4. Historical rows stay queryable (no schema migration).

## Dependencies

- `audit-logging` + `audit_service` (shipped).
- `MQTT_MAPPING_MANAGE` + `AUDIT_VIEW` perms (shipped).

## Success Criteria

- [ ] Each of 5 lifecycle events produces one audit row per call.
- [ ] Row has `actor_username`, `created_at`, `target_id`, `event_type`, `outcome`, `target_type=mqtt_mapping`, context keys.
- [ ] No row contains payload body, PII source_topic, or token/cookie/password.
- [ ] `GET /audit/events?target_type=mqtt_mapping&target_id={id}` returns history.
- [ ] Backend tests pass.