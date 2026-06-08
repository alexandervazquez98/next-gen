# Design: Dedicated User Audit Logging

Add a PostgreSQL-backed audit event store, a small centralized audit service, `AUDIT_VIEW` RBAC, an `/api/audit/events` query API, and a permission-gated frontend audit table. The first implementation should land as a foundation PR plus small domain-wiring PRs so each review stays under the 400 changed-line budget.

## Current codebase findings

| Area | Finding | Design implication |
|---|---|---|
| Backend routing | FastAPI routers are registered in `backend/main.py` with `/api` prefix. | Add `backend/routers/audit.py` and include it in `main.py` as `/api/audit/...`. |
| Persistence | PostgreSQL uses SQLAlchemy `Base.metadata.create_all(bind=engine)` at startup; users/rate limits/refresh tokens live under `backend/models`. | Add a SQLAlchemy `AuditEvent` model and import it during startup so the table is created. If production later requires formal migrations, this table can become the migration seed. |
| RBAC | `UserPermission` enum is in `backend/models/user.py`; `check_permission()` grants all permissions to `ADMIN`; role validation allow-list is in `backend/routers/roles.py`; frontend has hard-coded permission lists in role/user managers. | Add `AUDIT_VIEW` to backend enum, role validation, seed roles/admin, and frontend permission pickers. |
| Auth capture | `backend/routers/auth.py` handles `/auth/token`, `/auth/logout`, `/auth/refresh`; login currently lacks `Request` injection. | Inject `Request` where audit metadata is needed; capture login success/failure and logout only in first slice. Refresh-token auditing remains out of scope unless added later. |
| CI capture | CI CRUD is mainly `backend/routers/nodes.py` delegating to `services.node_service`; catalog/dictionary/relationship endpoints also mutate CI-related data. | First CI-critical PR should wire `/nodes` create/update/delete and optionally metadata updates; follow-up PRs can wire catalog/links/dictionary if they exceed review budget. |
| User/role capture | `backend/routers/users.py` and `backend/routers/roles.py` own users and roles/permissions. | Wire audit at router boundary after permission checks and around service/repository calls. |
| Critical system config | Backup schedule/config mutation is in `backend/routers/backup.py` and is admin-only. | Treat `PUT /backup/config` as the first critical system configuration event. |
| Frontend | Routes live in `frontend/App.tsx`; auth helper `hasPermission()` is in `frontend/context/AuthContext.tsx`; API wrapper is `frontend/services/api.ts`. | Add an `AuditLogPage` route/nav item gated by `AUDIT_VIEW` and use `api.get()` with query parameters. |

## Data model

Store audit events in PostgreSQL because it already backs user/auth state and supports indexed filter queries.

### SQLAlchemy table: `audit_events`

Recommended file: `backend/models/audit_event.py`.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | Internal stable identifier. |
| `schema_version` | integer, default `1`, not null | Required by spec; bump only for breaking/major schema changes. |
| `event_type` | string, indexed, not null | Examples: `LOGIN_SUCCESS`, `LOGIN_FAILURE`, `LOGOUT`, `CI_CREATE`, `USER_UPDATE`, `ROLE_DELETE`, `PERMISSION_UPDATE`, `SYSTEM_CONFIG_UPDATE`. |
| `outcome` | string, indexed, not null | `SUCCESS`, `DENIED`, `VALIDATION_FAILURE`, `FAILURE`. |
| `actor_username` | string nullable, indexed | Username when known; for failed login it may be the submitted username after normalization, not proof of identity. |
| `actor_role` | string nullable | Current role if authenticated. |
| `target_type` | string nullable, indexed | `auth`, `ci`, `user`, `role`, `permission`, `system_config`. |
| `target_id` | string nullable, indexed | CI id, username, role name, config key, etc. |
| `target_label` | string nullable | Human-readable label/name. |
| `source` | string nullable | Route/module source such as `auth`, `nodes`, `users`, `roles`, `backup`. |
| `ip_address` | string nullable | Derived from request client/forwarded header per existing deployment trust rules. |
| `user_agent` | string nullable | Header value truncated to a safe length. |
| `reason` | string nullable | Safe failure/denial reason only; no secrets or raw bodies. |
| `context` | JSON/JSONB nullable | Allow-listed metadata only, e.g. changed field names, route, method, request id. |
| `created_at` | UTC datetime, indexed, not null | Server-side event timestamp. |

