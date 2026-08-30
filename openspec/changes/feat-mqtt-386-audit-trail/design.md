# Design: MQTT Mapping Lifecycle Audit Trail

## Technical Approach

Reuse the existing `audit_events` table and `audit_service` helpers. Emit
exactly one row per lifecycle invocation (success, validation failure, denied)
from the **service layer** of `MqttMappingService`, with `db: Session` and
`Request` threaded in from the MQTT router. Extend the audit allow-list with
nine mapping-specific context keys. No schema migration, no new audit endpoints,
no UI changes.

## Goals

- Persist one audit row per invocation of `create_mapping`, `update_mapping`,
  `approve_mapping`, `revoke_mapping`, and `update_thresholds`.
- Persist rows for validation failures (HTTP 404/409 from repo) and permission
  denials, not only success.
- Guarantee lifecycle mutation succeeds even when audit persistence fails.
- Guarantee no token, cookie, authorization header, refresh token, request body,
  or raw MQTT payload body is persisted in audit context.

## Non-Goals

- New MQTT mapping detail UI (AuditLogPage already covers `target_type`/`target_id` filtering).
- Payload retention, threshold semantics, auto-mapping, retention/cleanup changes.
- Changing `record_denied` for non-MQTT callers (see Reconciliation below).

## Architecture Decisions

### Decision: Emit at service layer, not router layer

**Choice**: Add `db: Session` and `request: Request | None = None` parameters to
each of the 5 mutation methods on `MqttMappingService`. The MQTT router passes
its existing `Depends(get_pg_db)` and `Request` through.

**Alternatives considered**:
- *Router-layer emission* (current `nodes.py`/`users.py`/`backup.py` pattern): rejected — `previous_state` requires a pre-mutation read against Neo4j (`self._repo.get_mapping`), which only the service knows to perform. Routing it back to the router duplicates the read and splits lifecycle logic.
- *Repo-layer emission*: rejected — the audit table lives in Postgres (`audit_events`); the repo writes to Neo4j. Mixing stores at the repo would invert layering.

**Rationale**: Keeps `previous_state` capture next to where the mutation
happens, avoids duplicating the pre-read, and aligns with the proposal's
explicit "Emit at the service layer" directive.

### Decision: Bypass `record_denied` for lifecycle denials; call `record_critical_change` directly

**Choice**: For permission denials, emit via `record_critical_change` with
`event_type="MQTT_MAPPING_<ACTION>"` and `outcome="DENIED"`. Do **not** call
`record_denied`.

**Alternatives considered**:
- *Generalize `record_denied`* to accept `event_type` and keep using it for
  MQTT lifecycle: rejected — changes a shared utility used by 5+ routers
  (`users`, `roles`, `nodes`, `backup`, etc.). Risk of subtle regressions to
  unrelated callers is not justified for one feature.

**Rationale**: The spec's `Denied approve attempt is audited` scenario
requires `event_type=MQTT_MAPPING_APPROVE`, not `ACCESS_DENIED` (see
`openspec/changes/feat-mqtt-386-audit-trail/specs/audit-logging/spec.md`
Requirement: *Mapping lifecycle event types and target type* — `target_id`
filtering must work uniformly across success/validation/denial rows for a given
mapping). `record_denied` hardcodes `event_type="ACCESS_DENIED"` at line 253
of `audit_service.py`, so it cannot satisfy the spec without a contract change
that touches unrelated callers. Calling `record_critical_change` directly with
`outcome="DENIED"` is supported (the audit router's `AuditOutcome` Literal
includes `"DENIED"`) and reuses `sanitize_context` identically.

### Decision: Pre-read `previous_state` for `approve` and `revoke`

**Choice**: Add `self._repo.get_mapping(mapping_id)` at the start of
`approve_mapping` and `revoke_mapping` to capture `previous_state`.

**Rationale**: Required by the spec's *Approve by an authorized operator*
scenario (`previous_state=DRAFT`). The repo's `approve()` already reads it
internally, but that read happens too late (the SQL/Cypher has been issued by
the time the service returns). Doing the read at the service boundary keeps the
audit emission observable and idempotent.

