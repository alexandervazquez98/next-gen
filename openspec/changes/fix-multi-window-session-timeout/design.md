# Design: fix-multi-window-session-timeout

Status: Draft
Change ID: `fix-multi-window-session-timeout`
GitHub Issue: `#188`

## Executive Summary

Implement role/profile-aware session policy and refresh orchestration so operational NOC/SOC dashboards remain continuously authenticated while non-operational users receive configurable inactivity logout. The backend will become the source of truth for session policy, refresh-token state, inactivity, stale rotation tolerance, explicit revocation, and audit events. The frontend will reduce refresh storms with per-tab singleflight, bounded retry/redirect behavior, and best-effort cross-tab logout/session coordination.

This is a cross-cutting auth change touching backend models/services/routes and frontend API/auth state. The implementation should be split into chained PRs rather than one PR under the configured 400 changed-line review budget.

## Current-State Findings

### Backend

Relevant paths:

- `backend/routers/auth.py`
  - `/auth/token` validates credentials and sets only the `access_token` cookie in the current code.
  - `/auth/refresh` validates a refresh token, revokes it, creates a new access token and refresh token, sets both cookies, and increments refresh-token keyed rate limits on invalid tokens.
  - `/auth/logout` revokes all refresh tokens for the user and clears cookies.
- `backend/services/auth_service.py`
  - `ACCESS_TOKEN_EXPIRE_MINUTES = 15` is hardcoded.
  - `create_refresh_token()` uses hardcoded `REFRESH_TOKEN_EXPIRE_DAYS` from `models.refresh_token`.
  - `verify_refresh_token()` returns only `user_id` or `None`, so it cannot distinguish expired, revoked, rotated/stale, inactive, or abusive states.
- `backend/models/refresh_token.py`
  - `RefreshToken` currently stores `token_hash`, `created_at`, `expires_at`, and `revoked_at` only.
- `backend/middleware/rate_limit.py`
  - Refresh failures are keyed by hash of the submitted refresh token.
  - Legitimate stale-token races currently look like invalid-token failures and can accumulate lockout attempts.

Important discrepancy to correct during implementation: `login_for_access_token()` imports `create_refresh_token` but currently does not create/set a refresh-token cookie. The new design requires login to establish a backend refresh-token/session row and set the refresh cookie.

### Frontend

Relevant paths:

- `frontend/services/api.ts`
  - Any 401 immediately calls `/auth/refresh` and retries once.
  - Concurrent 401s cause concurrent refresh calls; there is no singleflight or queue.
  - Refresh failure redirects immediately for non-SSE requests.
- `frontend/context/AuthContext.tsx`
  - Hydrates via `/auth/users/me` on mount.
  - Logout is best effort and local state is isolated per tab.

## Design Goals

1. Resolve every authenticated user/session to one policy: `operational` or `standard`.
2. Make operational sessions inactivity-persistent unless explicitly logged out, revoked, disabled, password-reset, or reclassified.
3. Enforce configurable inactivity timeout for standard/non-operational users.
4. Tolerate benign multi-tab refresh rotation races without lockout.
5. Bound frontend refresh retries and prevent refresh storms.
6. Add tests first for policy resolution, stale-token tolerance, inactivity expiry, rate-limit behavior, frontend singleflight, and clean logout.

## Session Policy Resolution

### Policy model

Create a backend session policy module, likely `backend/services/session_policy.py`, with:

```python
class SessionPolicy(BaseModel):
    name: Literal["operational", "standard"]
    access_token_minutes: int
    refresh_token_days: int | None
    idle_timeout_minutes: int | None
    stale_rotation_grace_seconds: int
    stale_rotation_max_recoveries: int
    persistent: bool
```

### Resolution order

The resolver should fail closed to `standard`:

1. If global operational persistence is disabled, return `standard`.
2. If the user is inactive/disabled, do not resolve an active policy; auth fails.
3. If an explicit user allowlist env/config marks the user operational, return `operational`.
4. If the user's role is in configured operational roles, return `operational`.
5. If a future explicit `session_policy_profile` user field exists and is valid, use it.
6. Otherwise return `standard`.

Recommended initial knobs:

