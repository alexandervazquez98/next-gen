# Delta for audit-logging

## ADDED Requirements

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

## MODIFIED Requirements

None. The existing audit schema, redaction contract, retention policy, and `AUDIT_VIEW` access control remain unchanged. The `CI_PROPOSAL_*` event types extend the catalog of audit events without modifying the shape of existing rows.

## REMOVED Requirements

None.

## RENAMED Requirements

None.

## ADDED Scenarios

Scenarios embedded in REQ-AUDIT-001 through REQ-AUDIT-005 above.

## MODIFIED Scenarios

None.