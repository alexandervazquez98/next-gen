# Event Writer Coordination Observability Specification

## Purpose

Define runtime observability for Event writer PostgreSQL advisory-lock coordination without changing Event write, deduplication, blocking, retry, or healthcheck semantics.

## Requirements

### Requirement: Lock Acquisition Metrics

The system MUST maintain lightweight in-process metrics for shared Event triplet lock acquisition, including acquisition count and wait-duration distribution by bounded writer/context labels.

#### Scenario: Successful acquisition is measured

- GIVEN an Event writer acquires the shared triplet lock
- WHEN the acquisition completes
- THEN the metrics include one additional acquisition
- AND the observed wait duration is recorded for that writer context

#### Scenario: High-cardinality identifiers are excluded

- GIVEN lock metrics are recorded for a CI, metric, and event type triplet
- WHEN metric labels are produced
- THEN raw triplet identifiers MUST NOT be required as default metric labels

### Requirement: Structured Slow-Lock Logging

The system MUST emit structured slow-lock logs when acquisition wait time crosses the configured INFO threshold, defaulting to 250ms.

#### Scenario: Slow lock is logged

- GIVEN lock acquisition takes longer than the configured INFO threshold
- WHEN the lock is acquired
- THEN a structured log entry records writer context and wait duration
- AND Event write semantics remain unchanged

#### Scenario: Normal wait avoids noisy logs

- GIVEN lock acquisition completes below the configured INFO threshold
- WHEN the lock is acquired
- THEN the system SHOULD avoid emitting an INFO slow-lock log

### Requirement: Derived Lock Alert State

The system MUST derive alert state from in-process lock wait metrics without degrading liveness or readiness checks.

#### Scenario: Warning threshold is exceeded

- GIVEN the configured observation window has lock wait p95 above 1s
- WHEN alert state is evaluated
- THEN the system reports WARNING for lock coordination

#### Scenario: Critical threshold is exceeded

- GIVEN the configured observation window has lock wait p99 above 5s
- WHEN alert state is evaluated
- THEN the system reports CRITICAL for lock coordination

#### Scenario: Alert state does not fail healthchecks

- GIVEN lock alert state is WARNING or CRITICAL
- WHEN application health or readiness is evaluated
- THEN the result MUST NOT change solely because of lock contention observability

### Requirement: Coordination Invariants Documentation

The system MUST document operational invariants for advisory-lock coordination: all Event writers share the same PostgreSQL database identity, lock acquisition remains session/transaction scoped, deterministic sorted acquisition is preserved for batched writers, and issue #334 remains the complementary CI guard for future writer coverage.

#### Scenario: Operator reviews invariants

- GIVEN an operator reads Event writer coordination documentation
- WHEN they verify deployment requirements
- THEN the documentation identifies shared PostgreSQL identity and session-lifetime requirements
- AND it explains that #334 guards writer coverage in CI, not runtime contention

#### Scenario: Timeout policy remains unchanged

- GIVEN an Event writer waits for the shared advisory lock
- WHEN observability is enabled
- THEN the system MUST NOT introduce fail-open, fail-closed, or timeout behavior in this capability

## ADDED Requirements

### Requirement: Recovered Stale Gauge

The system MUST maintain an `events_recovered_stale_total` gauge counting RECOVERED Event rows older than `stale_after_seconds` without closure. The default `stale_after_seconds` MUST be 3600 seconds. `GET /api/system/status` MUST expose the value at `collector.prune.recovered_stale`.

#### Scenario: Stale recovered rows are surfaced

- GIVEN RECOVERED rows exceed the configured stale age and remain unclosed
- WHEN system status is requested
- THEN collector.prune.recovered_stale reports the current stale-row gauge

#### Scenario: Fresh rows are excluded

- GIVEN RECOVERED rows are younger than stale_after_seconds
- WHEN the prune observability snapshot is evaluated
- THEN those rows do not increase events_recovered_stale_total

### Requirement: Pruned Batch Counter

The system MUST maintain an `events_pruned_total` counter that increments once for each scheduler tick whose prune operation closes at least one row. `GET /api/system/status` MUST expose the value at `collector.prune.pruned`.

#### Scenario: Successful batch increments once

- GIVEN a scheduler tick closes one or more RECOVERED rows
- WHEN the tick completes
- THEN events_pruned_total increases by exactly one and collector.prune.pruned exposes it

#### Scenario: Empty batch does not increment

- GIVEN a scheduler tick closes no rows
- WHEN the tick completes
- THEN events_pruned_total remains unchanged

### Requirement: Prune Observability Snapshot

`get_event_prune_observability_snapshot()` MUST return the prune observability dataclass shape containing `events_recovered_stale_total` and `events_pruned_total`. It MUST be available as a sibling of `get_event_lock_observability_snapshot` and be used to populate system status.

#### Scenario: Snapshot exposes both metrics

- GIVEN prune metrics have recorded stale rows and completed batches
- WHEN get_event_prune_observability_snapshot() is called
- THEN the returned dataclass contains both named values with their current totals

