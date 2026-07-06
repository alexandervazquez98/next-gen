# Delta for legacy-event-backfill-local-evidence

## ADDED Requirements

### Requirement: Seed marker-scoped smoke fixtures for local validation
The system MUST seed uniquely marked local/shared Neo4j smoke fixture `Event` records using `issue155_smoke=true` and a unique run id.
The system MUST seed fixtures that cover expected safe, ambiguous, and no-touch recommendation buckets.
The system MUST keep the seeded scope isolated to the local/shared environment.

#### Scenario: Seeded fixtures cover all buckets
- GIVEN a unique run id has been selected for the validation run
- WHEN smoke fixtures are seeded
- THEN each seeded `Event` record MUST include `issue155_smoke=true` and the run id
- AND the fixture set MUST include safe, ambiguous, and no-touch cases

#### Scenario: Seed scope remains local
- GIVEN the validation run targets the shared local Neo4j environment
- WHEN fixtures are seeded
- THEN no production records are touched
- AND no unmarked records are required for the validation slice

### Requirement: Validate the existing read-only report against seeded fixtures
The system MUST run the existing read-only recommendation report against the seeded fixtures.
The system MUST persist Markdown and JSON evidence for the report output.
The system MUST validate expected-versus-actual classification for each seeded fixture.

#### Scenario: Report classifications match expectations
- GIVEN seeded fixtures exist for all expected buckets
- WHEN the read-only recommendation report runs
- THEN the Markdown and JSON evidence MUST record the report output
- AND the actual classifications MUST match the expected bucket mapping

#### Scenario: Classification mismatch is visible
- GIVEN a seeded fixture is classified into the wrong bucket
- WHEN evidence validation runs
- THEN the mismatch MUST be recorded in Markdown and JSON evidence
- AND the run MUST be marked invalid for planning use

### Requirement: Always clean up seeded fixtures and verify no markers remain
The system MUST delete all fixtures seeded for the run, including on failure.
The system MUST verify that no `issue155_smoke=true` records remain after cleanup.
The system MUST persist cleanup verification evidence.

#### Scenario: Cleanup succeeds after report execution
- GIVEN smoke fixtures were seeded for a unique run id
- WHEN cleanup runs after validation
- THEN all `issue155_smoke=true` records for that run id MUST be removed
- AND a post-cleanup check MUST confirm no marked records remain

#### Scenario: Cleanup runs after failure
- GIVEN the report or validation fails partway through
- WHEN failure handling runs
- THEN cleanup MUST still execute for the seeded run id
- AND the post-cleanup verification MUST be persisted

### Requirement: Prevent unsafe mutation, environment creation, and backfill paths
The system MUST NOT mutate production data or draw production conclusions from the smoke run.
The system MUST NOT create a new Docker, test, or isolated Neo4j environment.
The system MUST NOT invoke any `--apply`, backfill, or migration path during this validation.

#### Scenario: Unsafe path is blocked
- GIVEN a validation request includes an apply or migration flag
- WHEN the run is prepared
- THEN the system MUST refuse the request
- AND the evidence MUST state that only read-only local validation is allowed

#### Scenario: No production conclusion is claimed
- GIVEN the local smoke validation completes successfully
- WHEN the result is summarized
- THEN the summary MUST limit conclusions to classifier behavior on the seeded fixtures
- AND it MUST NOT claim production safety or production-scale coverage