- `SESSION_OPERATIONAL_ENABLED=true|false` default `false` or conservative `true` only if roles are explicitly configured.
- `SESSION_OPERATIONAL_ROLES=NOC,SOC` default empty or `NOC,SOC` if those roles are already deployed.
- `SESSION_OPERATIONAL_USERS=` optional comma-separated break-glass allowlist for deployments without NOC/SOC roles yet.
- `SESSION_STANDARD_ACCESS_MINUTES=15`.
- `SESSION_STANDARD_IDLE_TIMEOUT_MINUTES=15` or deployment-chosen value.
- `SESSION_STANDARD_REFRESH_DAYS=7`.
- `SESSION_OPERATIONAL_ACCESS_MINUTES=15` to keep access JWTs short even when refresh is persistent.
- `SESSION_OPERATIONAL_REFRESH_DAYS=` empty/none means no refresh max-age.
- `SESSION_STALE_ROTATION_GRACE_SECONDS=30`.
- `SESSION_STALE_ROTATION_MAX_RECOVERIES=3` per token/session grace window.

Design decision: keep access JWTs short-lived for both profiles. Operational persistence is provided by non-expiring refresh/session state, not by unbounded access JWTs. This preserves explicit revocation responsiveness and reduces impact if an access token leaks.

## Backend Design

### Refresh-token/session model

Extend `RefreshToken` to represent a token family/logical browser session and support race classification:

- `session_id` (`String`/UUID, indexed): stable logical session identifier created at login and included in access-token claims as `sid`.
- `policy_profile` (`String`): snapshot of resolved policy at token creation (`operational` or `standard`).
- `last_activity_at` (`DateTime`, nullable=False): authoritative server-side activity timestamp for standard inactivity checks.
- `rotated_at` (`DateTime`, nullable=True): set when token is replaced by rotation.
- `replaced_by_token_id` (`Integer`, nullable=True): points to the replacement token when known.
- `revoked_reason` (`String`, nullable=True): e.g. `logout`, `admin_revoke`, `password_reset`, `profile_change`, `rotated`, `abuse`.
- `expires_at` should become nullable or use a documented far-future sentinel for operational tokens. Prefer nullable `expires_at` where `None` means no max-age expiry.
- Optional `stale_recovery_count` (`Integer`, default 0) to cap recoveries from recently rotated tokens.

Migration note: the repository currently relies on `Base.metadata.create_all` in places and explicit migrations for some polling tables. The apply phase should choose the existing project migration convention for auth table alterations and add tests that fail until these columns exist.

### Service contracts

Refactor `verify_refresh_token()` away from `Optional[int]` into a result object, likely in `models.refresh_token` or `services.auth_service`:

```python
class RefreshVerificationStatus(str, Enum):
    VALID = "valid"
    MISSING = "missing"
    EXPIRED = "expired"
    IDLE_EXPIRED = "idle_expired"
    REVOKED = "revoked"
    ROTATED_STALE_RECOVERABLE = "rotated_stale_recoverable"
    ROTATED_STALE_REJECTED = "rotated_stale_rejected"
    USER_INACTIVE = "user_inactive"

class RefreshVerificationResult(BaseModel):
    status: RefreshVerificationStatus
    user_id: int | None = None
    session_id: str | None = None
    policy: SessionPolicy | None = None
    token_id: int | None = None
    should_count_rate_limit: bool = True
```

Required service operations:

- `create_session_tokens(user, db, policy)`
  - Creates refresh token with `session_id`, `policy_profile`, `last_activity_at=now`, and profile-derived `expires_at`.
  - Creates access token with `sub`, `role`, `sid`, and `profile` claims.
- `verify_refresh_token(token, db, now)`
  - Returns typed statuses.
  - For operational tokens: ignore inactivity; honor explicit revocation, user active state, profile change, and optional max-age if configured.
  - For standard tokens: reject if `now - last_activity_at >= idle_timeout`.
  - For rotated tokens: if `revoked_reason == "rotated"` and `rotated_at` is within `SESSION_STALE_ROTATION_GRACE_SECONDS` and session/user remains valid, return `ROTATED_STALE_RECOVERABLE` with `should_count_rate_limit=False`.
- `rotate_refresh_token(token_row, db, policy)`
  - Marks old token rotated, creates replacement, links `replaced_by_token_id`, and commits atomically where possible.
