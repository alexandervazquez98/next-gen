# Apply Progress: audit-user-logs — PR 2 Auth capture

## Session context
- Branch: `feat/audit-user-logs-auth`
- Scope: SDD change `audit-user-logs`
- Slice: **PR 2 — Auth capture**
- Working style: **strict TDD**

## TDD Cycle Evidence

| Phase | Evidence | Result |
|---|---|---|
| RED | Added failing auth lifecycle audit assertions in `backend/tests/test_routers_auth_users_roles.py` before production-side audit instrumentation/refinements. | Initial failures exposed patch-target mismatch and lockout-raise behavior gaps. |
| GREEN | Implemented `record_auth_event` calls in `backend/routers/auth.py` for login failure/denied/success and logout; targeted auth router suite passes. | `53 passed`. |
| TRIANGULATE | Added mixed success/failure regression, direct pre-check rate-limit coverage, threshold lockout coverage, inactive-user coverage, logout coverage, and sensitive-context assertions. | Edge branches covered for PR2 auth capture. |
| REFACTOR | Centralized auth audit event/outcome/reason constants in `backend/routers/auth.py` and reused them from tests. | Duplication reduced without broadening PR2 scope. |

### RED
- Added auth lifecycle assertions in `backend/tests/test_routers_auth_users_roles.py` for:
  - wrong credentials audit failure
  - lockout branch audit denial
  - inactive user audit denial
  - login success audit emission
  - mixed success/failure regression
  - logout audit emission
- Initial test pass (before production-side refinements) exposed failures due test patching target mismatch and lockout-raise behavior.

### GREEN
- Implemented auth request instrumentation in `backend/routers/auth.py`:
  - injected `Request` into `/api/auth/token` and `/api/logout` handlers
  - added `record_auth_event` calls for:
    - wrong credentials (`LOGIN_FAILURE`, `FAILURE`)
    - locked/rate-limited branch (`LOGIN_FAILURE`, `DENIED`)
    - inactive user (`LOGIN_FAILURE`, `DENIED`)
    - successful login (`LOGIN_SUCCESS`, `SUCCESS`)
    - logout (`LOGOUT`, `SUCCESS`)
  - added standardized auth constants for outcomes/events/reasons.
- Targeted command: `cd backend && python -m pytest tests/test_routers_auth_users_roles.py` => **53 passed**.

### TRIANGULATE
- Added regression test for mixed success/failure sequence in the same test file to ensure event outcomes remain correct per flow.
- Added explicit assertions that no sensitive keys (`password`, `token`, `raw_body`) are passed through audit context.
- Added focused direct pre-check rate-limit coverage and request-context assertions so audit calls receive `Request` data needed for IP/user-agent/request-id enrichment.

### REFACTOR
- Centralized auth outcomes/reasons in `backend/routers/auth.py` constants and reused them in tests.
- Kept PR2 scope limited to auth capture only; no PR3/PR4/PR5 files modified.

## Validation Command(s)
- `cd .worktrees/audit-user-logs-auth/backend && python -m pytest tests/test_routers_auth_users_roles.py` **(pass: 53/53)**

## Changed files
- `backend/routers/auth.py`
- `backend/tests/test_routers_auth_users_roles.py`
- `openspec/changes/audit-user-logs/tasks.md`
- `openspec/changes/audit-user-logs/apply-progress.md`

## Completed tasks (PR2)
- PR2 auth checklist items 1–6 marked complete in tasks:
  1. Extend auth test coverage for auth lifecycle
  2. Inject `Request` and call `record_auth_event` in auth/login/logout
  3. Emit audit on denied/failure branches before exceptions
  4. Emit success/failure with standardized reasons
  5. Triangulation mixed-outcome regression
  6. Refactor constants for outcomes/reasons

## Remaining tasks
- PR3+ scopes remain unchecked and unchanged.

## Fresh review follow-up
- Fresh reviewer found no blockers.
- Addressed minor review feedback by adding request-context assertions for audit enrichment and direct pre-check rate-limit denied coverage.
