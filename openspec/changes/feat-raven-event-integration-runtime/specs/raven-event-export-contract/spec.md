# Spec delta: raven-event-export-contract

## ADDED Requirements

### REQ-EXPORT-1: Stable versioned JSON shape

The system MUST expose a versioned JSON export shape for events intended for Raven ingestion.

#### Scenario: required fields present
- GIVEN any event in OPEN / ACK / RECOVERED status
- WHEN the principal calls the export endpoint
- THEN the response includes `event.id`, `ci_ref` (with at least `id`), `created_at`, `severity`, `status`, `type`, `raw`
- AND the shape matches the documented schema

#### Scenario: last_seen preserved
- GIVEN an event with `last_seen != created_at`
- WHEN the export returns the event
- THEN `last_seen` is preserved inside `raw` or details
- AND never replaces the initial observed time (`created_at`)

### REQ-EXPORT-2: Backward-compatibility policy

The system MUST follow an additive-within-major, removal-requires-new-major policy for the export contract.

#### Scenario: additive change is allowed
- GIVEN a new optional field is added to the export shape
- WHEN a v1.0 client consumes a v1.1 export
- THEN the client ignores the unknown field without error

#### Scenario: removal requires new major
- GIVEN a field is removed from the export shape
- WHEN the change is shipped
- THEN the export version moves to v2 (or next major)
- AND the v1 shape remains available until v1 sunset

### REQ-EXPORT-3: Existing /api/events shape unchanged

The system MUST NOT change the existing `/api/events` response shape.

#### Scenario: /api/events backward-compatible
- GIVEN the export contract is added
- WHEN the principal calls `/api/events`
- THEN the response shape is byte-equivalent (or field-compatible) to before the export contract was added

### REQ-EXPORT-4: Suitable for CLI and HTTP consumption

The export surface MUST be consumable by both `raven event ingest --source next-gen --stdin` and `--file <path>`.

#### Scenario: HTTP REST export
- GIVEN the principal has `CMDB_READ` or equivalent
- WHEN they call `GET /api/events/export`
- THEN the response is a streamable JSON shape
- AND the body is parseable by the Raven normalizer

#### Scenario: CLI dump export
- GIVEN the principal runs `next-gen events dump --status=ACTIVE`
- THEN the output is line-delimited or single-document JSON
- AND it matches the same shape as the HTTP export

## MODIFIED Requirements

_None._

## REMOVED Requirements

_None._

## Cross-references

- Downstream slice: #445 (Raven normalizer consumes this contract)
- Source proposal: `openspec/changes/feat-raven-event-integration-runtime/proposal.md`