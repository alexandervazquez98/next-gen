# Event Writer Lock Guard Specification

## Purpose

This capability defines a CI guard for production backend Neo4j `Event` emitters. It ensures emitters are inventoried, classified, and accompanied by explicit lock evidence metadata where lock protection is required.

## Requirements

### Requirement: Production Event Emitter Discovery

The system MUST discover production backend Python modules that create Neo4j `Event` nodes. Discovery MAY use simple source checks and MUST cover direct nodes, relationship/path creation, `CREATE`, `MERGE`, anonymous nodes, multiline Cypher, and `FOREACH`-wrapped Event creation. Discovery MUST exclude tests/support files and MUST NOT claim full control-flow proof.

#### Scenario: Existing production emitters are discovered

- GIVEN production modules contain Neo4j `Event` creation queries
- WHEN the guard runs during backend pytest
- THEN it MUST identify each production module that emits `Event` nodes
- AND it MUST ignore backend test modules.

#### Scenario: Relationship or wrapped Event creation is discovered

- GIVEN Cypher creates an `Event` through a relationship/path, anonymous node, multiline `MERGE`, or `FOREACH`
- WHEN static discovery scans production backend files
- THEN the module MUST be treated as an Event emitter.

### Requirement: Explicit Emitter Classification

Every discovered Event emitter MUST be classified as protected or exempt. Protected writers MUST include `backend/services/snmp_service.py`, `backend/engines/snmp_worker.py`, and `backend/polling/event_writer.py`. Exempt emitters MUST include `backend/engines/cli_worker.py` and `backend/services/backup_service.py` with non-empty rationale.

#### Scenario: All current emitters are classified

- GIVEN the current backend Event emitters are discovered
- WHEN the guard compares discovery with the registries
- THEN each discovered emitter MUST appear in exactly one classification.

### Requirement: Protected Writer Lock Evidence

Protected Event writer classifications MUST include explicit lock evidence metadata. Evidence MUST contain at least one non-empty reference to behavior test coverage, approved wrapper evidence, or equivalent documented evidence for the writer. CI MUST validate that each protected writer has present, non-empty evidence metadata; it MUST NOT rely on a fragile static AST/control-flow proof of every lock-before-write path.

When registering a new protected writer, maintainers MUST add or update either a behavior test reference or documented approved wrapper evidence. `_acquire_sorted_locks` is the approved production wrapper evidence for `backend/polling/event_writer.py`; `_acquire_unsorted_locks` MAY be an internal callee but MUST NOT be accepted as the approved direct writer wrapper.

#### Scenario: Protected writers include explicit evidence

- GIVEN a protected writer is registered
- WHEN the guard validates classifications during backend pytest
- THEN the writer MUST include non-empty lock evidence metadata
- AND the metadata MUST reference behavior test coverage, approved wrapper evidence, or equivalent documented evidence.

#### Scenario: Wrapper evidence is production-approved

- GIVEN `backend/polling/event_writer.py` is wrapper-based
- WHEN backend pytest validates protected writer evidence metadata
- THEN `_acquire_sorted_locks` MUST be accepted
- AND `_acquire_unsorted_locks` alone MUST NOT satisfy direct wrapper approval.

#### Scenario: Evidence metadata is missing

- GIVEN a protected writer classification has no evidence reference
- WHEN backend pytest runs the guard
- THEN the test MUST fail with a message naming the writer and missing evidence metadata.

### Requirement: CI Failure for Unclassified Emitters

The guard MUST fail CI when a newly added production backend Event emitter is not classified as protected or exempt.

#### Scenario: New emitter is unclassified

- GIVEN a production backend module starts creating Neo4j `Event` nodes
- WHEN the module is absent from both registries
- THEN backend pytest MUST fail and identify the unclassified module.

### Requirement: Registration Workflow Documentation

The backend test documentation MUST explain the Event writer guard, protected registration workflow, exempt registration workflow, and rationale expectations.

#### Scenario: Maintainer adds a protected writer

- GIVEN a maintainer adds a polling Event writer
- WHEN they read `backend/tests/README.md`
- THEN the documentation MUST tell them to register it as protected
- AND add or update behavior test references or approved wrapper evidence.
