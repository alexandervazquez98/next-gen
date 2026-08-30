# Tasks: MQTT Mapping Lifecycle Audit Trail

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 200–300 (backend) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | single PR |
| Delivery strategy | single-pr |
| Chain strategy | stacked-to-main (single-PR elected) |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: stacked-to-main
400-line budget risk: Low

> **Reconciliation — outcome casing**: spec uses lowercase; `AuditOutcome` in `routers/audit.py:21` + 30+ tests require uppercase. Apply emits uppercase; flag for spec follow-up.

### Suggested Work Units

| Unit | Goal | Focused test | Runtime | Rollback |
|------|------|--------------|---------|----------|
| WU1 | Allow-list ext | `pytest backend/tests/test_audit_service.py -k mapping_context` | N/A | Revert 9 keys at `audit_service.py:18-31` |
| WU2 | Helper | `pytest backend/tests/test_mqtt_mapping_service.py -k denied_emits` | N/A | Revert helper in `mqtt_mapping_service.py` |
| WU3 | Emit 5 mutations | `pytest backend/tests/test_mqtt_mapping_service.py` | N/A | Revert emission blocks per method |
| WU4 | Router+isolation | `cd backend && python -m pytest tests/test_mqtt_mapping_service.py tests/test_audit_service.py tests/test_mqtt_router.py` | N/A | Revert `routers/mqtt.py` dep additions |

## Phase 1: Allow-list Foundation (WU1)

- [x] 1.1 RED — `test_audit_service.py`: 9 mapping keys survive `sanitize_context`; sensitive keys stripped. Spec: *Mapping context keys survive sanitization*, *Sensitive payload keys never persist*.
- [x] 1.2 GREEN — Append 9 keys to `AUDIT_CONTEXT_ALLOWED_KEYS` at `audit_service.py:18-31` (additive).

## Phase 2: Service Layer (WU2 + WU3)

- [x] 2.1 RED — `test_mqtt_mapping_service.py`: every action emits `event_type=MQTT_MAPPING_<ACT>` + `outcome=DENIED`; `record_denied` NEVER called. Spec: *Denied approve attempt is audited*.
- [x] 2.2 GREEN — Add `_enforce_manage_with_audit(*, current_user, db, request, mapping_id, event_type)` in `mqtt_mapping_service.py`: on no perm emits denial row, then `require_mqtt_permission` raises.
- [x] 2.3 RED — `test_create_mapping_emits_audit_row_success`: outcome=SUCCESS, `previous_state=None`, `next_state=DRAFT`, `version=1` (spec: *Create produces a CREATE audit row*).
- [x] 2.4 GREEN — `create_mapping`: add `db`+`request` kwargs; emit `record_critical_change(MQTT_MAPPING_CREATE, SUCCESS, target_type=mqtt_mapping, target_id=mapping_id, context=9 keys)`.
- [x] 2.5 GREEN — `update_mapping`: same; `changed_fields` from `payload.dict(exclude_unset=True)` diff vs pre-read. Spec: *Update enumerates changed fields*.
- [x] 2.6 GREEN — `approve_mapping` + `revoke_mapping`: same with pre-read `previous_state` via `self._repo.get_mapping(...)`. Spec: *Approve transitions DRAFT to APPROVED*, *Revoke from APPROVED*.
- [x] 2.7 GREEN — `update_thresholds`: same; `previous_state=next_state=APPROVED`; threshold keys in `changed_fields`. Spec: *Threshold update on APPROVED mapping*.
- [x] 2.8 GREEN — `try/except HTTPException` on repo calls: on 404/409 emit `VALIDATION_FAILURE` row then re-raise.

## Phase 3: Router + Isolation (WU4)

- [x] 3.1 RED — `test_mqtt_mapping_service.py`: `source_topic`, >256-char strings, `body`/`raw_body` stripped/truncated.
- [x] 3.2 GREEN — `routers/mqtt.py` 5 mutation endpoints: thread `Depends(get_pg_db)` + `Request` into service calls as kw-only kwargs.
- [x] 3.3 GREEN — Stub `record_critical_change` to raise — mutation returns repo result / raises `HTTPException`. Spec: *Mutation succeeds when emission fails*.

## Phase 4: Final Verification

- [x] 4.1 `cd backend && python -m pytest tests/test_mqtt_mapping_service.py tests/test_audit_service.py tests/test_mqtt_router.py -v` all green.
- [x] 4.2 `cd backend && ruff check . && mypy services/audit_service.py services/mqtt_mapping_service.py routers/mqtt.py` clean.
- [x] 4.3 FastAPI TestClient: `GET /api/audit/events?target_type=mqtt_mapping&target_id=<id>` returns history ordered by `created_at`. Spec: *Mapping events are queryable by target filter*.
