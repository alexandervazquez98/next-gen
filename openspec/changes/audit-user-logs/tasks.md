# Tasks: Dedicated User Audit Logging (`audit-user-logs`)

Implement with strict TDD, sliced by review-safe PRs.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,100–1,700 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 Foundation → PR 2 Auth capture → PR 3 Critical changes capture → PR 4 Frontend table → PR 5 optional CI-adjacent completion |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

## PR 1 — Foundation (model/service/API + RBAC + retention)

**Estimated changed lines:** ~260–520 (Medium risk)

**Start state:** No dedicated `audit_events` schema, no `AUDIT_VIEW` permission, no `/api/audit/events` endpoint, no retention cleanup job.

**Finish state:** Foundation endpoint is functional and permission-gated, schema + service exists, retention cleanup path exists and is test-covered.

- [x] **RED:** Add failing tests in `backend/tests/test_audit_service.py` for
   - schema version defaults, required fields, and event metadata contract;
   - sensitive-field exclusion (`password`, tokens, raw body) from stored context;
   - retention cleanup removing rows older than 90 days and preserving newer rows.
- [x] **RED:** Add failing tests in `backend/tests/test_audit_router.py` for
   - `GET /api/audit/events` filtering by time actor/event_type/outcome;
   - `403` for missing `AUDIT_VIEW`;
   - pagination and sort semantics (page/page_size/sort).
- [x] Add SQLAlchemy model `backend/models/audit_event.py` with fields/indexes per design (`schema_version`, `event_type`, `outcome`, target/context, `created_at`, request metadata).
- [x] Export `AuditEvent` in `backend/models/__init__.py`.
- [x] Add DTO/schemas in `backend/models/audit.py` or colocated in `backend/routers/audit.py` (consistent with current model style).
- [x] Add `backend/services/audit_service.py` with helpers:
   - `build_request_context(request)`
   - `record_auth_event(...)`
   - `record_critical_change(...)`
   - `record_denied(...)`
   - `cleanup_old_events(db, retention_days=90, now=None)`
- [x] Add router `backend/routers/audit.py` with `GET /api/audit/events` query params (`start_time`, `end_time`, `actor`, `event_type`, `outcome`, `target_type`, `page`, `page_size`, `sort`).
- [x] Wire router in `backend/main.py` (`from routers import audit` + `app.include_router(audit.router, prefix="/api")`).
- [x] Add `UserPermission.AUDIT_VIEW` in `backend/models/user.py` and validate it through existing `UserPermission` flows (`backend/routers/roles.py` allow-list uses enum).
- [x] Schedule `audit_service.cleanup_old_events(..., retention_days=90)` in startup via existing APScheduler lifecycle in `backend/main.py` (parallel to backup scheduling).
- [x] Add focused bootstrap/seed expectation if needed in `backend/seed_roles.py`/`backend/seed_admin.py` so existing default seed logic still exposes `AUDIT_VIEW` consistently.
- [x] **TRIANGULATE:** Add targeted edge cases in `backend/tests/test_audit_service.py`/`backend/tests/test_audit_router.py` for invalid filters, denied requests, and timezone-safe date boundary behavior.
- [x] **REFACTOR:** Consolidate any duplicated request-context extraction or failure-reason constants in `backend/services/audit_service.py`.

**PR 1 validation (backend):** `cd backend && python -m pytest tests/test_audit_service.py tests/test_audit_router.py`

**Acceptance mapping:**
- Requirement: Audit event schema persistence + redaction.
- Requirement: Filterable audit API.
- Requirement: `AUDIT_VIEW` API access control.
- Requirement: 90-day retention cleanup.

**Rollback:** Stop including the new router in `main.py` and remove scheduler registration; model and service can be removed without touching domain mutators.

---

## PR 2 — Auth capture

**Estimated changed lines:** ~120–260 (Medium risk)

**Start state:** Foundation in place; auth flow has no user audit instrumentation.

**Finish state:** `LOGIN_SUCCESS`, `LOGIN_FAILURE`, and `LOGOUT` events are emitted with safe context.

- [x] **RED:** Extend `backend/tests/test_routers_auth_users_roles.py` with auth-lifecycle cases asserting audit side-effects for:
   - wrong credentials (`LOGIN_FAILURE`, safe reason, IP/UA present)
   - inactive user (`LOGIN_FAILURE`, `DENIED`)
   - lockout branch on repeated attempts (`LOGIN_FAILURE`, `DENIED`)
   - successful token login (`LOGIN_SUCCESS`)
   - successful logout (`LOGOUT`)
   - no raw password/token persisted in calls.