- `recover_from_stale_rotation(token_row, db, policy)`
  - Does not count as a failed auth attempt.
  - If recovery count is under cap and session is still valid, issue a fresh access token and refresh token for the same `session_id`.
  - Audit/log as stale race recovery.
- `record_session_activity(session_id, user_id, db, policy)`
  - Updates `last_activity_at` for standard sessions on accepted API activity or refresh.
  - No-op or low-frequency audit heartbeat for operational sessions.
- `revoke_session(session_id/user_id, reason, db)` and existing `revoke_all_user_refresh_tokens()` update `revoked_reason` and audit.

### Login flow

`POST /auth/token` must:

1. Authenticate user.
2. Resolve session policy.
3. Create refresh token/session row.
4. Create access token with `sid` and `profile` claims.
5. Set `access_token` and `refresh_token` cookies with profile-appropriate `max_age`.
6. Return existing `Token` response for compatibility, optionally adding session metadata only if response schema changes are covered by tests.

Cookie expectations:

- Standard refresh cookie max age should match `SESSION_STANDARD_REFRESH_DAYS` and still be cut short by inactivity server-side.
- Operational refresh cookie can be a session cookie or a long max age if browsers require durability across reloads. Prefer explicit deployment config for this because browser cookie semantics and security posture vary.

### Refresh flow

`POST /auth/refresh` must:

1. Extract refresh token from cookie/body.
2. If missing, return 401 and count only according to current behavior.
3. Rate-limit precheck may remain, but stale-race statuses must bypass increment.
4. Verify token using the typed result.
5. For `VALID`:
   - Load user and re-resolve policy to catch role/profile changes.
   - If profile changed from operational to standard, enforce standard policy immediately and audit `profile_change` if revoking.
   - Rotate token and set cookies.
   - Clear failed attempts for the submitted token.
6. For `ROTATED_STALE_RECOVERABLE`:
   - Do not increment refresh-token failed attempts.
   - Issue recoverable replacement cookies or return a success response that lets the browser converge.
   - Log as `refresh_stale_recovered`.
7. For terminal statuses (`EXPIRED`, `IDLE_EXPIRED`, `REVOKED`, `USER_INACTIVE`, rejected stale):
   - Increment rate-limit only when `should_count_rate_limit=True`.
   - Return deterministic 401 detail such as `session_expired`, `idle_timeout`, or `session_revoked`.
   - Clear cookies for terminal session states where appropriate.
8. For sustained suspicious stale/replay beyond grace/cap:
   - Return 401 or 429 with explicit security/audit event.
   - Revoke session only after policy threshold, not on the first stale overlap.

### Inactivity enforcement

Backend is authoritative. Standard-user inactivity should be updated on real authenticated API activity, not purely on frontend timers.

Implementation options:

- Minimal: in `get_current_user`, after successful JWT decode and user load, read `sid` and update `last_activity_at` throttled to at most once per minute per session.
- More complete: add a session middleware/dependency helper used by protected auth routes to update activity and reject standard sessions whose `last_activity_at` exceeds timeout.

The apply phase should avoid heavy writes on every API request by using a throttle window such as `SESSION_ACTIVITY_WRITE_THROTTLE_SECONDS=60`.

### Audit expectations

Add audit logging through the project's existing logging mechanism if no audit table exists. Minimum events:

- `session_created`
- `session_refreshed`
- `refresh_stale_recovered`
- `standard_session_idle_expired`
- `operational_session_created`
- `session_revoked_logout`
- `session_revoked_admin`
- `session_revoked_password_reset`
- `session_revoked_profile_change`
- `refresh_abuse_lockout`

Do not log raw tokens; log user id, session id, token row id, reason, source IP/user-agent if already available or easy to pass from `Request`.

### Rate-limit behavior

Keep protection against invalid refresh-token abuse, but classify recoverable stale rotation before incrementing attempts.

- Invalid hash / unknown token: count attempts under current hashed-key behavior.
- Expired/revoked terminal token: count attempts unless classified as benign stale rotation.
- Recoverable rotated token within grace: do not increment attempts; clear attempts if a successful recovery is issued.
- Sustained stale use beyond grace/cap: count attempts and optionally lock only after clear threshold.

This preserves lockout for abuse while preventing legitimate multi-tab races from causing lockout.

## Frontend Design

