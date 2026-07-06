# legacy-event-discriminator-audit Specification

## Purpose

Provide a read-only audit that classifies legacy `Event` rows for discriminator risk before any backfill, mutation, or runtime matching change is designed.

## Requirements

### Requirement: Read-only legacy event discriminator audit

The system MUST analyze event-like records without writing to the database, backfilling data, applying admin actions, or changing runtime event matching semantics.
The system MUST produce a domain result model that can be serialized into Markdown and JSON.

#### Scenario: Audit run leaves data unchanged

- GIVEN legacy event records with missing discriminator fields
- WHEN the audit runs
- THEN it MUST return findings only
- AND it MUST NOT mutate rows, trigger backfill, or alter matching behavior.

#### Scenario: Same result model drives both outputs

- GIVEN one completed audit result
- WHEN Markdown and JSON are generated
- THEN both outputs MUST describe the same findings and summary counts
- AND the outputs MUST be deterministic for the same input set.

### Requirement: Classify missing discriminator fields

The system MUST classify each legacy row for missing `event_type`, `failure_family`, and `source_protocol` independently.
Missing values MUST be reported as explicit findings rather than inferred silently.

#### Scenario: Missing fields are reported distinctly

- GIVEN a row missing `event_type` and `source_protocol`
- WHEN the audit runs
- THEN the result MUST include findings for both missing fields
- AND the findings MUST identify the affected row.

#### Scenario: Present fields are not flagged

- GIVEN a row with all three discriminator fields populated
- WHEN the audit runs
- THEN the row MUST NOT be reported as missing those fields.

### Requirement: Flag legacy-null ambiguity boundaries

The system MUST emit explicit ambiguous findings when legacy-null data could represent threshold or availability risk, or when the boundary between generic collection failure and SNMP no-response cannot be determined safely.
The system MUST label these findings as ambiguous rather than definitive.

#### Scenario: Threshold or availability nulls become ambiguous findings

- GIVEN a legacy row where null discriminator values may reflect threshold or availability semantics
- WHEN the audit runs
- THEN it MUST emit an ambiguous finding
- AND it MUST NOT assign a concrete discriminator.

#### Scenario: Generic collection failure versus SNMP no-response is unresolved

- GIVEN a legacy row that could be either generic collection failure or SNMP no-response
- WHEN the audit runs
- THEN it MUST emit an ambiguous boundary finding
- AND it MUST NOT collapse both cases into one definitive class.

### Requirement: Deterministic reporting for downstream reuse

The system MUST expose the audit result model for future admin UI reuse, while keeping Slice 1 free of admin UI and admin API surface.
The system MUST generate stable Markdown and JSON from the same ordered findings.

#### Scenario: Ordered findings remain stable across formats

- GIVEN the same input rows and classifier rules
- WHEN the audit is executed twice
- THEN the Markdown and JSON outputs MUST preserve the same finding order and identifiers.

#### Scenario: Slice 1 exposes no admin surface

- GIVEN the audit capability is implemented
- WHEN the system is inspected for this slice
- THEN no admin UI route or admin mutation API MUST be required for the capability.
