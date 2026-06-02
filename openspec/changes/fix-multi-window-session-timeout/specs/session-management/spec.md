# Session Management Specification

## Purpose
Define the post-change authentication and session behavior for operational continuity and secure timeout handling across backend and frontend, including multi-window/session refresh behavior.

## Requirements

### Requirement: Session policy profile resolution

The system MUST resolve each authenticated user into one of two policy categories: operational (NOC/SOC) or non-operational.

- Operational users MUST be explicitly identified (for example by role/profile assignment) and only those users SHALL receive operational persistence.
- Non-operational users MUST receive configurable timeout-based profiles.
- If profile information is missing or invalid, the system SHOULD fall back to non-operational timeout policy.

#### Scenario: Operational versus non-operational policy
- **GIVEN** a NOC/SOC user and a standard user authenticate,
- **WHEN** session policy resolution is evaluated,
- **THEN** the NOC/SOC user MUST resolve to operational profile and the standard user MUST resolve to non-operational profile.

#### Scenario: Missing profile data
- **GIVEN** a user session without valid profile metadata,
- **WHEN** session checks run,
- **THEN** the system MUST apply the non-operational timeout policy.

### Requirement: Operational sessions are inactivity-persistent with explicit lifecycle controls

Operational (NOC/SOC) sessions MUST NOT expire due to inactivity.

- Operational sessions MUST remain valid across refresh cycles and multi-window usage unless explicitly invalidated.
- Operational sessions MUST be terminated only by explicit logout, admin/session revocation, password reset, or profile change to non-operational.
- The system MUST record lifecycle events for operational sessions (creation, role/profile changes, explicit revocation, forced logout) in audit logs.

#### Scenario: Long-running operational monitoring session
- **GIVEN** a NOC user with active sessions in multiple browser tabs,
- **WHEN** the user remains idle for extended time,
- **THEN** sessions MUST remain active (no inactivity logout) unless an explicit revocation action occurs.

#### Scenario: Operational session revocation
- **GIVEN** a security operator revokes an operational user session,
- **WHEN** revocation is applied,
- **THEN** all active session instances for that user/session identifier MUST become invalid and logged with an auditable event.

### Requirement: Non-operational sessions use configurable inactivity timeout

The system MUST enforce inactivity-based timeout for non-operational users according to configured session profile parameters.

- The timeout duration and optional warning behavior MUST be configurable per deployment or profile.
- The system MUST perform logout of non-operational users once the configured inactivity threshold is reached.
- This timeout behavior MUST be uniform across tabs/windows for the same account session.

#### Scenario: Non-operational idle timeout
- **GIVEN** a non-operational user session with inactivity timeout configured to 15 minutes,
- **WHEN** no user activity occurs for 15 minutes,
- **THEN** the user MUST be logged out and informed that the session expired.

#### Scenario: Configurable threshold
- **GIVEN** an updated non-operational policy profile is applied,
- **WHEN** subsequent sessions are created,
- **THEN** timeout behavior SHALL use the updated configured values.

### Requirement: Multi-window refresh contention must be tolerated

The system MUST tolerate refresh token rotation contention across multiple windows/tabs without forcing logout when requests overlap during valid token windows.

- A benign concurrent refresh race between tabs MUST not terminate the account session by itself.
- If one refresh attempt succeeds and another uses a now-stale token, the result of the stale attempt SHALL be handled as recoverable (e.g., by replaying valid session state or a retry path) and MUST NOT produce a hard lockout.

#### Scenario: Concurrent tab refresh
- **GIVEN** two tabs approaching token expiry simultaneously,
- **WHEN** both trigger refresh near-concurrently,
- **THEN** at least one succeeds and all tabs SHALL remain authenticated, with no forced logout from that overlap.

### Requirement: Refresh stale-token/rate-limit behavior must avoid user lockout

The system MUST distinguish legitimate refresh races from abuse and MUST NOT lock out a user solely because of transient stale-token overlap.

- During a bounded burst of refresh attempts from the same logical session, the system SHOULD prioritize recoverability over immediate revocation.
- Hard lockout/revocation for stale tokens SHOULD only occur for sustained suspicious behavior beyond policy-defined thresholds.
- Temporary backoff responses from refresh attempts MUST be recoverable and logged for monitoring.

#### Scenario: Replayed stale token during overlap
- **GIVEN** a tab retries with a token that has just been rotated by another tab,
- **WHEN** the backend enforces stale-token checks under rate limits,
- **THEN** the system MUST not revoke the session or sign out the user solely for that request; user authentication must remain recoverable.

#### Scenario: Sustained abusive refresh behavior
- **GIVEN** a high-volume refresh failure pattern beyond configured thresholds,
- **WHEN** mitigation triggers,
- **THEN** the session MAY enter a temporary hard-stop state with explicit security event, and user remediation must be deterministic.

### Requirement: Frontend refresh singleflight and bounded retries

The frontend MUST coalesce refresh activity so that at most a bounded number of concurrent refresh calls is initiated for one logical session.

- When multiple triggers occur (multiple tabs, focus changes, visibility changes), refresh should be singleflight within a short window.
- Refresh retry attempts MUST be bounded by a configured maximum and must escalate to logout only after all bounded retries fail.
- The client MUST avoid unbounded refresh bursts and preserve normal UX during transient backend contention.

#### Scenario: Refresh storm prevention
- **GIVEN** several tabs become active at the same time,
- **WHEN** they detect near-expiring tokens,
- **THEN** the frontend MUST execute at most one refresh attempt per bounded window and suppress duplicates.

#### Scenario: Bounded refresh failures
- **GIVEN** repeated transient refresh failures in a non-operational session,
- **WHEN** retry limit is reached,
- **THEN** user is logged out cleanly with an explicit session-expired or re-authentication message.

### Requirement: Clean inactivity logout for non-operational users

After a non-operational inactivity timeout, the system SHOULD ensure the user is fully terminated from all local and active sessions.

- UI state, background loops, and held credentials SHOULD be cleared on logout.
- Non-operational users must be redirected to authentication entry and cannot continue API activity.
- Operational users MUST NOT be presented the inactivity-timeout logout path unless their policy has changed.

#### Scenario: Expired non-operational session cleanup
- **GIVEN** a non-operational user times out due inactivity,
- **WHEN** frontend receives timeout/expiry state,
- **THEN** all open tabs for that user session MUST transition to unauthenticated state and show a standard re-login flow.

## Non-Goals

- No broad RBAC redesign.
- No service catalog changes.
- No unrelated visualizer UI changes.
- No changes to identity provider or external SSO protocol in this session.
