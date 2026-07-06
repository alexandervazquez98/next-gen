# Delta for Event Writer Coordination Observability

## MODIFIED Requirements

### Requirement: Coordination Invariants Documentation

The system MUST document operational invariants for advisory-lock coordination: all Event writers share the same PostgreSQL database identity, protected Event triplet lock acquisition remains transaction/session scoped for `pg_advisory_xact_lock`, deterministic sorted acquisition is preserved for batched writers, and CI/static guard coverage fails when protected lock acquisition moves outside approved session or wrapper paths.
(Previously: documented shared PostgreSQL identity, session/transaction scope, sorted acquisition, and #334 writer coverage, but did not require inline transaction/session-lifetime documentation or guard failure for unapproved lock movement.)

#### Scenario: Operator reviews invariants

- GIVEN an operator reads Event writer coordination documentation
- WHEN they verify deployment requirements
- THEN the documentation identifies shared PostgreSQL identity and session-lifetime requirements
- AND it explains that CI guards writer coverage and protected lock placement, not runtime contention

#### Scenario: Protected lock path documents transaction lifetime

- GIVEN a protected Event triplet lock is acquired for an Event writer
- WHEN maintainers review the acquisition or approved wrapper path
- THEN inline documentation states the lock is held only while the PostgreSQL session transaction remains open through the following Event write

#### Scenario: Static guard blocks unapproved lock movement

- GIVEN protected Event triplet lock acquisition is moved outside approved writer session or wrapper paths
- WHEN the CI/static guard runs
- THEN the guard MUST fail before the change is accepted

#### Scenario: Timeout policy remains unchanged

- GIVEN an Event writer waits for the shared advisory lock
- WHEN invariant documentation and static guard coverage are present
- THEN the system MUST NOT introduce fail-open, fail-closed, timeout, lock primitive, or transaction ownership behavior changes in this capability
