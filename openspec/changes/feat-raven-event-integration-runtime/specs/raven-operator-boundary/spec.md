# Spec delta: raven-operator-boundary

## ADDED Requirements

### REQ-BOUNDARY-1: Default dry-run for external writes

The system MUST default to dry-run/read-only for all Raven event writes from external sources.

#### Scenario: default dry-run
- GIVEN a next-gen (or any external source) attempts an event write to Raven
- WHEN the write is attempted without explicit operator approval
- THEN the write does NOT persist
- AND the system surfaces a recommendation instead

### REQ-BOUNDARY-2: Approval gate per write

The system MUST require explicit operator approval for every external write.

#### Scenario: approval flow
- GIVEN a recommendation is surfaced for an external write
- WHEN the operator approves the write
- THEN the write proceeds through the validated Raven API/CLI
- AND an audit row is emitted

#### Scenario: rejection flow
- GIVEN a recommendation is surfaced for an external write
- WHEN the operator rejects with a free-text reason
- THEN the write does NOT persist
- AND an audit row is emitted including the rejection reason

### REQ-BOUNDARY-3: Audit row completeness

The system MUST emit an audit row for every write or attempted write, containing actor, source, target event id, payload hash, timestamp, and before/after state.

#### Scenario: successful write audit
- GIVEN an approved write completes
- WHEN the audit row is written
- THEN it contains all required fields
- AND `payload_hash` is a deterministic hash of the write payload

#### Scenario: failed write audit
- GIVEN a write attempt fails (validation, network, etc.)
- WHEN the audit row is written
- THEN it contains the failure reason
- AND before/after state reflects that the write did not persist

### REQ-BOUNDARY-4: No bypass paths

The system MUST NOT allow external writes that bypass the operator boundary.

#### Scenario: direct DB write rejected
- GIVEN an external source attempts a direct DB or model write to Raven
- WHEN the write is attempted
- THEN the boundary rejects it
- AND surfaces an error indicating the boundary was violated

## MODIFIED Requirements

_None._

## REMOVED Requirements

_None._

## Cross-references

- UX pattern reference: #154 (stale-event reminders — recommendations section UX)
- Upstream slice: #445 (Raven normalizer routes writes through this boundary)
- Source proposal: `openspec/changes/feat-raven-event-integration-runtime/proposal.md`