### Decision: Use uppercase outcomes (`SUCCESS`, `DENIED`, `VALIDATION_FAILURE`)

**Choice**: Emit `outcome="SUCCESS" | "DENIED" | "VALIDATION_FAILURE"` (uppercase).

**Alternatives considered**:
- *Lowercase* (`success`, `denied`, `validation_failure`): matches the spec's
  literal text but breaks the `AuditOutcome = Literal["SUCCESS", "DENIED",
  "VALIDATION_FAILURE", "FAILURE"]` constraint in `routers/audit.py:21` and
  diverges from every existing test assertion (e.g. `kwargs["outcome"] ==
  "VALIDATION_FAILURE"`).

**Rationale**: Follow the project's existing convention (8 routers and 30+
tests assert uppercase). The spec's lowercase wording is flagged in *Open
Questions* for spec reconciliation in a follow-up; behavior stays correct.

### Decision: Encapsulate the "denied + raise" flow in a private service helper

**Choice**: Add `_enforce_manage_with_audit(current_user, db, request,
mapping_id, event_type)` inside `mqtt_mapping_service.py`. It checks
`_user_has_permission`, emits `record_critical_change(outcome="DENIED")` when
false, then calls `require_mqtt_permission` (which raises). All 5 mutation
methods call it.

**Rationale**: Keeps `require_mqtt_permission` (module-level, also used by
`list_mappings`/`get_thresholds`/`list_mqtt_devices`) untouched. One helper,
five call sites, zero duplication.

### Decision: Allow-list extension (additive only)

**Choice**: Append to `AUDIT_CONTEXT_ALLOWED_KEYS` (currently 9 keys at
`audit_service.py:18-31`):
`mapping_id`, `source_device_id`, `source_metric_id`, `target_ci_id`,
`target_metric_def_id`, `previous_state`, `next_state`, `version`,
`changed_fields`.

**Rationale**: Additive — no existing key removed. Sensitive keys remain
blocked by `SENSITIVE_CONTEXT_KEYS` regardless. Required for spec scenario
*Context carries identifiers and state but no payload*.

## Data Flow

```
                    ┌─────────────────────────────────────────────┐
                    │  routers/mqtt.py                            │
                    │  POST/PUT /mqtt/mappings[/{id}/...]         │
                    │  deps: get_pg_db (Session) + Request        │
                    └────────────────┬────────────────────────────┘
                                     │ db, request, payload, current_user
                                     ▼
              ┌──────────────────────────────────────────────────────┐
              │  services/mqtt_mapping_service.py                   │
              │                                                      │
              │  1. _enforce_manage_with_audit(...)                  │
              │       └─ if denied: record_critical_change(         │
              │              outcome="DENIED",                       │
              │              event_type="MQTT_MAPPING_<ACT>")  ──┐   │
              │       └─ then require_mqtt_permission() raises    │   │
              │                                                    │   │
              │  2. previous_state = self._repo.get_mapping(...)    │   │
              │  3. try:                                            │   │
              │        result = self._repo.<mutation>(...)         │   │
              │     except:                                         │   │
              │        record_critical_change(VALIDATION_FAILURE) ──┤   │
              │        raise                                        │   │
              │  4. record_critical_change(                         │   │
              │         outcome="SUCCESS", event_type=...,          │   │
              │         context={...state, ids, version,            │   │
              │                    changed_fields?})             ──┤   │
              │  5. return result                                   │   │
              └────────────────────────────────────┬───────────────┘   │
                                                   │                   │
                                                   ▼                   ▼
                              ┌────────────────────────────┐  ┌─────────────────────────┐
                              │ repos/mqtt_mapping_repo.py│  │ services/audit_service.py│
                              │ Neo4j (mapping state)     │  │ Postgres audit_events    │
                              │                            │  │ (sanitize_context       │
                              │                            │  │  → _persist_event       │
                              │                            │  │  swallow + warn)        │
                              └────────────────────────────┘  └─────────────────────────┘
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/services/audit_service.py` | Modify | Extend `AUDIT_CONTEXT_ALLOWED_KEYS` with 9 mapping keys. No other change. |
| `backend/services/mqtt_mapping_service.py` | Modify | Add `db: Session`, `request: Request \| None` to 5 mutation signatures. Add private `_enforce_manage_with_audit` helper. Insert audit emission (denied/validation/success) at 5 sites. Add pre-read in `approve_mapping` and `revoke_mapping`. Import `services.audit_service`, `services.auth_service` permission value, `Request` from FastAPI, `Session` from SQLAlchemy. |
| `backend/routers/mqtt.py` | Modify | Add `request: Request` and `db: Session` deps; pass them into `service.create_mapping / update_mapping / approve_mapping / revoke_mapping / update_thresholds`. |
| `backend/tests/test_mqtt_mapping_service.py` | Modify | Existing 8 tests must keep passing unchanged (signatures widened, behaviour unchanged on existing paths). New tests for emission. |
| `backend/tests/test_audit_service.py` | Modify | New tests for allow-list membership, redaction survival, and persistence of mapping context. |

