# Apply Progress: audit-user-logs — PR3B-2 (Backup-only, after PR3B-1)

## Session context
- Branch: `feat/audit-user-logs-nodes-backup` (base `ada9d38`)
- Scope: `audit-user-logs` (OpenSpec)
- Slice: **PR3B-2 backup-only** (after PR3B-1)
- Working style: **strict TDD**
- Review/line budget: kept near/under review-safe threshold for this slice

## TDD Cycle Evidence

| Phase | Evidence | Result |
|---|---|---|
| RED (PR3A-1 baseline) | Added user audit tests in `backend/tests/test_routers_auth_users_roles.py` and implemented users-only roles from earlier slice. | PR3A-1 accepted. |
| GREEN (PR3A-1 baseline) | Implemented users-only instrumentation in `backend/routers/users.py` and validated (`54` passed). | Users baseline verified. |
| RED (PR3A-2) | Added focused role-mutation assertions for success/denied/failure branches in `backend/tests/test_routers_auth_users_roles.py` for create/update/delete role endpoints. | Added targeted expectations and updated mocks for `record_denied` + `record_critical_change`. |
| GREEN (PR3A-2) | Implemented role endpoint audit calls in `backend/routers/roles.py` with denied/success/validation branches for create/update/delete. | Scoped roles-only test file + router code changed and ready for verify. |
| TRIANGULATE (PR3A-2) | Added endpoint coverage across allowed role mutation slices: create/update/delete, covering success + forbidden + duplicate/not-found/system-role/in-use validation branches without broadening scope to nodes/backup/frontend. | Behavior spans multiple outcome classes with minimal diff. |
| REFACTOR (PR3A-2) | No major refactor required; kept changes localized to `roles.py` and role test section in `test_routers_auth_users_roles.py`. | Completed. |

## Completed implementation
- Added/updated role-mutator test assertions in `backend/tests/test_routers_auth_users_roles.py`:
  - `POST /api/roles/` (`ROLE_CREATE`): success + duplicate + forbidden
  - `PUT /api/roles/{name}` (`ROLE_UPDATE`): success + forbidden + system-role/validation/not-found
  - `DELETE /api/roles/{name}` (`ROLE_DELETE`): success + forbidden + system-role/not-found/assigned-users
- Added audit capture in `backend/routers/roles.py`:
  - `POST /api/roles/` (`ROLE_CREATE`) with denied + validation-failure + success `record_*` calls
  - `PUT /api/roles/{name}` (`ROLE_UPDATE`) with denied + validation-failure + success `record_*` calls
  - `DELETE /api/roles/{name}` (`ROLE_DELETE`) with denied + validation-failure + success `record_*` calls
  - validation-failure reasons and allow-listed context include changed fields + required permission
- Kept scope to roles-only mutator paths; no nodes/backup/frontend behavior changed.

## Verification
- Command: `cd .worktrees/audit-user-logs-roles/backend && python -m pytest tests/test_routers_auth_users_roles.py`
- Result: **55 passed**.

## Persisted task updates
- `openspec/changes/audit-user-logs/tasks.md` updated:
  - Added completed PR3A-1 users-only and PR3A-2 roles-only test/instrumentation bullets as `- [x]`.
  - Kept broader PR3 nodes/backup/frontend and PR4/PR5 items pending for later slices.

## Files changed
- `backend/routers/backup.py`
- `backend/tests/test_backup_router.py`
- `openspec/changes/audit-user-logs/tasks.md`
- `openspec/changes/audit-user-logs/apply-progress.md`

## Remaining tasks
- PR4 frontend + optional CI-adjacent slices still pending:
  - `frontend/components/AuditLogPage.test.tsx`
  - `frontend/components/AuditLogPage.tsx`
  - `backend/tests/test_routers_catalog.py`
  - `backend/tests/test_routers_links.py`

## PR boundary / workload
- This is **PR3B-2 (backup-only)** atop PR3B-1.
- Scope constrained to `backup.py` and `test_backup_router.py`.
- Reviewable size maintained for this work unit.