Indexes:
- `created_at DESC` for default table sort and retention cleanup.
- Composite indexes for common filters: `(created_at, event_type)`, `(created_at, outcome)`, `(created_at, actor_username)`.
- Optional `(target_type, target_id, created_at)` for incident investigation.

Do not store request bodies, passwords, token values/hashes, cookies, Authorization headers, or arbitrary form payloads.

## API contract

Add `backend/routers/audit.py`.

### `GET /api/audit/events`

Requires `AUDIT_VIEW` via `check_permission(UserPermission.AUDIT_VIEW, current_user)`.

Query parameters:
- `start_time?: datetime` inclusive.
- `end_time?: datetime` inclusive.
- `actor?: string` exact username match initially.
- `event_type?: string` exact event type; allow repeated values only if implementation stays small, otherwise one value in first slice.
- `outcome?: SUCCESS|DENIED|VALIDATION_FAILURE|FAILURE`.
- `target_type?: string` optional but useful for UI.
- `page: int = 1`, `page_size: int = 50`, max `100`.
- `sort: created_at_desc|created_at_asc = created_at_desc`.

Response:

```json
{
  "items": [
    {
      "id": 123,
      "schema_version": 1,
      "event_type": "LOGIN_FAILURE",
      "outcome": "FAILURE",
      "actor_username": "alice",
      "target_type": "auth",
      "target_id": "alice",
      "target_label": "alice",
      "source": "auth",
      "ip_address": "203.0.113.10",
      "user_agent": "Mozilla/5.0 ...",
      "reason": "incorrect_credentials",
      "context": { "route": "/api/auth/token" },
      "created_at": "2026-06-07T12:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 50
}
```

Invalid filters return `422`/FastAPI validation errors. Missing permission returns `403` and no audit rows.

## Centralized event emission pattern

Recommended files:
- `backend/services/audit_service.py`
- `backend/models/audit.py` for Pydantic request/response DTOs, or DTOs co-located in `routers/audit.py` if smaller.

Service responsibilities:
1. Normalize event fields and apply defaults (`schema_version=1`, UTC timestamp, source).
2. Extract safe request metadata from `Request` via `build_request_context(request)`.
3. Provide typed helpers:
   - `record_auth_event(db, request, event_type, outcome, actor_username=None, reason=None)`
   - `record_critical_change(db, request, actor, event_type, outcome, target_type, target_id, target_label=None, reason=None, context=None)`
   - `record_denied(db, request, actor, required_permission, target_type, target_id, reason)`
4. Truncate free-text fields and allow-list context keys.
5. Commit audit rows independently but safely: audit write failures are logged and MUST NOT expose secrets or break successful business operations unless a future compliance mode requires fail-closed behavior.

Pattern at router boundary:

```python
if not check_permission(UserPermission.CI_EDIT, current_user):
    audit_service.record_denied(..., reason="missing_permission:CI_EDIT")
    raise HTTPException(status_code=403, detail="Permission denied: CI_EDIT required")

try:
    result = node_service.create_update_node(node, current_user)
except ValidationErrorLike as exc:
    audit_service.record_critical_change(..., outcome="VALIDATION_FAILURE", reason=safe_reason(exc))
    raise

audit_service.record_critical_change(..., outcome="SUCCESS")
return result
```

This avoids ad-hoc table writes while keeping instrumentation close to the operations where actor, target, and outcome are known.

## Capture points

### Auth lifecycle

File: `backend/routers/auth.py`.

- `POST /auth/token`
  - Add `request: Request` parameter.
  - Before wrong-password/missing-user `401`: record `LOGIN_FAILURE`, `outcome=FAILURE`, `actor_username=form_data.username`, `target_type=auth`, `reason=incorrect_credentials`.
  - Before inactive-user `400`: record `LOGIN_FAILURE`, `outcome=DENIED`, `reason=inactive_user`.
  - When rate-limit lock is triggered: record `LOGIN_FAILURE`, `outcome=DENIED`, `reason=rate_limited` before raising `429` where practical.
  - After password verification and before/after token creation: record `LOGIN_SUCCESS`, `outcome=SUCCESS`.
- `POST /auth/logout`
  - Add `request: Request` and record `LOGOUT`, `outcome=SUCCESS` after refresh tokens are revoked/cookies cleared.

Do not audit raw `form_data.password`, refresh/access token cookies, or request body.

### Critical changes

First PR should wire the most central, high-value endpoints. Follow-up PRs wire remaining domains if budget grows.

