# Time Sync Skew Health Specification

## Purpose

Define runtime telemetry and operator guidance for backend-to-Neo4j clock skew without changing existing liveness, readiness, or system-status HTTP availability semantics.

## Requirements

### Requirement: System Status Time Sync Payload

`GET /api/system/status` MUST include a `time_sync` section reporting backend-vs-Neo4j clock skew, status thresholds, and measurement metadata.

The `time_sync` payload SHALL expose at least the measured skew in milliseconds when available, the evaluated status, the compared sources, and warning/critical threshold metadata.

#### Scenario: OK skew is reported
- GIVEN Neo4j time is available and backend-vs-Neo4j skew is below the warning threshold
- WHEN a client requests `/api/system/status`
- THEN the response includes `time_sync.status` as `OK`
- AND the payload includes the measured skew and configured thresholds

#### Scenario: Warning skew is reported
- GIVEN Neo4j time is available and backend-vs-Neo4j skew meets or exceeds the warning threshold but is below the critical threshold
- WHEN a client requests `/api/system/status`
- THEN the response includes `time_sync.status` as `WARNING`
- AND existing system status fields remain present

#### Scenario: Critical skew is reported
- GIVEN Neo4j time is available and backend-vs-Neo4j skew meets or exceeds the critical threshold
- WHEN a client requests `/api/system/status`
- THEN the response includes `time_sync.status` as `CRITICAL`
- AND the response remains an informational system-status response

### Requirement: Failure Isolation

Neo4j time-query failure MUST return `time_sync.status` as `UNKNOWN` and MUST NOT change liveness, readiness, or `/api/system/status` HTTP behavior.

The system SHALL preserve existing Neo4j/PostgreSQL connectivity fields independently from the time-sync telemetry result.

#### Scenario: Neo4j time query is unavailable
- GIVEN the Neo4j time query fails or returns an unusable value
- WHEN a client requests `/api/system/status`
- THEN the response includes `time_sync.status` as `UNKNOWN`
- AND the system-status endpoint uses its existing HTTP behavior

#### Scenario: Healthcheck semantics are unchanged
- GIVEN clock skew is `WARNING`, `CRITICAL`, or `UNKNOWN`
- WHEN liveness, readiness, or system-status checks are evaluated
- THEN their pass/fail and HTTP status semantics are not changed by `time_sync`

### Requirement: Operator Time Synchronization Guidance

Operator documentation MUST explain host-level clock synchronization verification and remediation for NTP, chrony, and systemd-timesyncd.

The documentation MUST state that container timezone configuration such as `TZ=UTC` is not host clock synchronization, and the system MUST NOT require privileged in-container NTP, chrony, or systemd management.

#### Scenario: Operator verifies host clock sync
- GIVEN an operator investigates `WARNING` or `CRITICAL` skew
- WHEN they follow the time-sync documentation
- THEN they can verify host NTP/chrony/systemd-timesyncd state and identify drift remediation steps

#### Scenario: Container NTP is not prescribed
- GIVEN an operator reads deployment guidance
- WHEN they review container time-sync expectations
- THEN the guidance states containers inherit host time
- AND it does not require privileged in-container time synchronization

### Requirement: Derivable Test Coverage

Implementation tasks MUST include automated backend tests or explicit test cases derivable from this specification for `OK`, `WARNING`, `CRITICAL`, and database-unavailable/`UNKNOWN` paths.

#### Scenario: Status mapping tests are planned
- GIVEN implementation tasks are created for this change
- WHEN test coverage is planned
- THEN tests cover `OK`, `WARNING`, `CRITICAL`, and Neo4j time-query failure paths