## Fresh review follow-up
- Scope now includes backup-only after PR3B-1 nodes coverage.
- Risk handled: explicit payload validation and allow-listed audit context were added before success path; backup re-scheduling remains untouched behaviorally.
- Added validation-failure capture for invalid payload values with actor/target attribution.
- Current acceptance scope confirms contract for this slice, while PR4/PR5 remain out-of-scope in this PR.


## PR3B-1 (nodes-only) implementation progress
- Scope: nodes mutators only (`POST /api/nodes`, `DELETE /api/nodes/{node_id}`, `PUT /api/nodes/{node_id}/metadata`).
- RED: Added failing-path and success-path audit assertions for nodes mutator endpoints before/with implementation.
- GREEN: Implemented audit capture in `backend/routers/nodes.py` for denied/success/validation outcomes.
- TRIANGULATE: Added mixed outcomes across create, delete, metadata mutator tests, and AI metadata field-restriction validation audit after fresh review.
- REFACTOR: Consolidated audit recording through `nodes.py` helper functions and kept slice confined to nodes router/tests.
- Verification: `cd backend && python -m pytest tests/test_routers_nodes.py` -> **39 passed**.
- Remaining: PR3B-2 backup slice (`backend/routers/backup.py`, `backend/tests/test_backup_router.py`) and PR4/PR5 continue.


## PR3B-2 (backup-only) implementation progress
- Scope: `PUT /api/backup/config` only.
- RED: Added focused `backend/tests/test_backup_router.py` cases for denied, validation-failure, and success outcomes on backup config update before implementation.
- GREEN: Implemented `backend/routers/backup.py` with `SYSTEM_CONFIG_UPDATE` audit capture for:
  - `DENIED` outcome before admin-only refusal via `record_denied`
  - `VALIDATION_FAILURE` outcome for invalid `schedule_type` / `retention_days` payloads
  - `SUCCESS` outcome when update succeeds
- TRIANGULATE: Added mixed outcome assertions on allow-listed context (`changed_fields`, `required_permission`) in router-level tests.
- REFACTOR: Added local payload validation helper to keep route logic explicit and minimize audit-path branching.
- Verification (PR3B-2): `cd backend && python -m pytest tests/test_backup_router.py` -> **14 passed**.

## PR4 — Frontend audit table + permission-gated access

- Branch: `feat/audit-user-logs-frontend` (base `e8f2bfc`)
- Scope: frontend only (`frontend` audit table, route, nav, permission pickers, PR4 tests).

### TDD Cycle Evidence

| Phase | Evidence | Result |
|---|---|---|
| RED | Added `frontend/components/AuditLogPage.test.tsx` for access denied, filter controls, query params, columns, placeholders, empty-state, and 403 fallback before/with implementation. | Targeted frontend tests covered required PR4 behavior. |
| GREEN | Added `frontend/components/AuditLogPage.tsx`, wired `/audit` route/nav item, and updated role/user permission catalogs for `AUDIT_VIEW`. | Targeted and full frontend suites pass. |
| TRIANGULATE | Added empty-result and 403 fallback negative assertions in `AuditLogPage.test.tsx`. | Denied/empty/error cases covered beyond happy-path table rendering. |
| REFACTOR | Normalized API params (`page_size` clamp to 100 and ISO datetime serialization). | Query serialization stays aligned with backend API contract. |

### Verification (PR4)
- `corepack pnpm --dir frontend run test:run` ✅ (44 files, 421 tests)

## Task reconciliation / de-scope

- **PR3 stale parent task**: reconciled in planning by marking user/role broad RED task as complete; scope was intentionally split across PR3A-1 (users-only) and PR3A-2 (roles-only), both completed and verified.
- **Shared helper refactor** (`backend/services/audit_service.py`): explicitly de-scoped for first-slice delivery. Context shaping is currently explicit in router-level code; this refactor is non-functional churn and was deferred as optional technical debt cleanup.
- **PR5 optional CI-adjacent scope**: formally de-scoped for first release. Optional catalog/links/dictionaries capture is not part of current audit-log slice and remains a future optional PR subject to product scope.
- **Archive readiness**: no product code/test changes were made in this task; only OpenSpec planning artifacts were updated to make archive intent explicit.