| Domain | Endpoints | Events |
|---|---|---|
| CIs | `POST /nodes`, `DELETE /nodes/{node_id}`, `PUT /nodes/{node_id}/metadata` | `CI_CREATE_OR_UPDATE` initially, `CI_DELETE`, `CI_UPDATE_METADATA`; if service can cheaply distinguish create vs update, split into `CI_CREATE` and `CI_UPDATE`. |
| Users | `POST /users/`, `PUT /users/{username}`, `DELETE /users/{username}`, `POST /users/{username}/reset` | `USER_CREATE`, `USER_UPDATE`, `USER_DELETE`, `USER_PASSWORD_RESET`. Do not record submitted/reset password. |
| Roles/permissions | `POST /roles/`, `PUT /roles/{name}`, `DELETE /roles/{name}` | `ROLE_CREATE`, `ROLE_UPDATE`, `ROLE_DELETE`; include changed permission names in allow-listed context, not whole request body. |
| Critical system config | `PUT /backup/config` | `SYSTEM_CONFIG_UPDATE` with changed config field names and safe values only where non-sensitive. Avoid `storage_path` if considered sensitive in deployment. |
| CI-related catalog/links/dictionaries | category/hardware/owner/relationship/dictionary mutations | Follow-up PRs if `/nodes` + user/role/system config already approach the budget. |

Denied attempts are captured immediately before existing `403` raises. Validation failures are captured around service/repository exceptions where handler code sees an attributable actor and target.

## Retention strategy

Add `audit_service.cleanup_old_events(db, retention_days=90, now=None) -> int`.

- Deletes rows with `created_at < now - 90 days`.
- Scheduled daily during `startup_event()` using the existing APScheduler lifecycle in `backend/main.py` or a dedicated audit scheduler job registered alongside backup scheduling.
- Expose no public deletion endpoint in the first slice.
- Include tests for boundary behavior: older than 90 days is deleted; exactly/newer than 90 days remains.

Operational note: because startup currently uses `Base.metadata.create_all`, the first implementation can create the table automatically in dev/test. Production rollout should confirm whether a migration script is needed for deployed databases.

## Frontend route, table, and query design

Recommended files:
- `frontend/components/AuditLogPage.tsx`
- Optional `frontend/services/auditQueries.ts` if keeping API calls out of the component is consistent with future query reuse.
- `frontend/App.tsx` for route/nav wiring.
- `frontend/components/RoleManager.tsx` and `frontend/components/UserManager.tsx` for `AUDIT_VIEW` permission selection.

Route:
- Add `audit` route under `MainLayout`: `<Route path="audit" element={<AuditLogPage />} />`.
- Add nav item only if `hasPermission("AUDIT_VIEW") || hasPermission("ADMIN")`.
- Inside `AuditLogPage`, render an access denied state if permission is absent to protect direct route access.

Filters:
- Date/time range (`start_time`, `end_time`).
- Actor text input.
- Event type select/text.
- Outcome select.
- Page/page size controls.
- Sort defaults to newest first.

Table columns:
- Timestamp.
- Actor.
- Event type.
- Target (`target_type` + `target_label || target_id`).
- Outcome.
- IP/context (`ip_address`, compact user-agent/context display).
- Source.

UI behavior:
- Server-side filtering/pagination only; do not fetch all rows for client filtering.
- Render em dash/`Not captured` for intentionally omitted fields; never show `undefined`/empty raw placeholders.
- On `403`, display a short access denied message rather than row data.

## Tests and strict TDD plan

`openspec/config.yaml` has `sdd.strict_tdd: true`; apply phase should show RED/GREEN evidence before completion.

### Backend RED tests first

Add tests before implementation, expected to fail:
- `backend/tests/test_audit_service.py`
  - redacts/never persists sensitive keys.
  - persists versioned schema fields.
  - cleanup deletes only rows older than 90 days.
- `backend/tests/test_audit_router.py`
  - `AUDIT_VIEW` user can query events with filters.
  - non-`AUDIT_VIEW` user receives `403` and no rows.
  - combined filters return only matching rows.
- Extend auth/user/role/node tests or add focused tests:
  - login failure stores IP, user agent, safe reason, no password.
  - login success/logout stores events.
  - denied critical change stores `DENIED` event.
  - successful user/role/CI/config change stores `SUCCESS` event.

Command:

```bash
cd backend
python -m pytest tests/test_audit_service.py tests/test_audit_router.py tests/test_routers_auth_users_roles.py
```

