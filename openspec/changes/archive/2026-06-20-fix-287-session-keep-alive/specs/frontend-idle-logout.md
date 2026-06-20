# PR2 Spec: Frontend Local Idle Logout

## Capability

- Creates/modifies: `auth-session-lifecycle`
- Modified capability diff: frontend idle expiry SHALL become local-only UX cleanup and cross-tab broadcast; explicit manual logout SHALL remain server-authoritative and revoke the refresh-token family.
- `audit-logging` diff: no new frontend audit requirement; backend PR1 owns session lifecycle audit events.

## ADDED Requirements

### Requirement 1: Idle Expiry Does Not Call Server Logout

Frontend inactivity expiry MUST NOT call `POST /auth/logout`; it SHALL clear local auth state and broadcast `session-expired` through the existing session bus.

#### Scenario: Idle tab does not revoke active sibling tab

- GIVEN two tabs share one authenticated session
- WHEN the background tab expires for inactivity
- THEN that tab SHALL clear local state and publish `session-expired`
- AND it SHALL NOT call `/auth/logout` or revoke the server refresh-token family.

#### Scenario: Manual logout still revokes server session

- GIVEN a user clicks explicit Logout
- WHEN `logout()` runs
- THEN it SHALL call `POST /auth/logout`
- AND sibling tabs SHALL receive the `logout` broadcast.

### Requirement 2: Idle UX Toast and Deferred Redirect

Idle expiry SHALL show the Spanish toast “Tu sesión expiró por inactividad. Volvé a iniciar sesión.”, keep it dismissable for 15 seconds, and redirect to `/login` after 30 seconds if still inactive.

#### Scenario: Idle expiry displays and redirects

- GIVEN a standard user becomes inactive past the frontend timer
- WHEN local idle expiry fires
- THEN the toast SHALL be visible and dismissable for 15 seconds
- AND redirect to `/login` SHALL occur after 30 seconds if the session remains inactive.

### Requirement 3: Touch Activity Resets Idle Timer

The frontend SHALL listen for `touchstart` and `touchmove` in addition to existing activity events.

#### Scenario: Mobile touch prevents local expiry

- GIVEN an armed inactivity timer
- WHEN `touchstart` or `touchmove` occurs before timeout
- THEN the idle timer SHALL reset
- AND local expiry SHALL NOT fire at the original deadline.

## Test Plan

- Test files: `frontend/context/AuthContext.test.tsx` and, if extracted, session bus/toast helper tests under `frontend/services/` or `frontend/context/`.
- Focused command: `pnpm --dir frontend run test:run`.
- Green means: RED tests first prove idle expiry calls no `/auth/logout`, manual logout still does, two providers/tabs preserve server state, toast/redirect timings pass with fake timers, and touch events reset the timer.
- Manual smoke before merge: two-tab idle background tab must not force active tab server logout; explicit Logout must still log out sibling tabs.

## Out of Scope

- No backend activity-bump implementation.
- No Prometheus metrics.
- No Bug 3 stale-recovery/rate-limit implementation in #287.
- TODO post-#287: create issue “Fix stale-recovery rate-limit follow-up from Bug 3” — track proposal Bug 3 and `openspec/changes/fix-multi-window-session-timeout/verify-report-pr2.md:56-57` terminal-detail/rate-limit branch follow-up.

## Risks

- `sonner` is not currently in `frontend/package.json`; PR2 must isolate dependency and lockfile changes.
- Vitest 4 rejects `--reporter=basic`; use exactly `pnpm --dir frontend run test:run`.
- True browser multi-tab behavior needs documented manual evidence because unit tests mock the bus.
