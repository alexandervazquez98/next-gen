# Explore: issue #188 — fix(auth): handle multi-window sessions and activity-based timeout

## Relevant code paths (current)

### Backend

- `backend/routers/auth.py`
  - `POST /api/auth/token`: issues `access_token` + `refresh_token` cookies, fixed expiries set at cookie layer from constants.
  - `POST /api/auth/refresh`:
    - reads refresh token from cookie/body;
    - `check_rate_limit` then `verify_refresh_token`;
    - on success: `revoke_refresh_token` + create new access token + create new refresh token + set cookies.
- `backend/services/auth_service.py`
  - `ACCESS_TOKEN_EXPIRE_MINUTES = 15` hardcoded.
  - `create_refresh_token()` sets `expires_at = now + REFRESH_TOKEN_EXPIRE_DAYS`.
  - `verify_refresh_token()` validates token exists + not revoked + not expired.
  - `revoke_refresh_token()` and `revoke_all_user_refresh_tokens()`.
- `backend/models/refresh_token.py`
  - `RefreshToken` model: `token_hash`, `expires_at`, `revoked_at`; no activity tracking fields.
- `backend/middleware/rate_limit.py`
  - refresh-token keyed lockout after repeated failed refreshes.

### Frontend

- `frontend/services/api.ts`
  - request wrapper:
    - on 401: calls `/api/auth/refresh` then retries original request once;
    - on refresh failure: redirects to `/login` except SSE mode and throws `ApiError('Session expired', 401)`;
    - no in-flight refresh singleflight/queueing dedupe;
    - no cross-tab coordination.
- `frontend/context/AuthContext.tsx`
  - session hydrate on mount via `/auth/users/me`.
  - logout calls `/auth/logout` and clears in-memory user.
- `frontend/App.tsx`
  - inline `ProtectedRoute` redirects based on `isAuthenticated` + loading state.

## Existing tests found

### Backend auth/session tests

- `backend/tests/test_auth_service_refresh.py`
  - verify/create/revoke refresh token behavior.
- `backend/tests/test_auth_router_refresh.py`
  - refresh success, invalid refresh -> 401/429, rate-limit behavior, hashed keying.
- `backend/tests/test_routers_auth_users_roles.py`
  - login/token basics, `/users/me`, rate limit patterns.
- `backend/tests/test_rate_limit.py`
  - rate-limit primitives and lockout behavior.

### Frontend auth/session tests

- `frontend/services/api.test.ts`
  - request/headers parsing and one 401-refresh-failure redirect case; no concurrent refresh success-path tests.
- `frontend/context/AuthContext.test.tsx`
  - hydration/login/logout/user state.
- `frontend/components/ProtectedRoute.test.tsx`
  - protected route redirects.

## Actual failure modes to target

1. **Concurrent refresh race across windows/tabs**
   - Refresh flow is per-request and not coordinated.
   - If multiple tabs refresh with the same token simultaneously, one request can revoke the token while another verifies after revocation and fails.
   - The failed request can count in refresh rate-limit, potentially causing lockout for a legitimate user.
2. **Refresh-token rotation behaves as one-shot + lockout under contention**
   - Current verification has no distinct semantic for stale token already rotated by another tab.
   - Stale-token failures can trigger retry/lockout instead of graceful recovery.
3. **Fixed session timing, no inactivity semantics**
   - Access token expiry is hardcoded.
   - Refresh token expiry is fixed; no role/profile-aware or inactivity-aware policy.
4. **Frontend refresh retry storm risk**
   - No dedupe for in-flight `/auth/refresh`.
   - A burst of 401s can trigger repeated refresh calls and redirect churn.

## User clarification after explore

The session policy should support two base profiles:

- Operational profiles: designated NOC/SOC users need persistent/non-expiring sessions or tokens for 24/7 monitoring continuity.
- Non-operational users: use configurable policies, preferably inactivity-based timeout.

This means the change is not only a generic timeout fix; it must introduce role/profile-aware session policy.

## Suggested scope

- Backend:
  - Add configurable session policy resolution by user role/profile.
  - Support persistent operational NOC/SOC sessions with explicit logout/revocation/audit controls.
  - Support inactivity/configurable timeout for non-operational users.
  - Adjust refresh-token rotation/stale-token behavior so legitimate concurrent tab races do not trigger lockout.
- Frontend:
  - Add in-flight refresh singleflight per tab.
  - Add bounded retry/redirect behavior.
  - Add clean logout/inactivity behavior for non-operational users.
  - Consider cross-tab coordination for logout/session updates.
- Tests:
  - Backend tests for policy resolution, persistent operational sessions, non-operational inactivity expiry, concurrent/stale refresh behavior, and rate-limit handling.
  - Frontend tests for singleflight refresh, bounded retry, and clean logout.

## Candidate acceptance criteria

- NOC/SOC operational sessions remain valid for monitoring continuity unless explicitly logged out/revoked or disabled by admin policy.
- Non-operational sessions expire according to configurable inactivity/session policy.
- Concurrent refresh attempts from separate tabs do not trigger per-token lockout for valid sessions.
- Refresh retry behavior is bounded; a burst of 401s does not cause refresh storms or redirect loops.
- Inactivity expiry cleanly transitions UI to logged-out state and avoids token-refresh churn.

## Risks / open questions

- Need to preserve security of refresh-token rotation while tolerating stale-token races.
- Persistent operational sessions require strong explicit revocation and audit controls.
- Operational-profile misclassification could grant overly broad persistent access.
- Cross-tab coordination behavior differs across browser contexts.
- Decide whether inactivity extension is driven by API activity, frontend user activity heartbeat, refresh success, or a combination.
