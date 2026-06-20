# Auth Session Lifecycle Specification

## Purpose

Define the server-authoritative session activity, idle expiry, and idle UX behavior that keeps authenticated users connected when they are active, terminates sessions when they are truly idle, and stops idle-tab local timeouts from revoking active sibling tabs. This capability extends the existing `session-management` capability (from `openspec/changes/fix-multi-window-session-timeout/`) by adding throttled server activity recording, a deployment-safe DB repair step, and a local-only frontend idle expiry with toast and deferred redirect.

## Requirements

### Requirement: Batched Backfill of Legacy Activity NULLs

The deployment SHALL update existing `refresh_tokens` rows where `last_activity_at IS NULL` in bounded batches around 1000 rows with a sleep between batches.

The runtime anchor for activity calculations SHALL be `COALESCE(last_activity_at, created_at)` for transitional NULL rows. The ORM `last_activity_at` column stays non-null; NULL is treated only as a transitional legacy DB state and is not exposed as "NULL until first request".

#### Scenario: Backfills at least one legacy row

- GIVEN a PostgreSQL `refresh_tokens` row with `last_activity_at IS NULL` and non-null `created_at`
- WHEN the backfill runs
- THEN that row SHALL have `last_activity_at` set to a non-null timestamp
- AND evidence SHALL identify at least one exercised live row.

#### Scenario: Empty batch is safe

- GIVEN no `refresh_tokens.last_activity_at IS NULL` rows exist
- WHEN the backfill runs
- THEN it SHALL complete without changing auth behavior or failing deployment.

#### Scenario: Live evidence is captured

- GIVEN a local or staging PostgreSQL instance with seeded NULL and non-NULL rows
- WHEN the backfill is executed
- THEN committed evidence SHALL show at least one NULL row updated to a non-null timestamp
- AND the control (non-NULL) row SHALL remain unchanged
- AND a second execution SHALL update 0 rows (idempotency).

### Requirement: Throttled Server Activity Recording

The backend SHALL expose `record_session_activity(session_id, user_id, db, policy)` and call it from refresh and authenticated `get_current_user` paths, including `/auth/users/me`.

The recorder SHALL coalesce activity writes using a per-worker advisory cache plus a DB conditional `UPDATE refresh_tokens SET last_activity_at = now() WHERE session_id=:sid AND user_id=:uid AND (last_activity_at IS NULL OR last_activity_at <= now() - :throttle)`. The throttle window SHALL default to `SESSION_ACTIVITY_WRITE_THROTTLE_SECONDS=60` and be configurable. The cache SHALL be bounded (default 10 000 entries) with expired-key eviction on the write path.

The recorder SHALL return `True` only when the DB row was updated and audit emission was attempted; `False` for missing `sid`, operational profile no-op, throttle skip, DB no-row update, or logged DB failure.

#### Scenario: Requests inside throttle window coalesce

- GIVEN `SESSION_ACTIVITY_WRITE_THROTTLE_SECONDS=60` and a valid standard session
- WHEN five authenticated `/auth/users/me` requests occur within 60 seconds
- THEN exactly one `refresh_tokens.last_activity_at` SQL update SHALL occur for that `session_id`.

#### Scenario: DB write failure does not fail auth

- GIVEN activity recording raises a DB exception after authentication succeeds
- WHEN `/auth/users/me` is requested
- THEN the response SHALL still succeed
- AND `logger.exception(...)` SHALL record the failure.

#### Scenario: Operational profile is a no-op for activity writes

- GIVEN an operational session policy
- WHEN authenticated activity is recorded
- THEN `record_session_activity` SHALL return `False` and SHALL NOT issue an SQL update
- AND the operational policy SHALL remain free of DB write pressure.

### Requirement: Refresh Idle Expiry Is Authoritative

Refresh verification SHALL expire standard sessions whose resolved activity anchor is older than policy timeout. The anchor SHALL be `COALESCE(last_activity_at, created_at)` for transitional NULL rows. Operational sessions SHALL NOT idle-expire.

