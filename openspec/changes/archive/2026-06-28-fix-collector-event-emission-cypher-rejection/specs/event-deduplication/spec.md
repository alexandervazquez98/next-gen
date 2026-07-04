# Delta for Event Deduplication

## ADDED Requirements

### Requirement: Defense-in-depth fallback preserves deduplication

Under the `cypher-param-fallback` capability, every Event writer protected by event deduplication SHALL attempt the narrow fallback when the primary collector-attributed query is rejected because `poll_collector_id` is not defined. The single-open-Event-per-`(ci_id, metric_id, event_type)` contract MUST remain unchanged when the fallback creates or updates the Event.

#### Scenario: Fallback creates the canonical Event under lock
- **GIVEN** a protected writer holds the advisory lock for one `(ci_id, metric_id, event_type)` triplet
- **WHEN** its primary Neo4j Event write is rejected for undefined `poll_collector_id`
- **THEN** the fallback query MUST run while preserving current matching semantics
- **AND** exactly one canonical OPEN Event MUST exist for the triplet

#### Scenario: Concurrent writers remain serialized during fallback
- **GIVEN** two protected writers target the same triplet concurrently
- **WHEN** the first writer falls back after the primary query is rejected
- **THEN** the second writer MUST remain serialized by the existing advisory-lock contract
- **AND** fallback MUST NOT introduce duplicate Events

#### Scenario: Happy path remains collector-attributed
- **GIVEN** the primary Event write succeeds
- **WHEN** no undefined `poll_collector_id` rejection occurs
- **THEN** the fallback MUST NOT run
- **AND** `poll_collector_id` MUST be persisted according to the existing collector-attribution requirement