- [x] In `backend/routers/auth.py`, inject `Request` into `login_for_access_token` and `logout` and call `audit_service.record_auth_event(...)` at each lifecycle branch.
- [x] Ensure denied/failure branches emit audit before exception is raised so denied outcomes are captured for retry/lockout paths.
- [x] Ensure success path records `LOGIN_SUCCESS` and failure paths record standardized safe reasons, while avoiding request payload persistence.
- [x] **TRIANGULATE:** Add regression in `backend/tests/test_routers_auth_users_roles.py` for mixed outcomes (success + failure) to guard false positives.
- [x] **REFACTOR:** Centralize outcome/reason constants used by auth tests + router for consistency.

**PR 2 validation (backend):** `cd backend && python -m pytest tests/test_routers_auth_users_roles.py`

**Acceptance mapping:**
- Requirement: Authentication lifecycle event capture.
- Requirement: Schema redaction for sensitive auth payload fields.

**Rollback:** Keep `AUDIT_VIEW` and foundation in PR1; remove auth hooks only.

---

## PR 3 — Critical change capture (users/roles/CI/config)

**Estimated changed lines:** ~350–650 (High risk; target near but ideally <400)

**Start state:** Foundation + auth instrumentation complete; critical domain endpoints currently uninstrumented.

**Finish state:** Critical create/update/delete attempts and outcomes are emitted as audit events for users, roles, CI core operations, and backup config.

### PR3 slice/line-gate

If this PR is projected to exceed ~400 changed lines, split by moving **users/roles** into a standalone PR scope and **CI/core + system-config** into follow-up PR within the same PR3 boundary.

- **3A Users + Roles capture (preferred if split):** keep in one PR.
- **3B CI core + `backup.config` capture (remaining):** second PR if split is needed.

- [ ] **RED:** Extend `backend/tests/test_routers_auth_users_roles.py` with user/role success, denied, and failure-path expectations for audit calls/events:
   - `POST /api/users/`, `PUT /api/users/{username}`, `DELETE /api/users/{username}`, `POST /api/users/{username}/reset`
   - `POST /api/roles/`, `PUT /api/roles/{name}`, `DELETE /api/roles/{name}`
   - denied attempts before `403` and validation attempts where actionable.
- [x] **RED (PR3A-1 users-only):** Added minimal targeted assertions for user mutating endpoints in `backend/tests/test_routers_auth_users_roles.py` for success, denied, and validation/failure branches:
   - `USER_CREATE` success + duplicate username + forbidden
   - `USER_UPDATE` success + not found + forbidden
   - `USER_DELETE` success + not found + forbidden
   - `USER_PASSWORD_RESET` success + forbidden
- [x] **RED (PR3A-2 roles-only):** Extended `backend/tests/test_routers_auth_users_roles.py` for role mutator success, denied, and failure-path expectations:
   - `ROLE_CREATE` success + duplicate + forbidden
   - `ROLE_UPDATE` success + system-role guard + not found + forbidden
   - `ROLE_DELETE` success + not found + system-role/role-assignment failures + forbidden
- [x] **RED:** In `backend/routers/roles.py`, added audit calls for role mutator denied/success/failure paths:
   - `ROLE_CREATE`, `ROLE_UPDATE`, `ROLE_DELETE` on create/update/delete endpoints.
- [ ] **RED:** Extend `backend/tests/test_routers_nodes.py` with audit assertions for:
   - `POST /api/nodes` (create/update path)
   - `DELETE /api/nodes/{node_id}`
   - `PUT /api/nodes/{node_id}/metadata`
   - denied-path and validation-failure branches where possible.
- [ ] **RED:** Extend `backend/tests/test_backup_router.py` with `PUT /api/backup/config` denied and success assertions.
- [x] In `backend/routers/users.py`, add audit calls around each mutating action:
   - denied-path capture before permission `HTTPException` (`DENIED`)
   - success-path captures with `event_type` (`USER_CREATE`, `USER_UPDATE`, `USER_DELETE`, `USER_PASSWORD_RESET`)
- [x] In `backend/routers/users.py` (PR3A-1 users-only), added user mutating endpoint audit calls for denied + `VALIDATION_FAILURE` + success paths on:
   - `POST /api/users/`
   - `PUT /api/users/{username}`
   - `DELETE /api/users/{username}`
   - `POST /api/users/{username}/reset`
- [x] In `backend/routers/roles.py`, add the same denied/success capture pattern:
   - `ROLE_CREATE`, `ROLE_UPDATE`, `ROLE_DELETE` with changed permission names in allow-listed context where needed.
