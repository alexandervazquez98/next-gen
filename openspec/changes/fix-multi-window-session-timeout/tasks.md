# Tasks — fix-multi-window-session-timeout (Issue #188)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 650–1,050 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 -> PR 2 -> PR 3 -> PR 4 |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

## Slice dependencies

- PR 1 must merge before PR 2 (backend policy and schema are prerequisites for stale-recovery logic).
- PR 2 must merge before PR 3/4 (frontend must align with backend refresh contract details).
- PR 3 and PR 4 can be parallelized after PR 2, but PR 4 should wait for PR 3 if it introduces shared cross-tab session utilities.
- PR 4 includes optional UX inactivity timers that can be feature-flagged or deferred if product wants a phased rollout.

## PR 1 — Backend: session-policy resolution + refresh/session baseline (highly test-first)

**Scope:** `backend/services/session_policy.py`, `backend/services/auth_service.py`, `backend/models/refresh_token.py`, `backend/routers/auth.py`, `backend/models/sql_models.py` (if needed), `backend/main.py` migration guard, `backend/tests/test_session_policy.py` (new), `backend/tests/test_auth_service_refresh.py`, `backend/tests/test_auth_router_refresh.py`.

1. **[x] Add policy-config and resolver test coverage**
   - Create `backend/tests/test_session_policy.py`.
   - Add tests for:
     - operational role/user allowlist mapping
     - missing/invalid profile fallbacks to standard
     - explicit config disabling of operational profiles
     - policy values returned for standard role/profile.
   - Use explicit env patching and user fixtures from `backend/tests/conftest.py`.
   - **Verify:** run targeted tests only and confirm failures prior to implementation.
   - **Rollback boundary:** no code changes yet; remove only this test file if this slice is deferred.

2. **[x] Add session policy module + env-config contract**
   - Add `backend/services/session_policy.py` with `SessionPolicy` + resolution helpers and pure parse of:
     - `SESSION_OPERATIONAL_ENABLED`
     - `SESSION_OPERATIONAL_ROLES`
     - `SESSION_OPERATIONAL_USERS`
     - standard/operational duration knobs from `design.md`.
   - Export deterministic `SessionPolicy` values for `operational` vs `standard`.
   - **Verify:** unit-test module directly or via the new `test_session_policy.py` tests.
   - **Rollback boundary:** revert module + callsites if policy semantics cause regressions.

