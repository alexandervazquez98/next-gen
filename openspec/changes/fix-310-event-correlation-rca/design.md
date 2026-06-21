# Design: fix-310-event-correlation-rca

## Architecture Overview

Restore RCA at event write time, then gate default consumers to authoritative events. Existing topology has three write paths: Path A `backend/engines/snmp_worker.py:poll_snmp` is active and hardcodes ROOT; Path B `backend/services/snmp_service.py:snmp_collector_loop` already tags RCA but remains disabled/out of scope (#311); Path C `backend/polling/snmp_worker.py:run_leased_snmp_worker_once` is active when leased polling is enabled and currently emits untagged envelopes that `event_writer.py` defaults to ROOT.

```text
Path A/Path C/CLI event candidate
  -> resolve_correlation_fields(ci_id, severity, can_propagate)
  -> find_open_parent_event(max_depth=3, DEPENDS_ON|HOSTED_ON|CONNECTS_TO)
  -> Event {ROOT|PROPAGATED, propagated_from, root_cause_ci_id}

Event consumers
  -> _is_authoritative_event(event)
  -> escalation suppresses PROPAGATED
  -> GET /api/events filters PROPAGATED unless include=propagated|all
```

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|---|---|---|---|
| Helper location | Add write helper in `backend/services/event_service.py`; reuse `repositories.topology_repo.find_open_parent_event` | New service module | Keeps correlation helpers with event helpers and avoids a broader package split. |
| Burst mitigation | Add a per-poll-cycle TTL memo cache (~5s) passed by callers | Global cache or concurrency limit | Deterministic, avoids stale cross-cycle state, and reduces repeated traversal during cascades. |
| Feature flag | No flag | Runtime flag for new behavior | The change fixes incorrect writes; rollback is reverting PR. AI filtering remains #311. |

## Component Design

### Write-side correlation helper

`backend/services/event_service.py` adds:

```python
def resolve_correlation_fields(
    ci_id: str,
    severity: str,
    *,
    can_propagate: bool = True,
    cache: dict[str, tuple[float, dict[str, Any]]] | None = None,
    now: Callable[[], float] = time.monotonic,
) -> dict[str, Any]: ...
```

Returns `{correlation_type, propagated_from, root_cause_ci_id}`. If `can_propagate` is false, no parent exists, or `find_open_parent_event` raises, return ROOT with own CI (fail-safe; collectors must not block on topology hiccups). PROPAGATED maps `propagated_from=parent_event_id` and inherits `root_cause_ci_id`.

Call sites: `backend/engines/snmp_worker.py` before bulk CREATE rows in `_refresh_snmp_collection_failures:248`, `_refresh_icmp_availability_events:295`, `_refresh_icmp_latency_events:381`; `backend/polling/snmp_worker.py:90-96` update `result.metadata` before `result_to_queue_row`; `backend/engines/cli_worker.py:349-361` before `CLI_POLL_ALERT` CREATE. Cypher CREATE clauses replace hardcoded fields at `snmp_worker.py:271-272,326,405-406` with row params.

### Authoritative event helper and API

`backend/services/event_service.py` adds `_is_authoritative_event(event) -> bool`: `False` only for `correlation_type == 'PROPAGATED'`; `True` for ROOT, missing, `None`, or unknown legacy values. `_is_authoritative_availability_event()` delegates to it. `backend/services/escalation_notifier.py` imports it and returns no publish/no active escalation for PROPAGATED. `backend/routers/events.py:get_events` adds `include: Optional[str] = Query(None)`; default calls `event_service.get_events(status, include_propagated=False)`, while `include=propagated|all` returns all. This is a breaking API default for consumers that expected every Event; they must opt in.

### Frontend hook

`frontend/hooks/useEventCorrelation.ts:89` extends the existing relationship condition to include `link.relationship === 'CONNECTS_TO'`. Update `frontend/hooks/useEventCorrelation.test.ts` by mirroring the DEPENDS_ON test with CONNECTS_TO and keeping MANAGED_BY ignored.

## Data Model

No Neo4j schema migration required. The fields `correlation_type`, `propagated_from`, and `root_cause_ci_id` already exist in Event nodes and `event_writer.build_event_rows`; this change writes values previously hardcoded/defaulted.

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/services/event_service.py` | Modify | Add correlation resolver and generic authoritative helper; extend `get_events`. |
| `backend/engines/snmp_worker.py` | Modify | Tag Path A collection failure, ICMP availability, and ICMP latency events. |
| `backend/polling/snmp_worker.py` | Modify | Pre-tag Path C envelopes. |
| `backend/polling/event_writer.py` | Test only | Preserve metadata; no logic change expected. |
| `backend/engines/cli_worker.py` | Modify | Tag CLI poll alerts. |
| `backend/services/escalation_notifier.py`, `backend/routers/events.py` | Modify | Suppress/filter propagated events by default. |
| `frontend/hooks/useEventCorrelation.ts` | Modify | Include CONNECTS_TO grouping. |
| `CHANGELOG.md` | Modify | Note KPI/open-event count drift and ops dashboard recalibration. |

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | `_is_authoritative_event`; resolver fail-safe/cache | Extend `backend/tests/test_event_correlation.py`; cases: missing, None, ROOT, PROPAGATED, unknown, lookup exception. |
| Integration/E2E | Mandatory Path A multi-CI chain | New `backend/tests/test_path_a_rca_chain.py`; production `poll_snmp` path, no real network. |
| Integration | Path C metadata round-trip | Extend `backend/tests/test_polling_event_writer.py` or add `test_polling_event_writer_chain.py`. |
| API/consumer | Escalation + events filtering | Extend `backend/tests/test_escalation_notifier.py` and `backend/tests/test_routers_events.py`. |
| Frontend | CONNECTS_TO grouping | Extend `frontend/hooks/useEventCorrelation.test.ts`. |

### Mandatory Path A Chain Test

Fixture factory: `build_dependency_chain(topology: Literal['fan_out','chain'], root_count=1, dependent_count=3, severities: dict[str,str]) -> ChainFixture` creates `MockNeo4jDriver`, CI ids `A/B/C/D`, MetricDefs, relationships (`B/C/D -> A` for fan-out, `C -> B -> A` for chain), and canned `find_open_parent_event` query responses through the mock session so real `topology_repo.find_open_parent_event` executes against `MockNeo4jDriver`. Stub only network boundary: `engines.snmp_worker.fetch_icmp_ping_measurement`/`fetch_snmp_value` return deterministic measurements; patch `SessionLocal`, `bulk_insert_metrics`, and scheduler side effects as existing tests do. Do NOT mock `find_open_parent_event` inside the engine.

The fixture factory also accepts a `depth=N` parameter for explicit N-hop linear chains (e.g., `depth=4` builds `A→B→C→D`, `depth=5` builds `A→B→C→D→E`). When `depth` is set, `ci_ids[0]` is the root and `ci_ids[N-1]` is the leaf. The factory's `parent_lookup` honors the same `max_depth=3` cap as the resolver, so dependents beyond the cap resolve to `None` and the leaf is tagged `ROOT` — exactly what the real Cypher traversal produces.

Scenarios (<1s each):
1. Fan-out: A CRITICAL, B/C/D mixed severities. After `poll_snmp`, assert one Event for A: `ROOT`, `root_cause_ci_id='A'`, CRITICAL; one Event per B/C/D: `PROPAGATED`, `propagated_from=<A event id>`, `root_cause_ci_id='A'`, severity from each CI metric.
2. 3-hop chain (A→B→C, two upstream hops from C to A): A WARNING, B CRITICAL, C WARNING; assert A ROOT WARNING, B PROPAGATED CRITICAL, C PROPAGATED WARNING.
3. Mixed-severity regression: propagated severity never flattens to root severity.
4. **Depth coverage (REQ-CORR-8)**: add explicit depth scenarios — a true 3-hop chain `A→B→C→D` (depth=4) where D resolves the root cause and is tagged `PROPAGATED`; a 4-hop chain `A→B→C→D→E` (depth=5) where E exceeds the traversal depth and is tagged `ROOT` with `root_cause_ci_id='E'`.

T5 covers write-side behavior only. Consumer-side assertions (`escalation_notifier` call counts, `GET /api/events` default-vs-opt-in) ship with T9/T10 in PR 2, where those surfaces are actually modified. Keeping T5 focused on write-side semantics avoids coupling the centerpiece test to consumer-side changes that have not landed yet.

## Migration / Rollout

No migration required. Single PR is preferred within the 800-line review budget; if task forecasting exceeds it, recommend chained PRs before apply. Deploy through normal SDD phases. Rollback by reverting the PR; no schema/data rollback. Ops note: dashboards/KPIs that count open events may drop; CHANGELOG must call out recalibration.

## Open Questions

None. Proposal/spec resolved traversal depth, CONNECTS_TO semantics, CLI inclusion, audit completeness, KPI drift, and ITSM one-ticket-per-chain.

## Out of Scope

AI agent filtering, Path B re-enable/deprecation, and historical backfill are deferred to #311. Audit log filtering, traversal depth changes, and KPI/dashboard rebalancing are out of scope.
