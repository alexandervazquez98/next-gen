# Audit Logging Specification

## Purpose

Deliver a first-slice user audit surface that records security- and change-sensitive actions for investigation and operations, while excluding sensitive payload data and limiting scope to the approved first-slice actions.

## Requirements

### Requirement: Audit event schema, persistence, and sensitive-data exclusion

The system MUST persist all first-slice audit events in a dedicated audit event store using a versioned schema that includes event type, actor identity, action context, outcome, timestamp, request metadata, and an explicit safe failure reason when applicable.
The system MUST NOT persist passwords, bearer tokens, session tokens, raw request bodies, or any other field flagged as sensitive secrets.

#### Scenario: Auth failure records redact sensitive inputs

- GIVEN an authentication failure request includes sensitive fields like password or token in the request payload
- WHEN an audit event is written for the failure
- THEN the stored event SHALL include `event_type`, `actor` (if known), `outcome`, `ip`, and `user_agent`
- AND the stored event SHALL NOT contain the submitted password, token, request body, or raw secret material.

#### Scenario: Versioned event schema is consistent

- GIVEN the audit logger receives events from auth and critical-change operations
- WHEN events are stored and returned
- THEN all stored records MUST include a schema version identifier
- AND consumers MUST be able to deserialize required fields without relying on undocumented ad-hoc keys.

### Requirement: Authentication lifecycle event capture

The system MUST capture authentication lifecycle events for `LOGIN_SUCCESS`, `LOGIN_FAILURE`, and `LOGOUT`, including at least actor context (where available), IP address, user-agent, event timestamp, and safe reason for failures.

#### Scenario: Login failure is audit-captured with context

- GIVEN a failed login attempt occurs
- WHEN audit logging is attempted for the event
- THEN an audit record MUST be created with `event_type = LOGIN_FAILURE`, the resolved actor identity if available, IP, user agent, and a non-sensitive failure reason.

#### Scenario: Successful login and logout are traceable

- GIVEN a successful login or logout occurs by an authenticated actor
- WHEN the event is emitted
- THEN an audit record MUST be created with outcome success and the actor identity, event timestamp, target actor context, IP, and user agent.

### Requirement: Critical change event capture and denied attempts

The system MUST capture first-slice critical changes for create/update/delete of CIs, users, roles, permissions, and critical system configuration, including denied and failed attempts when context is attributable to a user.

#### Scenario: Critical change attempts are captured with outcomes

- GIVEN an actor attempts any first-slice critical action
- WHEN the action is allowed or denied
- THEN one audit record MUST be written with action target, event outcome (`SUCCESS`, `DENIED`, or `VALIDATION_FAILURE`), and concise non-sensitive reason on failure/denial.

#### Scenario: Non-critical actions remain out of slice

- GIVEN an action modifies a non-critical entity outside first-slice scope
- WHEN the action completes
- THEN the system MUST NOT require mandatory audit capture in this slice.

### Requirement: `AUDIT_VIEW` access control for API and UI

The system MUST expose audit-log read endpoints and UI screens only to principals granted `AUDIT_VIEW`, and this permission is global (non-tenant/non-region scoped) in the first slice.

#### Scenario: User with `AUDIT_VIEW` can read audit data

- GIVEN a user session with `AUDIT_VIEW`
- WHEN the user opens the audit UI or calls the audit log API
- THEN access MUST be granted to view audit entries.

#### Scenario: User without `AUDIT_VIEW` is denied

- GIVEN a user session without `AUDIT_VIEW`
- WHEN the user opens the audit UI route or calls the audit log API
- THEN access MUST be denied and no audit entries or sensitive metadata SHOULD be returned.

### Requirement: Filterable audit log API and table behavior

The system MUST provide a query API and corresponding UI table that supports server-side filtering by at minimum: time range, actor, event type, and outcome.
The table MUST include columns for actor, event type, target, timestamp, outcome, IP/context, and source.

#### Scenario: Combined filters narrow results

- GIVEN multiple audit events in the store
- WHEN the API receives valid filters for time range, actor, and outcome
- THEN the response MUST contain only matching events and preserve pagination/sort semantics.

#### Scenario: UI table supports inspectability

- GIVEN filtered API responses are available
- WHEN a user with `AUDIT_VIEW` opens the audit log table
- THEN the UI MUST render actor, event type, target, timestamp, outcome, IP/context, and source for each row
- AND display no empty/undefined-only placeholder when sensitive fields are intentionally omitted.

### Requirement: 90-day retention cleanup

The system MUST retain audit events for 90 days by default in this slice, with no per-tenant or per-module retention exceptions.
A cleanup process MUST remove records strictly older than the retention window.

#### Scenario: Older-than-window events are purged

- GIVEN an audit event older than 90 days exists
- WHEN the retention cleanup job runs
- THEN that event MUST be removed from active query results and storage.

#### Scenario: Recent events remain available

- GIVEN an audit event within 90 days exists
- WHEN cleanup runs
- THEN that event MUST remain queryable.
