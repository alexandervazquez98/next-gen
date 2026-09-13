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

### Requirement: Authentication session lifecycle event capture

The system MUST capture session lifecycle events `session.activity_recorded` and `session.idle_expired` emitted by the backend auth/session activity recorder, with allow-listed context keys (`session_id`, `user_id`, `policy_profile`, `throttle_seconds`, `activity_anchor`) and explicit exclusion of raw tokens, cookies, authorization headers, and request bodies.

The `session.activity_recorded` event SHALL be emitted only when a refresh-token row is updated by the throttled `record_session_activity` recorder. The `session.idle_expired` event SHALL be emitted when refresh verification rejects a session for inactivity.

#### Scenario: Activity recording emits a safe audit row

- GIVEN an authenticated request bumps a standard session via the throttled recorder
- WHEN the recorder commits a `refresh_tokens.last_activity_at` update
- THEN an audit event with `event_type = session.activity_recorded` SHALL be persisted
- AND the audit context SHALL include `session_id`, `user_id`, `policy_profile`, `throttle_seconds`, and `activity_anchor`
- AND the audit context SHALL NOT include raw refresh or access tokens, cookies, or authorization headers.

#### Scenario: Idle expiry emits a safe audit row

- GIVEN a refresh request arrives for a session whose activity anchor is older than the configured timeout
- WHEN the router rejects the request with HTTP 401
- THEN an audit event with `event_type = session.idle_expired` SHALL be persisted before the response is sent
- AND the audit context SHALL include `session_id`, `user_id`, `policy_profile`, and `activity_anchor`
- AND no Prometheus metric SHALL be created for this event.

#### Scenario: Sensitive keys are stripped from session lifecycle context

- GIVEN a caller attempts to record a session lifecycle event with a context that includes `token`, `cookies`, `authorization`, `raw_body`, or `refresh_token`
- WHEN the audit service processes the event
- THEN those keys SHALL be stripped before persistence
- AND the allow-listed keys SHALL remain in the persisted context.
### Requirement: REQ-AUDIT-001 — `CI_PROPOSAL_*` event types and required context fields

The system MUST persist audit events for the CMDB proposal lifecycle with `event_type ∈ {CI_PROPOSAL_CREATE, CI_PROPOSAL_APPROVE, CI_PROPOSAL_REVOKE}` and a structured `context` payload that includes at minimum `proposal_id`, `proposed_by`, `actor_role`, `previous_state`, `next_state`, `version`, and `applied_manifest_summary`. The system MUST emit exactly one row per state transition and MUST NOT emit duplicate rows for a single transition.

#### Scenario: CI_PROPOSAL_CREATE row is written on submit

- GIVEN an agent successfully submits a manifest
- WHEN the audit service persists
- THEN exactly one row with `event_type="CI_PROPOSAL_CREATE"`, `previous_state=null`, `next_state="DRAFT"`, `version=1` MUST exist.

#### Scenario: CI_PROPOSAL_APPROVE row is written on approve

- GIVEN a reviewer successfully approves a DRAFT proposal
- WHEN the audit service persists
- THEN exactly one row with `event_type="CI_PROPOSAL_APPROVE"`, `previous_state="DRAFT"`, `next_state="APPROVED"`, `version=2` MUST exist.

#### Scenario: CI_PROPOSAL_REVOKE row is written on revoke

- GIVEN a reviewer (or system TTL) revokes a proposal
- WHEN the audit service persists
- THEN exactly one row with `event_type="CI_PROPOSAL_REVOKE"`, `previous_state` reflecting the prior state, `next_state="REVOKED"` MUST exist
- AND for system-driven revokes, `actor_role="SYSTEM"` MUST be set.

### Requirement: REQ-AUDIT-002 — Approved proposals link to the resulting :CI and record the actual written attributes

When an approve event is recorded, the audit context MUST include `resulted_ci_id` referencing the new `:CI` node and `applied_manifest_attributes` containing the actual attribute set that was persisted to Neo4j (not the agent-submitted manifest). The system MUST record the live values so that audit replay reflects what the graph actually holds, including any backend normalizations.

#### Scenario: Approve audit row links to the resulting :CI

- GIVEN a successful approve that creates `:CI {id: "CI-NEW"}`
- WHEN the audit row is written
- THEN `context.resulted_ci_id` MUST equal `"CI-NEW"`
- AND `context.applied_manifest_attributes` MUST contain the actual `:CI` property values.

#### Scenario: Backend-normalized fields are reflected in the audit

- GIVEN the backend normalizes `status` to `"OK"` regardless of what the manifest sent
- WHEN the audit row is written
- THEN `context.applied_manifest_attributes.status` MUST equal `"OK"` (the value the graph holds)
- AND it MUST NOT equal the raw submitted value if the backend overrode it.

### Requirement: REQ-AUDIT-003 — Secret redaction in audit context

The system MUST redact secret-like fields from any persisted audit context, including but not limited to: `snmp.community`, `snmp.authKey`, `snmp.privKey`, and any field whose key matches `*key|*token|*secret|*password` (case-insensitive). Redacted values MUST be persisted as `"<REDACTED>"` and the original value MUST NOT appear in audit storage, log files, or downstream snapshots.

#### Scenario: SNMP community string is redacted in audit

- GIVEN a manifest with `snmp.community = "public-ro-xyz"`
- WHEN an audit row is written for CREATE, APPROVE, or REVOKE
- THEN the persisted `context.applied_manifest_summary` MUST show `"community": "<REDACTED>"`.

#### Scenario: Token, password, and key fields are redacted

- GIVEN a manifest that contains arbitrary keys matching `*token|*password|*key|*secret` (case-insensitive)
- WHEN the audit row is written
- THEN every matched key's value MUST be stored as `"<REDACTED>"`.

#### Scenario: Redaction applies to free-form metadata too

- GIVEN a manifest with `metadata: { api_token: "...", rack: "R12" }`
- WHEN the audit row is written
- THEN `metadata.api_token` MUST be stored as `"<REDACTED>"`
- AND `metadata.rack` MUST be stored verbatim.

### Requirement: REQ-AUDIT-004 — Concurrent approval produces exactly one APPROVE row

The system MUST guarantee that a `CI_PROPOSAL_APPROVE` row is persisted at most once per transition, even under concurrent attempts. The optimistic-version check MUST happen before the audit write so the losing writer does not produce a second audit row.

#### Scenario: Two concurrent approves produce one audit row

- GIVEN a DRAFT proposal at version=1
- WHEN two reviewers both POST approve with `version=1` near-simultaneously
- THEN exactly one HTTP 200 response MUST occur
- AND exactly one `CI_PROPOSAL_APPROVE` row MUST be persisted
- AND the other request MUST receive HTTP 409 with no audit write.

### Requirement: REQ-AUDIT-005 — Proposal audit events honor the existing schema-version and access control contracts

The system MUST persist proposal audit events with the existing `schema_version` field and MUST gate read access to them behind the existing `AUDIT_VIEW` permission, consistent with all other audit event types in this slice.

#### Scenario: Proposal audit rows are visible only to AUDIT_VIEW holders

- GIVEN an audit table containing `CI_PROPOSAL_*` rows
- WHEN a user without `AUDIT_VIEW` queries the audit API
- THEN no proposal audit entries MUST be returned.

