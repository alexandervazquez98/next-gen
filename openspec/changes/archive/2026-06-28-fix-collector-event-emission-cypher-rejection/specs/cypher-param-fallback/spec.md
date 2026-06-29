# Cypher Param Fallback Specification

## Purpose

Define a narrow Event-write fallback for Neo4j `ClientError` rejections where `$poll_collector_id` is reported as undefined, preserving Event emission while keeping the primary collector-attributed path unchanged.

## Requirements

### Requirement: Specific undefined-parameter trigger

Event-writing `session.run(...)` calls SHALL execute the fallback only when `neo4j.exceptions.ClientError` contains both `poll_collector_id` and `not defined` in the error message.

#### Scenario: Matching production rejection triggers fallback
- **GIVEN** an Event-writing `session.run(...)` sets `poll_collector_id`
- **WHEN** Neo4j raises `ClientError` with `Variable poll_collector_id not defined`
- **THEN** the writer MUST enter the `cypher-param-fallback` path
- **AND** the surrounding polling cycle MUST continue after fallback execution

### Requirement: Fallback writes Event without collector parameter

The fallback query MUST create or update the matching Event while omitting `poll_collector_id`.

#### Scenario: Availability down Event survives primary rejection
- **GIVEN** an ICMP availability failure needs an Event with id, ci_id, metric_id, status, severity, message, event_type, and timestamps
- **WHEN** the primary query is rejected for undefined `poll_collector_id`
- **THEN** the fallback query MUST create or update the Event without `poll_collector_id`
- **AND** required Event fields MUST still be persisted

### Requirement: Non-matching Cypher errors propagate

Any Cypher error that does not match the exact undefined `poll_collector_id` condition MUST NOT trigger fallback and MUST propagate as before.

#### Scenario: Different syntax error is not retried
- **GIVEN** an Event-writing query raises `ClientError` for a syntax issue unrelated to `poll_collector_id not defined`
- **WHEN** the writer handles the exception
- **THEN** no fallback query MUST run
- **AND** the original error MUST be raised to the existing caller path

### Requirement: Protected Event writer coverage

The fallback SHALL protect every affected Event-writing `session.run(...)` site in `backend/engines/snmp_worker.py` lines 310-349, 384-424, 437-471, 492-527, 540-580, and the equivalent `backend/services/snmp_service.py` site at 498-504.

#### Scenario: All affected writers use the fallback guard
- **GIVEN** any listed Event writer executes a query that references `poll_collector_id`
- **WHEN** Neo4j rejects that query with the matching undefined-variable error
- **THEN** that writer MUST attempt its matching fallback query
- **AND** no listed writer MAY remain unprotected

### Requirement: Diagnostic observability

When fallback triggers, the system MUST log an ERROR containing `cypher-param-fallback`, the original query text, the parameters dict, and the stack trace.

#### Scenario: Operator can count fallback incidents
- **GIVEN** a fallback is triggered
- **WHEN** logs are inspected
- **THEN** operators MUST be able to grep `cypher-param-fallback`
- **AND** the log entry MUST include query text, params, and stack trace

### Requirement: Error path is visible, not silent

Fallback MUST NOT silently swallow the primary failure; it MAY allow the surrounding cycle to continue only after emitting diagnostic context.

#### Scenario: Cycle continues with visible failure evidence
- **GIVEN** fallback succeeds after the primary query fails
- **WHEN** the polling cycle continues
- **THEN** the original failure MUST remain visible in ERROR logs
- **AND** Event creation MUST take precedence over collector attribution