The router SHALL return HTTP 401 on idle expiry, clear `access_token` and `refresh_token` cookies, and emit a `session.idle_expired` audit event. The 401 response SHALL preserve the cookie-clearing `Set-Cookie` headers (use `JSONResponse` rather than `raise HTTPException` when the route's `response_model` would otherwise reject the error body).

#### Scenario: Expired standard refresh clears cookies

- GIVEN a standard refresh token with activity anchor `now - 16 minutes` and a 15-minute timeout
- WHEN `POST /auth/refresh` is called
- THEN it SHALL return HTTP 401 with session-timeout detail
- AND access/refresh cookies SHALL be cleared.

#### Scenario: Operational policy does not idle-expire

- GIVEN an operational session policy with no idle timeout
- WHEN refresh or authenticated activity is evaluated
- THEN inactivity expiry SHALL NOT revoke the session
- AND activity recording MAY no-op or heartbeat per policy.

#### Scenario: NULL `last_activity_at` uses `created_at` as anchor

- GIVEN a refresh token with `last_activity_at IS NULL` and `created_at = now - 16 minutes` under a 15-minute standard timeout
- WHEN `POST /auth/refresh` is called
- THEN it SHALL return HTTP 401 (idle expired)
- AND a token with `last_activity_at = now - 5 minutes` SHALL still be valid.

### Requirement: Session Lifecycle Audit Events

The backend SHALL emit `session.activity_recorded` when activity is persisted and `session.idle_expired` when refresh rejects for idle expiry. No Prometheus metrics SHALL be added.

The audit context for these events SHALL use the allow-list keys: `session_id`, `user_id`, `policy_profile`, `throttle_seconds`, `activity_anchor`. The audit context SHALL NOT contain raw refresh/access tokens, cookies, authorization headers, request body, or token hashes.

#### Scenario: Activity and idle expiry are audit-visible

- GIVEN activity is recorded or idle expiry rejects refresh
- WHEN audit logging is inspected
- THEN the corresponding session lifecycle event SHALL exist with safe actor/session context
- AND no sensitive token material SHALL be stored.

### Requirement: Frontend Idle Expiry Does Not Call Server Logout

Frontend inactivity expiry MUST NOT call `POST /auth/logout`; it SHALL clear local auth state, broadcast `session-expired` through the existing session bus, and SHALL NOT revoke the server refresh-token family.

Manual explicit `logout()` SHALL remain server-authoritative: it calls `POST /auth/logout`, revokes the refresh-token family, and broadcasts `logout` to sibling tabs.

#### Scenario: Idle tab does not revoke active sibling tab

- GIVEN two tabs share one authenticated session
- WHEN the background tab expires for inactivity
- THEN that tab SHALL clear local state and publish `session-expired`
- AND it SHALL NOT call `/auth/logout` or revoke the server refresh-token family
- AND the active tab SHALL remain authenticated.

#### Scenario: Manual logout still revokes server session

- GIVEN a user clicks explicit Logout
- WHEN `logout()` runs
- THEN it SHALL call `POST /auth/logout`
- AND sibling tabs SHALL receive the `logout` broadcast.

### Requirement: Idle UX Toast and Deferred Redirect

Idle expiry SHALL show the Spanish toast `Tu sesión expiró por inactividad. Volvé a iniciar sesión.`, keep it dismissable for 15 seconds, and redirect to `/login` after 30 seconds if the user remains inactive. The redirect timer SHALL survive the inactivity `useEffect` cleanup (it is cleared on a top-level provider unmount and on a successful `login`).

#### Scenario: Idle expiry displays and redirects

- GIVEN a standard user becomes inactive past the frontend timer
- WHEN local idle expiry fires
- THEN the toast SHALL be visible and dismissable for 15 seconds
- AND redirect to `/login` SHALL occur after 30 seconds if the session remains inactive.

### Requirement: Touch Activity Resets Idle Timer

The frontend SHALL listen for `touchstart` and `touchmove` in addition to the existing activity events. Any recognized activity event SHALL reset the inactivity deadline.

#### Scenario: Mobile touch prevents local expiry

- GIVEN an armed inactivity timer
- WHEN `touchstart` or `touchmove` occurs before timeout
- THEN the idle timer SHALL reset
- AND local expiry SHALL NOT fire at the original deadline.

## Test Plan

- Backend focused: `uv run pytest backend/tests/test_refresh_token_activity_backfill.py backend/tests/test_auth_service_refresh.py backend/tests/test_auth_router_refresh.py backend/tests/test_routers_auth_users_roles.py backend/tests/test_audit_service.py -v`.
- Backend full suite: `uv run pytest backend/tests -q`.
- Frontend focused: `pnpm --dir frontend exec vitest run context/AuthContext.test.tsx services/sessionBus.test.ts`.
- Frontend full suite: `pnpm --dir frontend run test:run` (no `--reporter=basic`).
- Manual evidence: PR0 requires PostgreSQL before/after row evidence; PR1 requires at least one `session.activity_recorded` and one `session.idle_expired` audit row; PR2 requires a two-tab manual smoke confirming idle background tab does not force active tab server logout.

## Out of Scope

- Bug 3 stale-recovery/rate-limit branch (tracked separately under `alexandervazquez98/next-gen#292`).
- No `SESSION_OPERATIONAL_ENABLED` default change.
- No broad ORM/DB nullable mismatch refactor beyond transitional NULL handling.
- No Prometheus metrics.
- No E2E harness for true browser tabs (manual two-tab smoke is required).

## Source

- `openspec/changes/fix-287-session-keep-alive/specs/db-backfill.md` (PR0)
- `openspec/changes/fix-287-session-keep-alive/specs/backend-activity-bump.md` (PR1)
- `openspec/changes/fix-287-session-keep-alive/specs/frontend-idle-logout.md` (PR2)
- Extends `openspec/changes/fix-multi-window-session-timeout/specs/session-management/spec.md` (the prior `session-management` capability is now superseded by this consolidated capability for the keep-alive / idle-expiry behavior introduced by #287).
