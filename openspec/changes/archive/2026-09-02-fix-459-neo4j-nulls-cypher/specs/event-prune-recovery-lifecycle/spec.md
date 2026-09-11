# Delta for Event Prune and Recovery Lifecycle

## ADDED Requirements

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

## MODIFIED Requirements

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
