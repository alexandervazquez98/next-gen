# Apply Progress: audit-user-logs — PR3A-1 (Users-only)

## Session context
- Branch: `feat/audit-user-logs-users-roles` (base `8943167`)
- Scope: `audit-user-logs` (OpenSpec)
- Slice: **PR3A-1 users-only** (no roles/nodes/backup/frontend, no non-user files)
- Working style: **strict TDD**
- Review/line budget: kept under ~400 changed lines and PR3A-1 boundary

## TDD Cycle Evidence

| Phase | Evidence | Result |
|---|---|---|
| RED (PR2 baseline) | Added auth lifecycle audit assertions in `backend/tests/test_routers_auth_users_roles.py` and validated auth capture in previous PR. | PR2 completed (`53` passed). |
| GREEN (PR2 baseline) | Implemented auth instrumentation in `backend/routers/auth.py` for lifecycle success/denied/failure cases. | PR2 previously verified (`53` passed). |
| TRIANGULATE (PR2 baseline) | Added mixed success/failure and denied-rate-limit regression coverage with context-safety checks. | PR2 accepted and merged. |
| REFACTOR (PR2 baseline) | Centralized auth outcomes/reasons and kept PR2 scope isolated. | Completed in prior PR artifact state. |
| RED (PR3A-1) | Added focused assertions in `backend/tests/test_routers_auth_users_roles.py` for user mutators: `USER_CREATE`, `USER_UPDATE`, `USER_DELETE`, and `USER_PASSWORD_RESET` success/denied/validation paths. | Initial targeted runs exposed missing handler audit branches and reset-password validation coverage gap. |
| GREEN (PR3A-1) | Implemented localized user-mutator audit capture in `backend/routers/users.py` with denied-path `record_denied`, validation-failure `record_critical_change`, and success `record_critical_change` for create/update/delete/reset endpoints. | Targeted users/auth/roles router suite passes. |
| TRIANGULATE (PR3A-1) | Added reset-password missing-body validation audit coverage after fresh review; preserved existing role/node/frontend tests and kept assertions minimal to avoid broad rewrites. | Branch coverage improved without broadening scope. |
| REFACTOR (PR3A-1) | No structural refactor required; inserted localized instrumentation + lightweight test assertions only. |

## Completed implementation
- Added/updated user-endpoint test assertions in `backend/tests/test_routers_auth_users_roles.py` for PR3A-1 scope.
- Added audit-event emission in `backend/routers/users.py` for:
  - `POST /api/users/` (`USER_CREATE`)
  - `PUT /api/users/{username}` (`USER_UPDATE`)
  - `DELETE /api/users/{username}` (`USER_DELETE`)
  - `POST /api/users/{username}/reset` (`USER_PASSWORD_RESET`)
- Scope bounded: no changes to roles/nodes/backup/frontend files.

## Verification
- Command: `cd .worktrees/audit-user-logs-users-roles/backend && python -m pytest tests/test_routers_auth_users_roles.py`
- Result: **54 passed**.

## Persisted task updates
- `openspec/changes/audit-user-logs/tasks.md` updated:
  - Added completed PR3A-1 users-only test coverage bullets as `- [x]`.
  - Added completed PR3A-1 users-only users.py instrumentation bullets as `- [x]`.
  - Kept broader PR3 roles/nodes/backup items pending.

## Files changed
- `backend/routers/users.py`
- `backend/tests/test_routers_auth_users_roles.py`
- `openspec/changes/audit-user-logs/tasks.md`
- `openspec/changes/audit-user-logs/apply-progress.md`

## Remaining tasks
- PR3 users + roles (roles still pending):
  - `backend/tests/test_routers_auth_users_roles.py` role mutation audits
  - `backend/routers/roles.py` role mutation audits
- PR3B CI/system scope still pending:
  - `backend/tests/test_routers_nodes.py`
  - `backend/tests/test_backup_router.py`
  - `backend/routers/nodes.py`
  - `backend/routers/backup.py`

## PR boundary / workload
- This is **PR3A-1 (Users-only)** only, as requested.
- No non-user scope files modified.
- Diff is within review-budget target.

## Fresh review follow-up
- Fresh reviewer found no blockers or majors and confirmed users-only scope.
- Addressed the minor reset-password validation coverage gap with `test_reset_password_missing_body_records_validation_audit`.
- Removed unused user-audit import/constant nits.