### Frontend RED tests first

Add tests before implementation, expected to fail:
- `frontend/components/AuditLogPage.test.tsx`
  - renders filters and table columns for `AUDIT_VIEW` user.
  - calls `/api/audit/events` with selected query params.
  - renders access denied for non-permitted user.
  - displays safe placeholders for omitted fields.
- Update `RoleManager.test.tsx`/`UserManager` tests for `AUDIT_VIEW` permission options if coverage already asserts permission lists.

Command:

```bash
corepack pnpm --dir frontend run test:run
```

### GREEN evidence expectations

For every PR in this chain, include:
- Failing test output or named failing tests from RED step.
- Passing backend command for changed backend slice.
- Passing frontend command for changed frontend slice.
- OpenSpec acceptance mapping in PR notes.

## Security and privacy safeguards

- Hard deny API/UI read access without `AUDIT_VIEW`; `ADMIN` remains allowed through existing `check_permission()` semantics.
- Do not record passwords, access tokens, refresh tokens, cookies, Authorization headers, raw request bodies, uploaded files, or unbounded payloads.
- Use safe reason codes (`incorrect_credentials`, `inactive_user`, `missing_permission:CI_EDIT`, `validation_failed`) instead of exception strings that may include data.
- Truncate `user_agent`, `reason`, `target_label`, and context values.
- Context is allow-listed by event helper; never pass `model.dict()` wholesale.
- Audit write failure logs should not include sensitive input.
- UI must not expose audit route/nav to unauthorized users and must handle direct route denial.

## Rollout and rollback

Rollout:
1. Add table/model/service/API behind permission checks.
2. Add `AUDIT_VIEW` to enum, seed admin/system roles, and UI permission pickers.
3. Wire auth events first to validate schema and retention.
4. Wire critical domains in small PRs.
5. Add UI table once API contract is stable.

Rollback:
- Remove/hide frontend nav/route to stop UI exposure.
- Disable or unregister `audit.router` in `main.py` to stop API reads.
- Temporarily disable specific capture calls if a domain causes operational issues; keep auth capture as the minimum useful slice.
- Stop retention job if cleanup behaves unexpectedly; existing rows remain queryable until job is fixed.
- Table addition is additive; no existing business data depends on it.

## PR slicing forecast against 400-line review budget

Chained PRs are recommended because backend model/service/API + RBAC + multi-domain capture + UI table is likely over 400 changed lines.

```text
tracker: audit-user-logs
├─ PR 1 📍 Foundation: model, audit service, AUDIT_VIEW, query API, retention tests
├─ PR 2    Auth capture: login success/failure/logout + tests
├─ PR 3    Critical change capture: users/roles/permissions + CI core + backup config
├─ PR 4    Frontend audit table: route/nav/filterable table + permission picker updates
└─ PR 5    Optional domain completion: catalog/links/dictionary CI-related critical changes if not included in PR 3
```

| PR | Boundary | Estimated review risk | Notes |
|---|---|---:|---|
| 1 | `AuditEvent` SQLAlchemy model, Pydantic DTOs, `audit_service`, `/api/audit/events`, retention cleanup, `AUDIT_VIEW` enum/seed/frontend picker minimal if needed for tests | Medium | Foundation should be kept tight; avoid wiring all domains here. |
| 2 | Auth router instrumentation and auth tests | Low/Medium | Focused and high security value. |
| 3 | Users, roles/permissions, `/nodes` CI core, backup config capture | Medium/High | If line count nears 400, split users/roles from CI/system config. |
| 4 | `AuditLogPage`, route/nav, query params, UI tests | Medium | Keep styling simple; server-side pagination only. |
| 5 | Remaining CI-adjacent catalog/link/dictionary mutations | Optional | Only if product insists these are first-slice critical and PR 3 cannot fit. |

Preferred first PR: **foundation only**. It should end with a working, permission-gated API and retention cleanup, but no broad domain instrumentation except test fixtures. Follow-up PRs should wire event capture by domain so each PR remains reviewable and reversible.

## Open decisions for tasks/apply

- Whether production deployments require an explicit SQL migration instead of relying on `Base.metadata.create_all`.
- Exact event names for `/nodes` upsert: use `CI_CREATE_OR_UPDATE` initially unless `node_service` can distinguish create vs update cheaply.
- Which CI-adjacent catalog/link/dictionary mutations must be included before first release versus optional PR 5.
