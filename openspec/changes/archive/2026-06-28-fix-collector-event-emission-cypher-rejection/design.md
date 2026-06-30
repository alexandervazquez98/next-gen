# Design: Fix Collector Event Emission Cypher Rejection

## 1. Context

Production rejects Event writes that reference `$poll_collector_id` with `Neo.ClientError.Statement.SyntaxError: Variable poll_collector_id not defined`. The value is passed by Python, so this change keeps the collector-attributed primary path but adds a narrow fallback that preserves Event emission when Neo4j rejects that one parameter.

## 2. Goals

- Preserve Event creation/update.
- Keep primary `poll_collector_id` attribution when accepted.
- Retry only the specific undefined-parameter failure.
- Keep existing dedup/lock semantics.
- Emit grep-friendly diagnostics.

## 3. Non-Goals

No schema change, no backfill of dropped Events, no RCA for why Neo4j rejects the param, no rewrite of `snmp_worker.py` / `snmp_service.py`, no changes to recovery writers or `polling/event_writer.py`.

## 4. Architecture Overview

```text
writer acquires pg_advisory_xact_lock
        │
        ▼
run primary Cypher with poll_collector_id
        │
        ├─ success / non-matching error ──► return / re-raise
        ▼
matching ClientError
        ▼
log ERROR cypher-param-fallback + retry without poll_collector_id
```

## 5. Architectural Choice

| Option | Trade-off | Decision |
|---|---|---|
| New helper module | Small new surface, unit-testable without Neo4j, reusable by worker + legacy service | **Choose** |
| Inline per writer | Lowest indirection, but repeats fragile error/logging logic | Reject |
| Decorator | Hides the query-pair shape and makes per-call fallback params less explicit | Reject |

Create `backend/services/neo4j_write_guard.py`, matching the small service-helper convention used by `backend/services/event_lock.py`.

## 6. Module Layout

| File | Action | Notes |
|---|---|---|
| `backend/services/neo4j_write_guard.py` | Create | `run_with_cypher_param_fallback(...)` + `is_poll_collector_id_undefined_error(...)` |
| `backend/engines/snmp_worker.py` | Modify | Wrap the three current Event `session.run` blocks that contain six `poll_collector_id` CREATE/SET clauses |
| `backend/services/snmp_service.py` | Modify | Wrap legacy update/create Event writes at `:530` and `:575` |
| `backend/tests/test_neo4j_write_guard.py` | Create | Helper unit tests |
| `backend/tests/test_snmp_worker_cypher_fallback.py` | Create | Worker integration-style mocked fallback tests |
| `backend/tests/test_snmp_service_cypher_fallback.py` | Create | Legacy backend-loop fallback tests |

Interface:

```python
def is_poll_collector_id_undefined_error(error: Exception) -> bool: ...

def run_with_cypher_param_fallback(
    session,
    primary_query: str,
    primary_params: dict,
    fallback_query: str,
    fallback_params: dict,
    error_filter: Callable[[Exception], bool],
    logger,
): ...
```

The helper runs primary, catches only matching errors, logs, then runs fallback. Non-matching errors re-raise unchanged.

## 7. Fallback Query Construction

Each protected writer keeps its existing multi-line Cypher as `primary_query`. The fallback is the same string with `poll_collector_id: $poll_collector_id` and `poll_collector_id = $poll_collector_id` removed; fallback params remove `poll_collector_id`.

Example from `_refresh_icmp_availability_events`:

```diff
-    session.run("""... poll_collector_id: $poll_collector_id ... poll_collector_id = $poll_collector_id ...""",
-        availability_events=availability_events, poll_collector_id=POLL_COLLECTOR_ID)
+    run_with_cypher_param_fallback(
+        session, primary_query, {"availability_events": availability_events, "poll_collector_id": POLL_COLLECTOR_ID},
+        fallback_query, {"availability_events": availability_events},
+        is_poll_collector_id_undefined_error, logger)
```

Apply the same query-pair pattern to collection failures, ICMP latency breaches, and legacy service update/create writes.

## 8. Error Detection

The predicate is strict: `isinstance(error, neo4j.exceptions.ClientError)` AND `"poll_collector_id" in error.message` AND `"not defined" in error.message`. This is a `ClientError`-class test, not a Python `SyntaxError` test; the Neo4j driver wraps statement syntax failures under `ClientError`.

## 9. Lock Interaction

Fallback runs **inside** the existing `acquire_event_triplet_lock` scope. Locks are acquired before primary; fallback does not acquire a second lock and does not widen lock scope.

## 10. Logging Contract

On fallback trigger, log at `ERROR` using `logger.exception("cypher-param-fallback primary_query=%r primary_params=%r fallback_query=%r fallback_params=%r", ...)`. This includes the marker, original query, params, fallback query/params, and stack trace.

## 11. Test Strategy (Strict TDD)

- `test_neo4j_write_guard.py`: primary success skips fallback; matching `ClientError` logs and runs fallback; non-matching `ClientError` re-raises; fallback failure surfaces.
- `test_snmp_worker_cypher_fallback.py`: with `mock_neo4j_driver`/mock session, force the primary worker Event write to raise matching `ClientError`; assert fallback query omits `poll_collector_id`, still creates/touches Event, and lock was already acquired.
- `test_snmp_service_cypher_fallback.py`: same for legacy update and create branches in `store_metric_result`.

## 12. Migration / Deploy

No migration. Prefer one reviewable work-unit commit containing helper + writer wiring + tests; split only if diff exceeds the 400-line review budget. Rebuild `nextgen-snmp-engine`, restart `nexgen_snmp_worker` on `10.53.1.22`, then verify with `docker logs nexgen_snmp_worker | grep cypher-param-fallback`.

## 13. Risk and Mitigations

| Risk | Mitigation |
|---|---|
| Fallback masks unrelated Cypher bugs | Strict `ClientError` + message predicate |
| Lost collector attribution on fallback | Accepted: Event emission wins; ERROR log preserves params |
| Duplicate Events during fallback | Existing advisory lock remains held |
| Fallback also fails | Surface the fallback error; no third tier |

## 14. Open Architectural Questions

- Is the wrapper strict TDD-compatible? **Yes**: helper tests use mocks only; no real Neo4j required.
- Should fallback acquire the lock a second time? **No**: the writer already holds the transaction-scoped lock.
- Should there be a third tier if fallback fails? **No**: surface the failure; one tier is sufficient.

## 15. References

- `openspec/changes/fix-collector-event-emission-cypher-rejection/proposal.md`
- `openspec/changes/fix-collector-event-emission-cypher-rejection/specs/cypher-param-fallback/spec.md`
- `openspec/changes/fix-collector-event-emission-cypher-rejection/specs/event-deduplication/spec.md`
- Sibling: `openspec/changes/fix-event-duplication-cross-writer/design.md`, `apply-progress.md`
- Commits / PRs: `75cd3ae`, PR #328, PR #330, PR #332