### Per-tab refresh singleflight

In `frontend/services/api.ts`, add module-level refresh state:

- `let refreshPromise: Promise<void> | null = null`.
- `refreshSession()` returns the existing promise when one is in flight.
- Only one `/auth/refresh` request can be active per tab.
- Requests receiving 401 await the same refresh promise, then retry once.

Expected behavior:

- A burst of parallel API calls in one tab produces one refresh call.
- Each original request is retried at most once after refresh.
- Refresh calls themselves must not recursively trigger refresh.

### Bounded retry and redirect

Add explicit retry metadata:

- Internal request config flag: `skipAuthRefresh` for `/auth/refresh` and `/auth/logout`.
- Internal request config flag/counter: `authRetryCount`, max default `1` for original request retries.
- Refresh retry max default `1` or `2` for transient 429/backoff only.

Redirect behavior:

- Redirect to `/login` only after bounded refresh attempts fail or backend returns terminal details (`idle_timeout`, `session_revoked`, `session_expired`).
- Avoid repeated redirects by central helper `redirectToLoginOnce(reason)`.
- SSE requests should continue to avoid immediate redirect, but must receive a terminal error signal so stream owners can stop reconnect loops on session expiry.

### Cross-tab coordination

Use `BroadcastChannel` when available, with `localStorage` event fallback if feasible:

Channel: `next-gen-auth-session`

Messages:

- `refresh-started` with timestamp and tab id.
- `refresh-finished` with success/failure and timestamp.
- `logout` with reason.
- `session-expired` with reason.

Recommended initial scope:

- Implement cross-tab logout/session-expired broadcast because it is low-risk and directly satisfies clean multi-tab logout.
- Cross-tab refresh singleflight is feasible but more complex because HttpOnly cookies cannot expose token state. If implemented, use a short-lived `localStorage` lock with TTL (for example 5 seconds) so tabs wait briefly before issuing their own refresh. If lock acquisition is unreliable, fall back to backend stale-race tolerance.

Design decision: backend stale-token tolerance is required even if cross-tab refresh coordination is implemented, because browser locks are advisory and fail across processes/private contexts.

### Inactivity handling

The frontend should assist UX but not be the security authority.

- Track standard-user activity events (`click`, `keydown`, `mousemove` throttled, focus/visibility) after auth hydration.
- If `/auth/users/me` or login response exposes `session_policy`, only enable inactivity UI for `standard` policy.
- Do not arm inactivity logout timers for `operational` policy.
- For standard users, show optional warning before idle timeout if configured; otherwise let backend terminal response drive logout.
- On local idle timeout, call `/auth/logout` best effort, clear user state, broadcast `session-expired`, redirect to login with message.
- On any terminal backend idle/session expiry response, clear user state and broadcast.

If exposing policy metadata is too large for first implementation, infer operational roles conservatively only for UX timers while backend remains authoritative.

## API/Contract Changes

Backend response/error details should be stable enough for frontend branching:

- Refresh success remains compatible with `RefreshTokenResponse(access_token=..., token_type="bearer")`.
- Refresh/login may optionally include:
  - `session_policy: "operational" | "standard"`
  - `idle_timeout_minutes: int | null`
- Terminal refresh 401 details should be strings or structured details with one of:
  - `invalid_refresh_token`
  - `session_expired`
  - `idle_timeout`
  - `session_revoked`
  - `user_inactive`
- Recoverable stale rotation should return 200 with new cookies, not a frontend-visible error.

Keep existing public API shape where possible; cookie behavior and backend state are the primary changes.

## Strict TDD Test Plan

Strict TDD is active because relevant automated tests exist and new tests can be reasonably created. Write RED tests before implementation.

### Backend RED tests

Likely files:

1. `backend/tests/test_session_policy.py` (new)
   - `test_resolves_operational_role_from_config`
   - `test_missing_profile_falls_back_to_standard`
   - `test_operational_persistence_can_be_disabled_by_env`
   - `test_standard_policy_uses_configured_idle_timeout`
2. `backend/tests/test_auth_service_refresh.py` (extend)
   - `test_create_refresh_token_records_session_policy_and_last_activity`
   - `test_operational_refresh_token_has_no_inactivity_expiry`
   - `test_standard_refresh_token_idle_expires_after_configured_timeout`
   - `test_recently_rotated_token_returns_stale_recoverable_status`
   - `test_stale_token_beyond_grace_is_rejected`