3. **[x] Extend refresh-token persistence model and migration safety path**
   - Update `backend/models/refresh_token.py` schema fields to include:
     - `session_id`, `policy_profile`, `last_activity_at`, `rotated_at`, `replaced_by_token_id`, `revoked_reason`, `stale_recovery_count` (and make `expires_at` nullable or configurable sentinel-safe).
   - Add/adjust indexes/uniques where needed for `session_id` and `token_hash` access paths.
   - Update startup migration in `backend/main.py` using safe `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for `refresh_tokens` fields (no dedicated migration framework is used today).
   - **Verify:**
     - Backend startup creates/updates without failure in empty DB path and existing DB path.
     - Manual schema check (psql) confirms fields.
   - **Rollback boundary:** remove migration lines in startup and keep model fields untouched.

4. **[x] Update token creation path to emit profile/session metadata at login**
   - Update `backend/services/auth_service.py:create_refresh_token` (and related helpers) to accept resolved policy + user and persist metadata (`session_id`, `policy_profile`, `last_activity_at`).
   - Update `backend/services/auth_service.py:get_current_user` to read and preserve `role` and policy-relevant claims when converting DB user to pydantic `UserInDB`.
   - Update `backend/routers/auth.py:/token` to:
     - resolve policy
     - create both access + refresh tokens
     - set refresh cookie.
   - Ensure access token max-age still comes from policy/`ACCESS_TOKEN_EXPIRE_MINUTES`.
   - **Verify:** augment/extend `backend/tests/test_auth_router_refresh.py::TestAuthTokenCookie` and `TestAuthTokenCookie` variants for refresh-cookie presence and session metadata on login.
   - **Rollback boundary:** limit to request cookie behavior only; keep old auth path as fallback by reverting resolver wiring.

5. **[x] Backend policy integration verification**
   - Run:
     - `cd backend && python -m pytest backend/tests/test_session_policy.py backend/tests/test_auth_service_refresh.py backend/tests/test_auth_router_refresh.py`
     - `cd backend && python -m pytest`
   - Confirm no breakage in `backend/tests/test_routers_auth_users_roles.py`.
   - **Rollback boundary:** if failures are wide, drop PR 1 and re-open policy semantics as pure helper first.

## PR 2 — Backend: refresh contention tolerance + stale-rotation/rate-limit behavior

**Scope:** `backend/models/refresh_token.py`, `backend/services/auth_service.py`, `backend/routers/auth.py`, `backend/middleware/rate_limit.py`, `backend/tests/test_auth_service_refresh.py`, `backend/tests/test_auth_router_refresh.py`, `backend/tests/test_rate_limit.py`.

6. **[x] Add stale-rotation and terminal-state tests**
   - Extend `backend/tests/test_auth_service_refresh.py`:
     - recently rotated token returns recoverable status
     - stale token beyond grace is rejected
     - idle-timeout path marks session invalid for non-operational policy.
   - Extend `backend/tests/test_auth_router_refresh.py`:
     - concurrent stale refresh does not lock token race across window semantics
     - recoverable stale refresh returns success + set cookies
     - terminal session states return deterministic error details (`session_expired`/`idle_timeout`/`session_revoked`) and clear cookies.
   - Extend/adjust `test_rate_limit` if threshold/count changes are introduced for stale recovery.
   - **Verify:** tests fail before code changes.

7. **[x] Replace boolean refresh verification with status result object**
   - Add structured status model in `backend/models/refresh_token.py` or `backend/services/auth_service.py` (e.g., enum + `RefreshVerificationResult`).
   - Update `verify_refresh_token` to return terminal/recoverable distinctions:
     - `VALID`, `MISSING`, `EXPIRED`, `IDLE_EXPIRED`, `REVOKED`, `ROTATED_STALE_RECOVERABLE`, `ROTATED_STALE_REJECTED`, `USER_INACTIVE`.
   - Return `should_count_rate_limit` flag and token/session identifiers for deterministic handling.
   - **Verify:** add focused unit assertions in service tests.

8. **[x] Implement stale-recovery and refresh rotation logic**
   - Update `backend/services/auth_service.py`:
     - `rotate_refresh_token`
     - `recover_from_stale_rotation`
     - policy re-resolution on refresh
     - optional audit hook calls (if audit path exists).
   - Update `backend/routers/auth.py` refresh handler:
     - do not count recoverable stale races toward rate limit
     - rotate/reissue cookies for recoverable overlap
     - enforce terminal statuses and lockout only after sustained abusive behavior.
   - Keep single-use rotation safety for valid rotation paths.
   - **Verify:** add/extend endpoint tests for `429` and `401` edge cases after recoverability updates.

9. **[x] Rate-limit contract tests and verification**
   - Adjust `backend/middleware/rate_limit.py` integration points only if needed to preserve token hash keying and namespace semantics.
   - Confirm old raw-token leakage does not occur (`identity_key` remains hashed in DB rows).
   - **Verify:** run subset:
     - `cd backend && python -m pytest backend/tests/test_rate_limit.py backend/tests/test_auth_router_refresh.py backend/tests/test_auth_service_refresh.py`
   - **Rollback boundary:** if abuse protection regresses, revert to pre-slice behavior and isolate stale-recovery as opt-in with feature gate.

10. **[x] Hardening pass for determinism and naming**
    - Consolidate duplicated expiry/rotation constants into policy config reads.
    - Ensure error details emitted by refresh endpoint are stable (`session_expired`, `idle_timeout`, `session_revoked`, etc.).
    - **Verify:** execute full backend test suite.

## PR 3 — Backend frontend-contract bridge for inactivity state (optional API metadata + helpers)

**Scope:** `backend/services/auth_service.py`, `backend/routers/auth.py`, `backend/models/user.py`, `backend/tests/test_routers_auth_users_roles.py`.

11. **[RED] Add tests for session-policy visibility to frontend**
   - Add or extend tests for `/auth/users/me` response to include optional `session_policy`/`idle_timeout_minutes` (if/when endpoint schema includes it) and verify operational users are not forcibly timed out.

12. **[GREEN] Expose minimal policy metadata (if required for UX)**
   - Option A (preferred): include policy fields in `/auth/users/me` response while retaining pydantic compatibility.
   - Option B: keep API unchanged and infer operational profile in frontend conservatively; add comment contract if using B.
   - Update AuthContext integration expectations in docs/tests accordingly.
   - **Verify:** modify/extend `backend/tests/test_routers_auth_users_roles.py` and run auth-related backend tests.

13. **[TRIANGULATE/REFACTOR] Choose and lock API contract**
   - Confirm with frontend task owner whether metadata is required in this issue cycle.
   - Finalize one stable contract to avoid churn in PR 4.

## PR 4 — Frontend: singleflight + bounded refresh + cross-tab + inactivity UX

**Scope:** `frontend/services/api.ts`, `frontend/context/AuthContext.tsx`, `frontend/services/sessionBus.ts` (new), `frontend/App.tsx` (optional), `frontend/services/api.test.ts`, `frontend/context/AuthContext.test.tsx`, new tests for cross-tab behavior.

14. **[RED] Add strict client-side refresh orchestration tests**
   - Extend `frontend/services/api.test.ts`:
     - parallel 401 requests coalesce into a single refresh call
     - each failed original request retries at most once
     - bounded retry limit stops repeated refresh calls and triggers logout once.
   - Add test for SSE behavior: refresh failures do not redirect but surface error.
   - **Verify:** tests fail before code edits.

15. **[GREEN] Add per-tab refresh singleflight + bounded retry metadata**
   - Update `frontend/services/api.ts` with module-level in-flight refresh promise.
   - Add internal request metadata (`skipAuthRefresh`, `authRetryCount`, max attempts).
   - Prevent repeated refresh for `/auth/refresh` and recursive refresh loops.
   - Add centralized redirect helper to avoid duplicate login redirects.
   - **Verify:** run API tests + targeted Vitest.

16. **[GREEN] Add cross-tab session coordination channel**
   - Add `frontend/services/sessionBus.ts` using `BroadcastChannel` with `localStorage` fallback.
   - On refresh success/failure/logout/session-expired broadcast `session-expired` and `logout` reasons; guard duplicates with sender/session IDs.
   - Wire `frontend/context/AuthContext.tsx` subscription: clear local user state and optionally navigate once on session-expired.
   - **Verify:** add tests for channel preference/fallback and AuthContext reaction tests.

17. **[GREEN] Inactivity UX for non-operational sessions**
   - Extend AuthContext user shape (or use `/auth/users/me` metadata) to track `session_policy`.
   - Add activity listeners + timer for non-operational users only.
   - On local idle timeout:
     - call `/auth/logout` best effort
     - clear local auth state
     - broadcast session-expired.
   - Ensure operational users are not armed for inactivity timer unless policy changed.
   - **Verify:** add/extend `frontend/context/AuthContext.test.tsx` for policy-aware behavior.

18. **[TRIANGULATE] Full frontend verification and manual cross-tab checks**
   - Run:
     - `cd frontend && corepack pnpm test:run`
   - Manual checks (if browser-level cross-tab lock behavior not fully unit-testable):
     - two tabs near token expiry should converge without lockout
     - non-operational user idles past timeout and transitions to login in both tabs.

## Migration/schema risks (to track before PR merge)

- Missing migration framework means schema drift risk is higher:
  - add null-friendly columns first to avoid outage on existing rows.
  - consider explicit startup guard migration queries in `backend/main.py` or one-time DBA SQL.
- New indexes for `refresh_tokens.session_id`/`policy_profile` should be added as schema-safe operations and validated on PostgreSQL-only deployment.
- Any long-lived operational token behavior must not reduce security: verify revocation path is complete for session id and user profile change.

### Suggested DB validation commands (manual, when deploying)
- Verify columns:
  - `psql "$POSTGRES_URL" -c "\d refresh_tokens"`
  - `psql "$POSTGRES_URL" -c "SELECT column_name FROM information_schema.columns WHERE table_name='refresh_tokens' ORDER BY column_name;"`
- Quick behavior sanity:
  - call `/api/auth/token` then `/api/auth/refresh` in two browser tabs with same refresh token; assert no immediate lockout on stale overlap.

## Risks & rollback notes

- **High-risk change:** backend refresh semantics; isolate by PR and keep feature-safe defaults.
- **Rollback PR strategy:** each PR should be independently revertible by reverting only changed files in that slice.
- **Operational misclassification risk:** default to non-operational when policy config missing or invalid.

## Summary of strict-TDD workflow

All slices are staged as: **RED → GREEN → TRIANGULATE → REFACTOR** with per-slice test gates before moving forward.
