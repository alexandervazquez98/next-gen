# Apply Progress: audit-user-logs — PR3A-2 (Roles-only)

## Session context
- Branch: `feat/audit-user-logs-roles` (base `1f0e31a`)
- Scope: `audit-user-logs` (OpenSpec)
- Slice: **PR3A-2 roles-only** (no users/nodes/backup/frontend changes; users baseline from PR3A-1 retained)
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
- `backend/routers/roles.py`
- `backend/tests/test_routers_auth_users_roles.py`
- `openspec/changes/audit-user-logs/tasks.md`
- `openspec/changes/audit-user-logs/apply-progress.md`

## Remaining tasks
- PR3 nodes/backup scope still pending:
  - `backend/tests/test_routers_nodes.py`
  - `backend/tests/test_backup_router.py`
  - `backend/routers/nodes.py`
  - `backend/routers/backup.py`
- PR4 frontend + optional CI-adjacent slices still pending:
  - `frontend/components/AuditLogPage.test.tsx`
  - `frontend/components/AuditLogPage.tsx`
  - `backend/tests/test_routers_catalog.py`
  - `backend/tests/test_routers_links.py`

## PR boundary / workload
- This is **PR3A-2 (roles-only)** atop PR3A-1.
- No non-role/mutations files modified beyond `users.py`-adjacent test module already touched in prior slice.
- Scope constrained to stay reviewable.

## Fresh review follow-up
- Scope remains roles-only and aligned with prior user-role sequencing.
- Notable implementation risk handled: role mutator audit calls use request-level DB session via `Depends(get_pg_db)` to keep existing audit persistence behavior consistent.
- Added validation-failure audit assertions for invalid permission create/update branches after fresh review.
- Current acceptance scope confirms contract for this slice, while PR3B/PR4 remain explicitly out-of-scope in this PR.


## PR3B-1 (nodes-only) implementation progress
- Scope: nodes mutators only (`POST /api/nodes`, `DELETE /api/nodes/{node_id}`, `PUT /api/nodes/{node_id}/metadata`).
- RED: Added failing-path and success-path audit assertions for nodes mutator endpoints before/with implementation.
- GREEN: Implemented audit capture in `backend/routers/nodes.py` for denied/success/validation outcomes.
- TRIANGULATE: Added mixed outcomes across create, delete, metadata mutator tests, and AI metadata field-restriction validation audit after fresh review.
- REFACTOR: Consolidated audit recording through `nodes.py` helper functions and kept slice confined to nodes router/tests.
- Verification: `cd backend && python -m pytest tests/test_routers_nodes.py` -> **39 passed**.
- Remaining: PR3B-2 backup slice (`backend/routers/backup.py`, `backend/tests/test_backup_router.py`) and PR4/PR5 continue.
