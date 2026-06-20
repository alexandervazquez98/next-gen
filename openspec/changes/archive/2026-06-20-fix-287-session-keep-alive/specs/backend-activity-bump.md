# PR1 Spec: Backend Session Activity Bump

## Capability

- Creates/modifies: `auth-session-lifecycle`
- Modified capability diff: authenticated backend activity SHALL update server-side activity for the resolved session, and idle expiry SHALL be based on server-authoritative activity.
- Modified capability diff: `audit-logging` SHALL include `session.activity_recorded` and `session.idle_expired` auth lifecycle events.

## ADDED Requirements

### Requirement 1: Throttled Server Activity Recording

The backend SHALL expose `record_session_activity(session_id, user_id, db, policy)` and call it from refresh and authenticated `get_current_user` paths, including `/auth/users/me`.

#### Scenario: Requests inside throttle window coalesce

- GIVEN `SESSION_ACTIVITY_WRITE_THROTTLE_SECONDS=60` and a valid standard session
- WHEN five authenticated `/auth/users/me` requests occur within 60 seconds
- THEN exactly one `refresh_tokens.last_activity_at` SQL update SHALL occur for that `session_id`.

#### Scenario: DB write failure does not fail auth

- GIVEN activity recording raises a DB exception after authentication succeeds
- WHEN `/auth/users/me` is requested
- THEN the response SHALL still succeed
- AND `logger.exception(...)` SHALL record the failure.

### Requirement 2: Refresh Idle Expiry Is Authoritative

Refresh verification SHALL expire standard sessions whose resolved activity anchor is older than policy timeout. The anchor SHALL be `COALESCE(last_activity_at, created_at)` for transitional NULL rows.

#### Scenario: Expired standard refresh clears cookies

- GIVEN a standard refresh token with activity anchor `now - 16 minutes` and a 15-minute timeout
- WHEN `POST /auth/refresh` is called
- THEN it SHALL return HTTP 401 with session-timeout detail
- AND access/refresh cookies SHALL be cleared.

#### Scenario: Operational policy does not idle-expire

- GIVEN an operational session policy with no idle timeout
- WHEN refresh or authenticated activity is evaluated
- THEN inactivity expiry SHALL NOT revoke the session; activity recording MAY no-op or heartbeat per policy.

### Requirement 3: Session Lifecycle Audit Events

The backend SHALL emit `session.activity_recorded` when activity is persisted and `session.idle_expired` when refresh rejects for idle expiry. No Prometheus metrics SHALL be added.

#### Scenario: Activity and idle expiry are audit-visible

- GIVEN activity is recorded or idle expiry rejects refresh
- WHEN audit logging is inspected
- THEN the corresponding session lifecycle event SHALL exist with safe actor/session context
- AND no sensitive token material SHALL be stored.

## Test Plan

- Test files: `backend/tests/test_auth_service_refresh.py`, `backend/tests/test_auth_router_refresh.py`, and auth user-route coverage for `get_current_user`/`/auth/users/me`.
- Focused commands: `uv run pytest backend/tests/test_auth_service_refresh.py -v`; `uv run pytest backend/tests/test_auth_router_refresh.py -v`; plus the focused user-route test command for the file that owns `/auth/users/me` coverage.
- Green means: RED tests first for throttle count, idle 401 cookie clearing, audit events, operational policy, and DB-error resilience; GREEN implementation passes focused tests before full backend suite.

## Out of Scope

- No frontend idle UX changes.
- No Bug 3 stale-recovery/rate-limit implementation in #287.
- No `SESSION_OPERATIONAL_ENABLED` default change.
- TODO post-#287: create issue “Fix stale-recovery rate-limit follow-up from Bug 3” — track proposal Bug 3 and `openspec/changes/fix-multi-window-session-timeout/verify-report-pr2.md:56-57` terminal-detail/rate-limit branch follow-up.

## Risks

- Activity writes can add DB load; throttle must be proven by SQL update count.
- Existing code currently has no `SESSION_ACTIVITY_WRITE_THROTTLE_SECONDS` or `record_session_activity`; tests must define the contract before implementation.
- Existing `_is_token_idle_expired` treats NULL `last_activity_at` as not expired; PR1 must close that gap with COALESCE semantics.