3. `backend/tests/test_auth_router_refresh.py` (extend)
   - `test_login_sets_refresh_cookie_and_session_claim`
   - `test_concurrent_stale_refresh_does_not_increment_rate_limit`
   - `test_recoverable_stale_refresh_returns_success_and_sets_cookies`
   - `test_idle_expired_standard_session_clears_cookies_and_returns_401`
   - `test_sustained_invalid_refresh_still_rate_limits`
4. `backend/tests/test_routers_auth_users_roles.py` or a new auth-session route test
   - `test_operational_user_me_does_not_idle_timeout`
   - `test_standard_user_activity_updates_last_activity_throttled`

Run command: `cd backend && python -m pytest`.

### Frontend RED tests

Likely files:

1. `frontend/services/api.test.ts` (extend)
   - `coalesces_parallel_401s_into_single_refresh_call`
   - `retries_each_original_request_once_after_shared_refresh`
   - `does_not_recursively_refresh_refresh_endpoint`
   - `redirects_to_login_once_after_bounded_refresh_failure`
   - `does_not_redirect_immediately_for_sse_refresh_failure`
2. `frontend/context/AuthContext.test.tsx` (extend)
   - `broadcast_logout_clears_authenticated_state_in_other_tabs`
   - `session_expired_message_clears_user_and_redirects`
   - `operational_policy_does_not_arm_inactivity_logout_timer`
   - `standard_policy_arms_inactivity_logout_timer_when_metadata_available`
3. Optional new `frontend/services/authSessionChannel.test.ts`
   - `uses_broadcast_channel_when_available`
   - `falls_back_to_storage_event_when_broadcast_channel_missing`

Run command: `cd frontend && corepack pnpm test:run`.

### Manual evidence after automated tests

If browser cross-tab locking is not fully automatable in Vitest, verify manually:

1. Open two tabs as standard user, force access expiry, trigger simultaneous API requests; both remain authenticated after one refresh cycle.
2. Open two tabs as standard user and idle past configured timeout; both transition to login/expired message.
3. Open NOC/SOC dashboard tab and leave idle past standard timeout; it remains authenticated unless explicitly logged out/revoked.

## Rollout Plan

Recommended chained PRs:

1. **Backend session policy and token-state PR**
   - Add policy resolver, model fields/migration, typed refresh verification, login refresh-cookie issuance, backend tests.
2. **Backend stale-race/rate-limit hardening PR**
   - Add recoverable stale rotation behavior, audit logging, inactivity enforcement, concurrent/rate-limit tests.
   - This may be combined with PR 1 only if implementation remains under review budget.
3. **Frontend refresh/session coordination PR**
   - Add singleflight, bounded retry/redirect, cross-tab logout, inactivity UX, frontend tests.

One PR is not recommended under the configured 400 changed-line review budget because model/schema changes, backend auth logic, route behavior, frontend request orchestration, and tests will likely exceed the budget and deserve isolated review.

## Risks and Mitigations

- **Operational misclassification grants persistence**: fail closed to standard; require explicit configured roles/users; audit operational session creation.
- **Long-lived refresh token theft risk**: keep access tokens short; support immediate revocation; log operational lifecycle events; avoid raw token logs.
- **Refresh race recovery could enable replay abuse**: only recover recently rotated tokens within a short grace window and capped recovery count; rate-limit beyond threshold.
- **Inactivity writes create DB load**: throttle `last_activity_at` updates.
- **Cross-tab browser APIs are unreliable**: backend stale tolerance remains authoritative; frontend coordination is best effort.
- **Profile changes while logged in**: re-resolve policy on refresh and protected session checks; revoke or downgrade sessions deterministically.

## Open Implementation Questions for Apply Phase

- Whether to add a user-level `session_policy_profile` column now or rely on configured role/user mapping for this issue. This design recommends starting with configured role/user mapping and leaving a column as future enhancement unless product requires per-user UI assignment immediately.
- Whether operational refresh cookies should be persistent browser cookies with long max-age or session cookies backed by non-expiring server state. This should be chosen per deployment security preference.
- Which existing audit/logging sink should hold session lifecycle events if no audit table currently exists.