- [ ] In `backend/routers/nodes.py`, add critical CI mutator capture at router boundary:
   - `POST /nodes`, `DELETE /nodes/{node_id}`, `PUT /nodes/{node_id}/metadata`.
   - event naming per design (`CI_CREATE_OR_UPDATE`, `CI_DELETE`, `CI_UPDATE_METADATA`) with safe target fields.
- [ ] In `backend/routers/backup.py`, add capture for `PUT /api/backup/config` (`SYSTEM_CONFIG_UPDATE`) and denied attempt capture before admin-only refusal.
- [ ] **TRIANGULATE:** Add/adjust tests for denied + validation outcomes (`DENIED` vs `VALIDATION_FAILURE`) for each domain capture.
- [ ] **REFACTOR:** Extract a small shared helper in `backend/services/audit_service.py` for standard target/context shaping used across nodes/users/roles/backup.

**PR 3 validation (backend):**
- `cd backend && python -m pytest tests/test_routers_auth_users_roles.py`
- `cd backend && python -m pytest tests/test_routers_nodes.py tests/test_backup_router.py`

**Acceptance mapping:**
- Requirement: Critical change capture and denied attempts.
- Requirement: Filterable events contain valid actor/target/outcome fields.

**Rollback:** Remove mutator hooks in affected routers and keep PR1+PR2 safe; `AUDIT_VIEW` remains unaffected.

---

## PR 4 — Frontend audit table + permission-gated access

**Estimated changed lines:** ~260–420 (High risk at budget boundary, but likely manageable)

**Start state:** Backend audit API exists; frontend has no audit surface.

**Finish state:** `AUDIT_VIEW`-gated audit route + table present and filters server-side.

- [ ] **RED:** Add `frontend/components/AuditLogPage.test.tsx` asserting:
   - unauthorized state renders access denied for missing permission;
   - filter controls render and query API is called with params;
   - table columns include actor, event type, target, timestamp, outcome, IP/context, source;
   - placeholders used for intentionally missing values.
- [ ] **RED:** Update `frontend/components/RoleManager.test.tsx` to include `AUDIT_VIEW` in permission picker assertions and round-trip selection.
- [ ] Add `frontend/components/AuditLogPage.tsx` with:
   - controlled filter inputs for actor/event type/outcome/time range/page/page size/sort;
   - server-side data fetch via `/api/audit/events`;
   - 403 handling and safe placeholder rendering.
- [ ] Add route + nav visibility in `frontend/App.tsx`:
   - route: `/audit` -> `AuditLogPage`
   - nav item visible to `hasPermission("AUDIT_VIEW") || hasPermission("ADMIN")`
- [ ] Add minimal query utility in `frontend/services/auditQueries.ts` (if component-level fetch becomes noisy), otherwise keep request logic in component.
- [ ] Add/update `frontend/components/UserManager.tsx` and `frontend/components/RoleManager.tsx` permission option lists to include `AUDIT_VIEW`.
- [ ] **TRIANGULATE:** Add negative filter cases in `frontend/components/AuditLogPage.test.tsx` (empty result, out-of-range page, invalid actor/time)
- [ ] **REFACTOR:** Normalize date serialization and parameter naming to match API contract (`page_size` max 100).

**PR 4 validation (frontend):** `corepack pnpm --dir frontend run test:run`

**Acceptance mapping:**
- Requirement: Filterable audit table behavior (front-end)
- Requirement: `AUDIT_VIEW` route/UI access control.

**Rollback:** Remove/disable `/audit` route and nav item.

---

## PR 5 — Optional CI-adjacent completion (if in-scope)

**Estimated changed lines:** ~120–320 (Medium)

**Purpose:** Capture remaining CI-adjacent critical mutations only if product scope confirms they are required in first release.

- [ ] **RED:** Add tests for each CI-adjacent router selected for inclusion:
   - `backend/tests/test_routers_catalog.py`
   - `backend/tests/test_routers_links.py`
   - `backend/tests/test_routers_dictionaries.py` (if present)
- [ ] Add capture hooks in:
   - `backend/routers/catalog.py` (`/categories`, `/hardware` mutators)
   - `backend/routers/links.py` (link mutation endpoints)
   - `backend/routers/dictionaries.py` (mutators) as approved in-scope.
- [ ] Preserve PR3 event semantics (`DENIED`/`VALIDATION_FAILURE`/`SUCCESS`) and keep context allow-listed.
- [ ] Validate only added paths do not regress existing router behavior; run targeted backend command.

**PR 5 validation (backend):** `cd backend && python -m pytest tests/test_routers_catalog.py tests/test_routers_links.py`

**Acceptance mapping:**
- Requirement: First-slice critical change definition closure.

**Rollback:** De-scope remaining CI-adjacent capture without touching PR1–PR4 core behavior.
