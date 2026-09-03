# Event Prune and Recovery Lifecycle Specification

## Purpose

Define bounded, repeatable lifecycle handling for recovered Event rows, including safe cursor pagination, legacy timestamp backfill, scheduled pruning, and recovery-event reuse, so stale `RECOVERED` Event rows do not accumulate indefinitely and the manual and scheduled pruning paths never write concurrently.

## Requirements

### Requirement: Cursor Forward Progress on NULL `created_at`

The event batch pruner MUST paginate with a composite `(created_at, id)` cursor and a NULL-safe ordering/tiebreak rule. It MUST process every eligible row exactly once across bounded batches, including rows whose `created_at` is NULL. The ordering clause MUST rely on the Cypher 5 default NULL placement — `NULLS LAST` under `ASC`, `NULLS FIRST` under `DESC` — and MUST NOT emit the explicit `NULLS FIRST` or `NULLS LAST` keywords, which are not part of the Cypher 5 grammar and therefore produce `Neo.ClientError.Statement.SyntaxError` against Neo4j 5.x.
(Previously: required a "NULL-safe ordering/tiebreak rule" without constraining the ORDER BY syntax — now mandates Cypher-5-valid implicit NULL placement and forbids the explicit `NULLS` keyword.)

#### Scenario: All timestamps are NULL

- GIVEN all eligible rows have `created_at=null`
- WHEN the pruner processes multiple bounded batches
- THEN each row is processed
- AND later batches continue until no eligible rows remain

#### Scenario: Mixed NULL and timestamped rows

- GIVEN eligible rows contain both NULL and timestamped `created_at` values
- WHEN the pruner advances its cursor
- THEN no eligible row is skipped or revisited across batches

#### Scenario: Monotonic UUID tiebreak across boundary

- GIVEN rows share a cursor boundary across NULL and timestamped groups
- WHEN the next batch is selected
- THEN the monotonic event-id tiebreak selects the remaining rows deterministically

### Requirement: Event `created_at` Backfill Contract

`backend/scripts/backfill_event_created_at.py` MUST be argparse-driven, batch-bounded, and idempotent. For rows with NULL `created_at`, it MUST set `created_at = COALESCE(recovered_at, last_seen, closed_at, datetime())` and MUST NOT modify rows whose `created_at` is already populated.

#### Scenario: Dry-run reports candidates

- GIVEN N Event rows have `created_at=null`
- WHEN the script runs in dry-run mode
- THEN it reports N candidates and mutates zero rows

#### Scenario: Live run mutates candidates

- GIVEN N Event rows have `created_at=null`
- WHEN the script runs live with a configured batch size
- THEN it mutates N rows through bounded batches using the specified arguments

#### Scenario: Re-run is idempotent

- GIVEN the previous live run completed
- WHEN the script runs live again
- THEN it mutates zero rows

### Requirement: Auto-Prune Scheduler

The existing `backup_scheduler` MUST register an APScheduler `IntervalTrigger` job named `run_prune_recovered_events`, defaulting to a one-hour interval. The job MUST honor `EVENT_PRUNE_ENABLED`, use `coalesce=True`, `max_instances=1`, and `replace_existing=True`, and share prune-lock serialization with manual pruning.

#### Scenario: Enabled scheduler fires

- GIVEN `EVENT_PRUNE_ENABLED` is true and the scheduler is healthy
- WHEN the configured interval elapses
- THEN `run_prune_recovered_events` executes one bounded prune job

#### Scenario: Kill-switch skips execution

- GIVEN `EVENT_PRUNE_ENABLED=false`
- WHEN the scheduler tick occurs
- THEN the job remains registered but skips pruning without raising

#### Scenario: Manual and scheduled prune contend

- GIVEN a manual `POST /events/prune` holds the prune lock
- WHEN a scheduler tick attempts pruning concurrently
- THEN the second caller receives HTTP 409
- AND concurrent writes never occur

### Requirement: ICMP-Latency Reuses RECOVERED Events

The ICMP-latency recovery writers MUST treat `RECOVERED` as eligible in their existing-event predicates so a subsequent failure reopens the existing ROOT Event rather than creating a new ROOT. The ICMP-latency CREATE payloads MUST also include `created_at: datetime()` so that the cursor can paginate these rows reliably.

#### Scenario: DOWN–OK–DOWN reuses the ROOT

- GIVEN an ICMP-latency ROOT transitions DOWN to OK and then DOWN again
- WHEN the second failure is written
- THEN the original ROOT event id is reused
- AND no new ROOT is created

#### Scenario: ICMP-latency CREATE carries `created_at`

- GIVEN an ICMP-latency CREATE payload is emitted
- WHEN the writer persists the new Event
- THEN the `created_at` property is set to the current timestamp
- AND the cursor can order this row by `created_at` without falling back to `id`

### Requirement: Existing Recovery-Writer Lock Contract

The collection-failure and ICMP-availability recovery writers MUST continue to include `RECOVERED` in their existing-event predicates. A regression test MUST assert this predicate and fail if the eligible status set is narrowed.

#### Scenario: Existing predicates retain RECOVERED

- GIVEN the current recovery writer predicates include `OPEN`, `ACK`, and `RECOVERED`
- WHEN the regression contract test runs
- THEN all four existing predicate sites remain RECOVERED-eligible

### Requirement: Fail-Loud on CypherSyntaxError in `event_batch_pruner`

The `event_batch_pruner` MUST propagate a `CypherSyntaxError` (the Neo4j `ClientError` whose `code` equals `Neo.ClientError.Statement.SyntaxError`) to the SSE consumer on the first failed chunk, bypassing the consecutive-failure debounce. On propagation the generator MUST yield a terminal `error` chunk containing the exception message, log at ERROR level, and terminate the stream. Non-syntax errors (transient, unavailable, driver) MUST keep the existing debounce.

#### Scenario: First-chunk syntax error is not debounced

- GIVEN the page query raises `CypherSyntaxError` on the first iteration
- WHEN the pruner yields its first chunk
- THEN the consumer receives an `error` chunk carrying the syntax message
- AND the pruner logs at ERROR level
- AND the stream closes after the terminal chunk

#### Scenario: Transient errors keep the existing debounce

- GIVEN the page query raises `ServiceUnavailable` or `TransientError`
- WHEN the pruner yields three consecutive failure chunks
- THEN the existing 3-strike debounce still applies
- AND no terminal `error` chunk is emitted before the cap
