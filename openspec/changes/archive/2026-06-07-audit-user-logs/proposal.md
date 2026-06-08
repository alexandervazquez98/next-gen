# Add Dedicated User Audit Logging with Filterable Audit Table

Enable a dedicated user-audit capability that captures high-value security and change events, stores them for 90 days, and exposes a filterable audit log interface secured by a new `AUDIT_VIEW` permission.

## Intent
- Reduce blind spots in security and change tracking after KPI-chain merge by tracking user-auth and critical system/user configuration actions independently.
- Provide a first-class, permission-gated audit surface without forcing admin-only visibility.

## Problem
Current logging lacks a productized, dedicated user audit trail for sensitive account/configuration behavior, making it hard to investigate security incidents and change provenance consistently.

## Scope (First Slice)
- Capture audit events for:
  - Authentication lifecycle: `LOGIN_SUCCESS`, `LOGIN_FAILURE`, `LOGOUT`.
  - Critical entity/config changes: CIs, users, roles, permissions, and critical system configuration.
  - Critical change failures: attempts denied by policy or validation, where user context is relevant.
- Implement dedicated permission `AUDIT_VIEW` and gate audit-log read access to it.
- Persist audit records with retention policy of **90 days**.
- Deliver initial UI: filterable audit log table (for now: actor, event type, target, timestamp, outcome, IP/context, source).

## Affected areas
- Backend audit event model/contract for standardized event schema and new event categories.
- Backend retention/cleanup job and indexing strategy suitable for 90-day query/filtering.
- RBAC/authorization checks for audit log access (`AUDIT_VIEW`).
- Backend API for listing + filtering audit logs.
- Frontend audit log view with filter controls and server-side pagination/sorting as applicable.

## Non-goals / Out of Scope
- **Explicitly out-of-scope:**
  - Exhaustive all-module CRUD auditing (non-critical modules are excluded in first slice).
  - Analytics dashboards beyond the filterable table view.
  - Tamper-proof/WORM storage semantics unless compliance/legal requirement is formally added later.
  - Audit export/download workflows unless product direction later adds this need.
  - Real-time alerting/integration hooks in this first slice.

## First-slice Boundaries
- Only events listed in *Scope* are required initially.
- No global re-architecture of logging framework.
- No changes to existing admin-only workflows except introducing/using `AUDIT_VIEW`.
- No custom retention policies per tenant/module in first slice (single global 90-day retention).

## Acceptance Criteria
- Given a user with `AUDIT_VIEW`, they can query/read audit entries via UI and API.
- Given a user without `AUDIT_VIEW`, access to audit logs/UI/API is denied.
- Login/logout/auth-failure and critical change events are recorded with actor identity and key action context.
- Audit retention keeps records for 90 days and enforces cleanup after the window.
- Audit table supports meaningful filtering (at minimum by time range, actor, event type, and outcome).
- Event schema is versioned/consistent enough for later consumer expansion.

## Risks
- **Scope creep:** pressure to include non-critical modules before policy and schema stabilization.
- **PII/security exposure:** over-collection of request payload/context can leak sensitive data.
- **Permission sprawl:** `AUDIT_VIEW` mis-assigned could either overexpose or hide logs.
- **Storage growth/perf:** missing indexes or cleanup lag could degrade list performance near retention boundary.

## Rollback Plan
- Feature-flag or route-level gating can disable UI/API exposure if needed.
- If retention/collection causes operational impact, temporarily narrow event capture to auth events only and defer critical-change events.
- Remove/disable `AUDIT_VIEW` checks and migrate users back to existing admin controls if required while keeping data model migration reversible.

## PR slicing note
- This proposal is intentionally scoped for a manageable first PR chain; first-slice implementation is expected to stay near or below the review budget by focusing strictly on critical events + table UI.
- If event wiring touches many modules, split by domain (auth/events, RBAC changes, UI/listing endpoint) into linked PRs.

## Proposal question round
To reduce ambiguity before spec/design, please confirm/adjust if needed:
1. Which user actions inside CI/user/role/permission/system-config workflows are truly *critical* for initial event coverage?
2. For auth failures, should repeated lockout/brute-force outcomes and client metadata (IP/UA) be mandatory fields in first slice?
3. Should audit logs be globally visible by a central role (`AUDIT_VIEW`) or scoped by tenant/region in this initial implementation?
4. Do failed writes/read attempts (authorization denied) count as audit-worthy in slice 1, or only successful critical actions?

### Assumptions used in this proposal
- New `AUDIT_VIEW` permission is available before or as part of this work.
- Backend supports reliable actor identity resolution and request context capture for audit entries.
- A dedicated table-based UI can deliver the minimum viable audit experience for internal operations.

If any of the above assumptions are incorrect, please correct them before spec phase or request a second question round.