No DB migration; `audit_events` schema (`backend/models/audit_event.py`) is
unchanged.

## Interfaces / Contracts

```python
# backend/services/mqtt_mapping_service.py

EVENT_TYPE_CREATE          = "MQTT_MAPPING_CREATE"
EVENT_TYPE_UPDATE          = "MQTT_MAPPING_UPDATE"
EVENT_TYPE_APPROVE         = "MQTT_MAPPING_APPROVE"
EVENT_TYPE_REVOKE          = "MQTT_MAPPING_REVOKE"
EVENT_TYPE_THRESHOLD_UPDATE = "MQTT_MAPPING_THRESHOLD_UPDATE"

OUTCOME_SUCCESS            = "SUCCESS"
OUTCOME_VALIDATION_FAILURE = "VALIDATION_FAILURE"
OUTCOME_DENIED             = "DENIED"

TARGET_TYPE_MQTT_MAPPING   = "mqtt_mapping"
AUDIT_SOURCE               = "mqtt_mapping"

def _enforce_manage_with_audit(
    *, current_user, db, request, mapping_id, event_type
) -> None: ...

class MqttMappingService:
    def create_mapping(
        self, payload, current_user, *, db: Session, request: Request | None = None
    ) -> dict: ...
    def update_mapping(
        self, mapping_id, payload, current_user, *, db: Session, request: Request | None = None
    ) -> dict: ...
    def approve_mapping(
        self, mapping_id, current_user, *, db: Session, request: Request | None = None
    ) -> dict: ...
    def revoke_mapping(
        self, mapping_id, current_user, *, db: Session, request: Request | None = None
    ) -> dict: ...
    def update_thresholds(
        self, mapping_id, thresholds, current_user, *, db: Session, request: Request | None = None
    ) -> dict: ...
    # list_mappings, get_thresholds unchanged (no audit emission for reads)
```

### Audit row shape (per success/validation/denied row)

```python
AuditEvent(
    event_type   = "MQTT_MAPPING_<ACTION>",
    outcome      = "SUCCESS" | "DENIED" | "VALIDATION_FAILURE",
    target_type  = "mqtt_mapping",
    target_id    = mapping_id,            # str(uuid4) for create, repo id for others
    target_label = mapping_id,
    source       = "mqtt_mapping",
    actor_username = current_user.username,
    actor_role   = current_user.role,
    context = {
        # present when allow-listed by AUDIT_CONTEXT_ALLOWED_KEYS:
        "mapping_id", "source_device_id", "source_metric_id",
        "target_ci_id", "target_metric_def_id",
        "previous_state", "next_state", "version",
        "changed_fields": [...]   # update + threshold_update only
        "required_permission": "MQTT_MAPPING_MANAGE"   # denial only
    },
    reason = "ci_saved"-style tag, e.g. "mapping_created" / "mapping_denied"
)
```

`changed_fields` for `update_mapping` is computed by comparing
`payload.dict(exclude_unset=True)` against the pre-read mapping:
`source_metric_name`, `target_ci_id`, `target_metric_def_id`, `warning`,
`critical`, `operator`. For `update_thresholds`, the three threshold keys.

