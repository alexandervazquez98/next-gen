# Proposal: fix-310-event-correlation-rca

Status: Ready for archive. PR 1 + PR 2 + PR 3 bundled into a single PR against `main`. 28+ commits. All 8 requirements pass with runtime evidence (verify pass_with_warnings). Issue #310 closes when merged. Issue #311 tracks follow-ups (AI agent filtering, Path B re-enable, historical backfill).
Change ID: `fix-310-event-correlation-rca`
GitHub Issue: `#310`

## Intent
Production event writers currently mark downstream failures as independent `ROOT` events, even though topology RCA already exists and is tested. This breaks operator-facing incident semantics: MQTT/ITSM can escalate every cascade member, `GET /api/events` shows duplicate incidents, and frontend grouping misses `CONNECTS_TO` topologies.

This change restores write-time RCA for active producer paths and filters default consumer views to authoritative events while preserving forensic records for both ROOT and PROPAGATED events.

## Scope
### In Scope
- `backend/engines/snmp_worker.py:271-272,326,405-406`: replace hardcoded ROOT fields with correlation helper output from `find_open_parent_event`.
- `backend/polling/snmp_worker.py`: pre-tag Path C envelopes with `correlation_type`, `propagated_from`, `root_cause_ci_id` before `event_writer.batch_update_events`.
- `backend/polling/event_writer.py:211-214`: no logic change; add regression coverage proving pre-tagged PROPAGATED envelopes round-trip.
- `backend/engines/cli_worker.py:350-361`: add the same correlation tagging for `CLI_POLL_ALERT` events.
- `backend/services/event_service.py`: add shared `_is_authoritative_event(event)` alongside `_is_authoritative_availability_event`.
- `backend/services/escalation_notifier.py`: suppress escalation for PROPAGATED events via `_is_authoritative_event()`.
- `backend/routers/events.py`: default `get_events` to ROOT/authoritative events; allow `?include=propagated` for advanced views.
- `frontend/hooks/useEventCorrelation.ts:89`: include `CONNECTS_TO` in client-side grouping.

### Non-Goals
- AI agent filtering (`backend/services/ai_chat_service.py`) — tracked by #311.
- Path B re-enable/deprecation (`backend/services/snmp_service.py:snmp_collector_loop`) — tracked by #311.
- Backfill migration for historical wrong/empty `correlation_type` — tracked by #311.
- Changing traversal depth (`max_depth=3`), recovery cascade logic, or audit-log completeness.

## Capabilities
### New Capabilities
- `event-correlation-rca`: write-time event correlation, authoritative event filtering, and CONNECTS_TO grouping behavior.

### Modified Capabilities
- None.

## Approach
Introduce a thin write-side helper near event correlation service code, for example:

```python
resolve_event_correlation(topology_repo, ci_id: str, *, can_propagate: bool = True) -> dict
```

Return fields: `correlation_type`, `propagated_from`, `root_cause_ci_id`. If `can_propagate` is false or no open parent exists, return ROOT with `root_cause_ci_id=ci_id`; otherwise return PROPAGATED using `find_open_parent_event(ci_id, max_depth=3)`. Call it from Path A SNMP CREATE branches, Path C producer envelope construction, and CLI poll alert creation. Keep `event_writer.py` as a preservation boundary, not the RCA computation owner.

Add `_is_authoritative_event(event)` to centralize `correlation_type != 'PROPAGATED'`. Reuse it in escalation and events API defaults. Frontend grouping aligns with backend traversal by adding `CONNECTS_TO`.

## Affected Files
| Area | Impact | Description |
|---|---|---|
| `backend/engines/snmp_worker.py` | Modified | Path A write-side RCA tagging. |
| `backend/polling/snmp_worker.py` | Modified | Path C envelope pre-tagging. |
| `backend/polling/event_writer.py` | Tested | Preserve pre-tagged PROPAGATED fields. |
| `backend/engines/cli_worker.py` | Modified | RCA tagging for CLI poll alerts. |
| `backend/services/event_service.py` | Modified | Shared helper for authoritative event checks. |
| `backend/services/escalation_notifier.py` | Modified | No escalation for PROPAGATED events. |
| `backend/routers/events.py` | Modified | ROOT default with propagated opt-in query. |
| `frontend/hooks/useEventCorrelation.ts` | Modified | Add `CONNECTS_TO` grouping. |
| `backend/tests/` / `frontend/tests/` | Modified | Regression coverage for paths and filters. |

## Acceptance Criteria
- [ ] When CI E depends on CI A and both fail, Neo4j stores A as `ROOT` and E as `PROPAGATED` with `propagated_from=<A event id>` and `root_cause_ci_id='A'`.
- [ ] Path A, Path C, and CLI poll alert writes use the same correlation semantics and honor `can_propagate=false` where available.
- [ ] `event_writer.py` preserves pre-tagged PROPAGATED envelopes without rewriting them to ROOT.
- [ ] `escalation_notifier.py` does not publish for `correlation_type='PROPAGATED'`.
- [ ] `GET /api/events` returns authoritative/ROOT events by default and includes propagated events only with `?include=propagated`.
- [ ] `useEventCorrelation.ts` collapses `CONNECTS_TO` cascades like `DEPENDS_ON` and `HOSTED_ON`.

## Resolved Questions
1. Fix active Paths A and C inline; Path B remains out of scope (#311).
2. Use a separate write-side helper, not `_is_authoritative_availability_event`.
3. `CONNECTS_TO` has same RCA propagation semantics as `DEPENDS_ON`.
4. Historical backfill is deferred to #311.
5. Preserve current `can_propagate=false` opt-out behavior.
6. Escalation and default event feed filter PROPAGATED; AI filtering deferred to #311.
7. Test production write paths with mocked parent lookup plus writer round-trip assertions.
8. CLI poll alerts are in this PR.
9. Frontend continues client-side grouping but aligns relationship set with backend.
10. KPI count changes are accepted: cascades deduplicate to one authoritative incident.

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| Neo4j traversal cost during bursts | Med | Keep `max_depth=3`; test/helper boundary allows later caching. |
| Consumer behavior changes | Med | Default only filters authoritative views; expose propagated opt-in. |
| AI agent still sees duplicate semantics | Med | Explicitly defer to #311 and note side effect. |
| Incorrect helper placement/cycles | Low | Keep helper thin and dependency-injected around topology repo. |
| KPI/dashboard count drift | Med | Accepted product impact; document in release notes/spec. |

## Dependencies / Coordination
- Requires no external service or migration.
- Blocks #311 follow-up decisions by establishing correct forward-write semantics first.
- Coordinate operator communication because escalation and open-event counts will decrease for cascades.

## Rollback Plan
Revert this change’s code and tests to restore previous ROOT-only writes and unfiltered event/escalation behavior. If only consumer filtering causes issues, disable/revert `_is_authoritative_event()` use in `events.py` and `escalation_notifier.py` while keeping write-side RCA for investigation. No data migration rollback is required because this change is forward-only.
