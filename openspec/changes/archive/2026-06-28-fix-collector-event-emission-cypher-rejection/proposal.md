# Proposal: fix-collector-event-emission-cypher-rejection

Status: Draft
Change ID: `fix-collector-event-emission-cypher-rejection`
GitHub Issue: `#340`

## Executive Summary
A Configuration Item can lose contact with the SNMP collector and still produce no Neo4j `Event` because production rejects Cypher that references `$poll_collector_id` with ``Neo.ClientError.Statement.SyntaxError: Variable `poll_collector_id` not defined``. The affected queries were introduced by the collector-attribution work from issue #322, but this is a new production event-emission bug, not the prior deduplication defect. The fix hardens all affected SNMP worker writers with a narrow fallback that retries without `poll_collector_id` and logs the original query, params, and stack.

## Problem Statement
On `10.53.1.22` (`nexgen_snmp_worker`, built 2026-06-28 07:17:46 UTC), every cycle that processes ICMP availability `value=0.0` or `value=1.0` fails to persist the corresponding Event when Neo4j reports `$poll_collector_id` is undefined. CIs such as `CI-45A1EDD1` can remain DOWN for hours while the UI stays healthy because the availability Event is silently dropped. The repo/container source passes `poll_collector_id=POLL_COLLECTOR_ID`, so the root cause is still unresolved and must not block event creation.

## Scope
### In Scope
- Six `backend/engines/snmp_worker.py` writers that use `$poll_collector_id`.
- `backend/services/snmp_service.py::store_metric_result` writer path (the legacy backend loop): apply the same wrapper for defense in depth even though it is not the active production path. Approved by user 2026-06-28.
- Fallback writer strategy that retries without collector attribution.
- ERROR logging with original Cypher, params, and stack when fallback triggers.
- Strict TDD regression: mock `session.run(...)` to raise the production `ClientError` and prove fallback creates the Event, for both writer paths.

### Out of Scope
- Deduplication changes from `fix-event-duplication-cross-writer` / issue #322.
- Topology RCA wiring from #310.
- Structural refactor of `engines/snmp_worker.py` or `services/snmp_service.py`.
- Backfill for silently dropped Events.
- Migration of `engines/snmp_worker.py` to the lease/polling path under `backend/polling/`.

## Capabilities
### New Capabilities
- `cypher-param-fallback`: Event writers retry a minimal query without the rejected parameter only for the specific undefined-parameter Cypher failure and emit diagnostic context.

### Modified Capabilities
- `event-deduplication`: Collector-attributed writers gain defense-in-depth fallback; deduplication behavior is unchanged when the primary query succeeds.

## Technical Approach
Add a small `session.run` wrapper/helper near the SNMP worker Event writes. Detect `Neo.ClientError.Statement.SyntaxError` containing `poll_collector_id` and `not defined`, log query + params + stack at ERROR, then execute the matching fallback query without collector attribution. Re-raise every other Neo4j error. Write the regression test first.

## Affected Areas
| Area | Impact | Description |
|---|---|---|
| `backend/engines/snmp_worker.py` | Modified | Wrap six `$poll_collector_id` Event writers with fallback |
| `backend/tests/` | Modified | Add regression coverage for fallback Event creation |
| Operator runbook | Deferred | Document fallback attribution trade-off after implementation |

## Acceptance Criteria
- Fallback covers all six SNMP worker writers using `$poll_collector_id`.
- A mocked production `ClientError` causes a second query without `poll_collector_id` and creates/touches the Event.
- Non-matching Cypher errors still fail loudly.
- Logs include the original query, params, and stack.
- Fallback Events may omit `poll_collector_id`; Event creation wins over forensics.

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| Fallback masks real Cypher defects | Med | Match only the specific undefined `poll_collector_id` error |
| Retry doubles Neo4j traffic on failure path | Low | Exceptional path only; primary query remains unchanged |
| Lost fallback attribution | Med | Accepted trade-off; log diagnostics for RCA |

## Rollback Plan
Revert the wrapper, fallback queries, and tests. No schema, migration, or data backfill state is introduced.

## Open Questions
- Which unresolved hypothesis explains production rejection: driver drift, param mutation, runtime empty collector id, or Neo4j/protocol behavior? (Tracking only; does not block the fallback fix.)
- ~~Should `backend/services/snmp_service.py::store_metric_result` receive the same wrapper for defense in depth, even though it is not the active production path?~~ **Resolved 2026-06-28** by user: YES, apply to both paths. Reflected in Scope.

## References
- `openspec/changes/fix-event-duplication-cross-writer/` and issue #322.
- Commit `75cd3ae` (`poll_collector_id` attribution) and `89dba95` (#310 topology RCA).
- `backend/engines/snmp_worker.py:310-580`; `backend/services/event_lock.py:32-56`.
- Production logs: ~30+ `poll_collector_id not defined` errors/hour since rebuild.