## Sensitive-Field Exclusion

Two layers, both already present:

1. `AUDIT_CONTEXT_ALLOWED_KEYS` whitelist — service only emits the 9 mapping
   keys + `required_permission` (already in allow-list).
2. `sanitize_context` strips `SENSITIVE_CONTEXT_KEYS` (token, cookie, body,
   raw_body, authorization, password, refresh_token, request_body,
   session_token) and truncates any string value > 256 chars.

The service **never** receives the MQTT payload body or HTTP request body
(the FastAPI router validates payloads and passes typed models), so secret
material is not even available to audit emission. The spec's
*Sensitive payload keys never persist in mapping context* scenario is
defensively covered by a RED test that constructs a context dict containing
every key in `SENSITIVE_CONTEXT_KEYS` and asserts none persist.

## Emission-Failure Isolation

Rely on the existing `_persist_event` swallow-and-warn behavior
(`audit_service.py:159-168`). Audit emission is a **fire-and-forget side
effect** that runs after the repo mutation returns a value (for success) or
inside the `except` block (for validation failure). The mutation result is
returned to the router regardless of audit outcome; the user-facing HTTP
response is unaffected.

For denial, emission happens before `raise HTTPException`; if `_persist_event`
swallows the failure, the 403 is still raised with the standard detail string.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit (`test_audit_service.py`) | New allow-list keys pass sanitization; `body`/`token`/`cookie`/`password`/`authorization`/`refresh_token`/`raw_body`/`session_token`/`request_body` are stripped from a mapping context. | SQLite in-memory; reuse `_Request` fixture pattern. |
| Unit (`test_mqtt_mapping_service.py`) | Each of 5 lifecycle methods emits exactly one row. Success path carries `outcome=SUCCESS`, correct `event_type`, `target_type=mqtt_mapping`, `previous_state`/`next_state`/`version`. Denied path carries `outcome=DENIED`, `event_type=MQTT_MAPPING_<ACT>`, `required_permission=MQTT_MAPPING_MANAGE`. Validation-failure path (404/409) carries `outcome=VALIDATION_FAILURE`. | Mock `services.audit_service.record_critical_change` (existing pattern in `test_routers_nodes.py`, `test_routers_auth_users_roles.py`); extend `_RepoStub` to assert pre-read happens for approve/revoke. |
| Unit (`test_mqtt_mapping_service.py`) | Lifecycle mutation succeeds when `record_critical_change` raises (defensive: covers `_persist_event`'s swallow-and-warn contract at the service layer too). | Stub `record_critical_change` to `raise RuntimeError("audit down")`; assert service returns repo result / raises HTTPException normally. |
| Integration (manual / CI) | `GET /api/audit/events?target_type=mqtt_mapping&target_id=<id>` returns the 5-row history ordered by `created_at`. | Use FastAPI TestClient + real Postgres test DB. |

Existing 8 tests in `test_mqtt_mapping_service.py` keep passing because the
new `db` / `request` params are keyword-only with `request=None` default,
and emission paths are added without removing existing logic.

## Threat Matrix

The change does **not** touch routing, shell, subprocess, VCS/PR automation,
executable-file classification, or process integration. The applicable
boundary is **sensitive data in audit context**.

| Row | Boundary | Applicable? | Expected behavior | Planned RED test |
|-----|----------|-------------|-------------------|------------------|
| 1 | Secret/credential leakage to audit | Yes (explicit spec scenario) | `sanitize_context` strips every key in `SENSITIVE_CONTEXT_KEYS`; allow-list only carries 9 mapping keys + `required_permission`. None of `body`, `token`, `cookie`, `password`, `authorization`, `refresh_token`, `raw_body`, `request_body`, `session_token` persist. | `test_mapping_context_strips_every_sensitive_key`: build context dict with all 9 sensitive keys, call `record_critical_change(event_type="MQTT_MAPPING_CREATE", target_type="mqtt_mapping", context=...)`, assert none of the forbidden tokens appear in stored `context`. |
| 2 | Payload body capture | Yes (spec: *Context carries identifiers and state but no payload*) | Service signature only receives `MqttMappingCreateRequest`/`UpdateRequest`/`Thresholds` — typed models without a raw body field. `_safe_scalar` truncates any string > 256 chars. | `test_mapping_context_rejects_payload_body`: include `"body": "raw mqtt payload..."` and `"raw_body": {...}` in context; assert both stripped, no fragment of payload string appears in stored row. |
| 3 | PII / `source_topic` exposure | Yes (source_device_id and source_metric_id are identifiers, not PII, but enforce care) | Context only carries the id forms (`source_device_id`, `source_metric_id`); never `source_topic`, never `username`-level PII. Truncation at 256 chars prevents accidental oversize. | `test_mapping_context_caps_value_length`: include `"source_topic": "x" * 1000`; assert it is stripped (not on allow-list) AND any string field is truncated to ≤256 chars. |
| 4 | Denied-event-type generalization risk (spec-flagged concern) | Yes (spec calls this out: `record_denied` hardcodes `ACCESS_DENIED`) | Lifecycle denials emit with `event_type=MQTT_MAPPING_<ACT>` (NOT `ACCESS_DENIED`) and `outcome=DENIED`, by calling `record_critical_change` directly. The `record_denied` helper is left untouched for other callers. | `test_denied_create_uses_lifecycle_event_type`: assert `record_critical_change.call_args.kwargs["event_type"] == "MQTT_MAPPING_CREATE"` and `kwargs["outcome"] == "DENIED"`; assert `record_denied` is NOT called. Repeat for all 5 actions. |

Explicit **N/A** rows: routing — unchanged; shell/subprocess — none;
VCS/PR automation — none; executable-file classification — none;
process-integration — none.

## Migration / Rollout

No migration. Backward compatible:
- Allow-list is additive.
- New `db` / `request` parameters are keyword-only on the service.
- Existing 8 unit tests stay green.

Rollout is the standard merge → deploy → observe path. No feature flag.

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Audit emission blocks user-facing mutation if DB is slow | Low | `_persist_event` already does a single short-lived commit; runs after the Neo4j mutation returns. Worst case: a slow Postgres commits the audit row before the HTTP response returns — acceptable, mirrors CI/role audit behavior. |
| Lifecycle audit rows grow retention cost | Low | ~600 B/row × ≤5 rows per mapping lifecycle; existing 90-day window already absorbs this. |
| New service signature breaks the `test_mqtt_router.py` call surface | Low | Router endpoints are updated to pass `db` and `request`; existing router tests (`test_mqtt_router.py:181 test_create_mapping_uses_mapping_service`) mock the service and won't see the new kwargs. |
| Outcome casing mismatch with spec | Medium (documented) | Use uppercase to match `AuditOutcome` Literal; flagged in *Open Questions* for spec reconciliation. |
| `record_denied` continues to be the right answer for non-MQTT denials | N/A | Decision explicitly does NOT touch `record_denied`. Other callers (`users`, `roles`, `nodes`, `backup`) keep current behavior. |

## Open Questions

- [ ] **Outcome casing**: spec text uses lowercase (`success`, `validation_failure`, `denied`); codebase convention is uppercase to satisfy `routers/audit.py:21 AuditOutcome` Literal. Behavior uses uppercase. Does the spec author want the spec text aligned, or do they accept the casing deviation?
- [ ] **`source_topic` in mapping row**: currently not in the allow-list. Should `source_topic` ever be exposed to the audit log? (Current design says no — it's an operational secret.)
- [ ] **`changed_fields` for `update_mapping` when payload uses defaults**: `exclude_unset=True` correctly excludes omitted fields, but Pydantic `MqttMappingUpdateRequest` may apply defaults. Confirm with author which fields can actually change.

## Next Step

Ready for `sdd-tasks`. Each task will be sized to fit the 400-line PR review
budget; total expected change is ~300 lines backend (allow-list + 5 emission
sites + tests), no migration, no frontend.