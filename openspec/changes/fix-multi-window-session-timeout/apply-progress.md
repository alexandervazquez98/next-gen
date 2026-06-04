# Apply Progress — PR1 / Backend policy schema foundation

Scope: `fix-multi-window-session-timeout` (Issue #188) — **PR1 only**.

## Status

- PR selection: **Only PR1** (backend policy/schema foundation), in line with user instruction.
- Delivery model: `single-pr` exception accepted by user.
- **Reviewer recommendations addressed in this continuation:**
  - legacy-row migration backfill and non-null alignment
  - explicit profile-driven cookie expiry assertions
  - refresh-session_id continuity on refresh rotation

## Completed in PR1

### Added

- `backend/services/session_policy.py`
- `backend/tests/test_session_policy.py`

### Updated

- `backend/services/auth_service.py`
  - `create_refresh_token` now accepts optional `policy` and `session_id`.
  - Uses policy to set token expiry and stores session-policy metadata.
- `backend/models/refresh_token.py`
  - Added session-policy columns: `session_id`, `policy_profile`, `last_activity_at`, `rotated_at`, `replaced_by_token_id`, `revoked_reason`, `stale_recovery_count`.
- `backend/routers/auth.py`
  - Resolves session policy at login/refresh.
  - Applies policy-aware cookie max-age values.
- `backend/main.py`
  - Added `_ensure_refresh_token_schema_migration` and startup call for additive column/index migration.
- `backend/tests/test_auth_service_refresh.py`
  - Policy metadata persistence tests for standard/operational profiles.
- `backend/tests/test_auth_router_refresh.py`
  - Login cookie assertions were strengthened to verify environment-driven profile-based `refresh_token` `Max-Age` in both standard and operational policies.
- `openspec/changes/fix-multi-window-session-timeout/tasks.md`
  - Marked PR1 task steps 1–5 as complete.

## Verification (Strict-TDD evidence)

### TDD Cycle Evidence

| Phase | Evidence |
| --- | --- |
| RED | Added/updated PR1 tests first in:
`backend/tests/test_session_policy.py`,
`backend/tests/test_auth_service.py`,
`backend/tests/test_auth_service_refresh.py`,
`backend/tests/test_auth_router_refresh.py`.
New access-token continuity/protocol claims were first asserted in:
`test_auth_router_refresh.py::test_login_access_token_includes_session_and_profile_claims` and `test_auth_router_refresh.py::test_refresh_includes_session_claim_continuity_and_profile`.
Also added `test_auth_service.py::test_token_includes_session_and_profile_claims`.
| GREEN | Implemented code changes to include `sid` + `profile` in access token payloads and preserve `sid` continuity during refresh in:
- `backend/routers/auth.py`.
- `backend/services/auth_service.py` already persisted session/policy metadata for refresh tokens (from PR1).
| TRIANGULATE | Repeated focused matrix check using:
- `python -m pytest backend/tests/test_session_policy.py`\
- `python -m pytest backend/tests/test_auth_service.py`\
- `python -m pytest backend/tests/test_auth_service_refresh.py`\
- `python -m pytest backend/tests/test_auth_router_refresh.py`
| REFACTOR | Kept PR1 scope to backend-only and backward-compatible payload shape (`sub` and `role` preserved). |

### Focused proof command (evidence)

- `cd backend && python -m pytest tests/test_session_policy.py tests/test_auth_service_refresh.py tests/test_auth_router_refresh.py`
  - **Result:** **47 passed**.
- `cd backend && python -m pytest tests/test_auth_service.py`
  - **Result:** **26 passed**.

### Additional verification

- `python -m pytest backend/tests/test_routers_auth_users_roles.py`
  - **Result:** 3 failures due pre-existing/environmental DB/runtime issues (`psycopg2` hstore OID unpack and unrelated roles test payload enum/string assumptions), plus dependent auth path DB bootstrap. Not introduced by PR1 policy changes.
- `python -m pytest`
  - **Result:** existing known suite-level failure in `backend/scripts/test_single_ci_reconcile.py` (`ModuleNotFoundError: No module named 'database'`) observed as before.

## Deviations from design

- Startup migration is implemented as a minimal additive DDL guard in `main.py` and now backfills existing rows (`session_id`, `policy_profile`, `last_activity_at`, `stale_recovery_count`) to align model non-null expectations.
- PR1 is intentionally backend-only; no frontend token-orchestration/inactivity UX work included.

## Remaining work (PR2–PR4)

- PR2: stale-token recovery state machine, rotation edge cases, and recoverable/terminal refresh statuses.
- PR3: API contract decisions for policy visibility to frontend.
- PR4: frontend single-flight refresh, cross-tab coordination, and inactivity behavior.

### PR1-specific follow-up before verify handoff

- Update `test_auth_service_refresh.py` now includes session metadata regression coverage for `verify_refresh_token(..., include_session_metadata=True)`.
- `routers/auth.py` now threads prior token lineage (`session_id`) into new refresh token creation.
- Open follow-up: validate startup migration behavior in a real PostgreSQL instance for backfilled legacy rows (especially `CONCAT`/`NOW()` SQL compatibility).

## Workload boundary

- Kept PR1 edits within the requested slice to minimize change size; backend/auth contract foundation only.