# Proposal: fix-multi-window-session-timeout

Status: Draft
Change ID: `fix-multi-window-session-timeout`
GitHub Issue: `#188`

## Executive Summary
This proposal introduces session timeout profiles to address login lockouts and token churn in multi-window usage while preserving secure behavior for non-operational users. Operational roles (NOC/SOC) require non-expiring, monitoring-stable sessions, while other users keep configurable activity-based timeout policies. The design separates **who should be persistent** from **who should expire**, and aligns frontend/backend behavior to avoid multi-tab refresh races and frontend refresh storms.

## Problem Statement
Current auth behavior appears to combine refresh-token rotation and inactivity handling in a way that causes:
- race conditions when the same session/account is active across multiple browser windows/tabs,
- lockouts when one tab invalidates refresh state for others,
- repeated refresh bursts (`refresh storm`) in active multi-window users,
- inability to support different timeout expectations for different user operational profiles.

## Goals
1. Define explicit session policy profiles tied to user role/profile (operational vs. non-operational).
2. Ensure NOC/SOC sessions are persistent (no inactivity expiry) to support 24/7 monitoring continuity.
3. Ensure standard/admin/non-operational users use configurable inactivity and refresh controls.
4. Preserve/restore robust multi-window behavior:
   - avoid cross-window refresh collisions,
   - avoid lockouts due to token rotation contention,
   - prevent refresh amplification in multiple open tabs.
5. Keep security posture explicit with auditability for long-lived operational sessions.

## Non-Goals
- Not implementing code in this phase.
- Not changing identity provider or external SSO protocol.
- Not redefining role taxonomy beyond mapping to profiles.
- Not adding new session storage technology (Redis/local store/backend architecture stays current unless design dictates later).

## Scope
### In Scope
- Backend auth/session policy semantics (profile resolution, expiry rules, profile config paths).
- Frontend token/session orchestration behavior under multi-window conditions.
- User/account policy assignment and override model.
- Security/audit framing for long-lived sessions.

### Out of Scope
- New IAM integrations.
- Changes outside authentication/session lifecycle.
- Hardcoding concrete timeout values in code (defaults may be proposed but should be configurable).

## Proposed Session Policy Profiles
### Operational Profiles
- **NOC** and **SOC** users:
  - Sessions are **non-expiring by inactivity** for both access and refresh lifecycles.
  - Objective: uninterrupted monitoring continuity across shifts/windows.
  - These are explicit exceptions, not defaults.

### Non-operational Profiles
- **Standard/Admin/Non-operational** users:
  - Activity-based timeout and optional refresh windows are **configurable** per profile.
  - Profiles define:
    - idle timeout duration,
    - maximum refresh age (if applicable),
    - warning/soft-expiry behavior,
    - forced logout behavior.

## Security and Compliance Implications (Operational Profiles)
Non-expiring sessions increase dwell-time risk from token theft/session hijacking. The proposal requires:
- explicit justification and documentation for each operational profile assignment,
- stricter monitoring of operational sessions (device/IP/user-agent change, unusual activity windows, manual revocation events),
- auditable events for session lifecycle changes (creation, role/profile switch, manual revoke, admin forced logout),
- immediate ability to invalidate all sessions for affected accounts/users.

## Technical Direction (Design-Level)
### Preserve Issue-Specific Concerns
- **Multi-window refresh races**: coordinate refresh across open tabs/windows per user session so only one active refresh is performed for a given logical user session.
- **Lockouts**: avoid invalidating sibling window tokens due to unrelated refresh attempts or stale state.
- **Frontend refresh storms**: debounce/coalesce refresh scheduling across windows and avoid repeated concurrent token refresh calls.

### Conceptual Policy Application
- Centralized profile resolver determines profile at session-check time.
- Token expiry checks evaluate:
  - policy type (operational vs non-operational),
  - last activity timestamp,
  - refresh state.
- Frontend should treat expired/non-expiring differently by profile instead of a single global timeout rule.
- Migration: default behavior remains backward-compatible; NOC/SOC require explicit profile assignment to unlock persistence.

## Acceptance Direction
- Validate with automated tests where available (strict TDD mode is active):
  - Backend unit/integration tests for policy resolution and expiry decisions by profile.
  - Backend simulation of concurrent refresh attempts to avoid lockout conditions.
  - Frontend tests for multi-window token refresh coordination and storm prevention.
- Manual acceptance scenarios if automation gaps remain:
  - NOC/SOC account remains authenticated across tabs/windows over long idle period.
  - Standard/admin account times out after configured inactivity and surfaces expected UX warning/logout behavior.
  - No user-facing refresh-loop behavior in active multi-tab sessions.

## Risks
1. **Operational-profile misclassification** can unintentionally grant persistence to non-operational users.
2. **Overly permissive default config** for non-operational timeouts.
3. **State synchronization complexity** across tabs leading to stale session state.
4. **Long-lived sessions** may reduce security if audit/invalidation processes are weak.

## Rollback Plan
- Keep policy resolution behind configuration/profile switches.
- If failures occur, disable operational profile persistence first and revert to bounded timeouts for all users.
- If multi-window coordination changes are unstable, temporarily force single-window refresh fallback behavior and reintroduce conservative token strategy.

## Proposed Rollout
1. Publish proposal and validate with security/product owners.
2. Build design/tasks from this policy model.
3. Implement with strict tests in backend and frontend.
4. Stage by profile: non-operational policy controls, then operational persistence controls, then cross-window coordination hardening.
