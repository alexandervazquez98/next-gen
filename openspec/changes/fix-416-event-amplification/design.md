# Design: fix-416 Event Amplification — Two-Pass Correlation

## Technical Approach

Refactor `backend/engines/snmp_worker.py:poll_snmp` into three passes inside the same SQLAlchemy `db` and Neo4j `session` that already hold the Event advisory-lock triplet contract. Pass 1 (Collect) unchanged. Pass 2 (Materialize Roots) writes eligible current-cycle candidates as ROOT through the existing `_refresh_*` CREATE sites with `cache={}`. Pass 3 (Attach Dependents) re-resolves `build_open_parent_index` and routes dependents through the existing `_update_propagated_root_events` to attach `affected_ci_ids`/`affected_ci_count` idempotently. No public API change. Specs: REQ-001..007 / SCN-001..011.

## Architecture Decisions

| # | Decision | Alternatives | Rationale |
|---|----------|--------------|-----------|
| AD-1 | New `backend/engines/correlation.py` with pure candidate selection + Neo4j writes; no module-level state | Inline in `snmp_worker.py` | Small stubbable surface; unit-testable without session |
| AD-2 | Cycle candidates computed from `correlation_pairs` + the availability/latency slices already extracted in `poll_snmp:1221-1244` | Re-run topology lookup | Pair set is already deterministic; avoids second depth-three Cypher |
| AD-3 | Pass 2 reuses existing `_refresh_*` FOREACH(CREATE) with `cache={}` | Bespoke root CREATE Cypher | Reuses proven dedup + `poll_collector_id` fallback (`#322/#330/#340`); zero new event-write code |
| AD-4 | Pass 3 reuses `_update_propagated_root_events`; idempotency via its existing `IN` guard + `size(affected_ci_ids)` | Custom MERGE/CREATE for attach | Matches verified behaviour in `test_propagated_rows_do_not_generate_duplicate_child_events_or_notes_on_repeated_polls` |
| AD-5 | `topology_repo.build_open_parent_index` contract unchanged; add pure `current_cycle_parent_candidates(observations)` that does NOT query Neo4j | Bake into `correlation.py` | Topology repo owns topology vocabulary |
| AD-6 | Triplet locks stay lexicographic per `(ci_id, metric_id, event_type)` inside each `_refresh_*` (`snmp_worker.py:374-389, 524-539, 711-726`); Pass 2 and Pass 3 share the same `db` so the transaction-scoped `pg_advisory_xact_lock` survives | Per-pass re-acquire | Preserves REQ-007 / `#322/#330` invariants |
| AD-7 | Lookup failure handled at the same boundary that already handles cache-build failure (`snmp_worker.py:1248-1259`); Pass 2's `materialize_current_cycle_roots` wraps each helper in try/except and falls back to ROOT writes via the existing `cache={}` path | Abort cycle | Mirrors the W2 blast-radius decision the repo already accepts |

## Data Flow

```
poll_snmp (session, db)  ← same SQLAlchemy db, same Neo4j session
  ├─ PASS 1: COLLECT         failure_updates / availability_updates / latency_updates
  ├─ PASS 2: MATERIALIZE     cycle_root_candidates(updates, cache) → set[(ci,metric,event_type)]
  │     for each candidate: _refresh_*(cache={}) → forces ROOT CREATE; sorted triplet locks
  │     _recover_*_events runs unchanged
  ├─ PASS 3: ATTACH          rebuild build_open_parent_index(session, all_pairs)
  │     _refresh_*(cache=rebuilt) → PROPAGATED skipped at CREATE
  │     _update_propagated_root_events → SET root.affected_ci_ids += [node_id] IF NOT IN;
  │                                       SET root.affected_ci_count = size(...)
  └─ finally: db.close()  → releases triplet lock
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/engines/correlation.py` | Create | `cycle_root_candidates`, `materialize_current_cycle_roots`, `attach_dependents_to_roots` |
| `backend/engines/snmp_worker.py` | Modify | `poll_snmp` orchestrates Pass 1-3 within lines 919-1307; Pass 2 gated by candidate set; Pass 3 re-uses existing `_refresh_*` with rebuilt cache |
| `backend/repositories/topology_repo.py` | Modify | Add `current_cycle_parent_candidates(observations)` (~25 lines, pure); no change to `build_open_parent_index` |
| `backend/tests/test_snmp_worker_correlation.py` | Modify | Add strict-TDD SCN-001..011 cases via `MockNeo4jSession.set_sequence_response` |
| `backend/tests/test_event_correlation.py` | Modify | Unit tests for `cycle_root_candidates` + attach idempotency |

## Interfaces / Contracts

```python
# backend/engines/correlation.py
def cycle_root_candidates(
    observations: list[dict],
    topology_index: dict[tuple[str, str], dict] | None,
) -> set[tuple[str, str, str]]:
    """Pure. (ci_id, metric_id, event_type) tuples missing from `topology_index`."""

def materialize_current_cycle_roots(
    session, db, candidates: set[tuple[str, str, str]],
    refresh_collection, refresh_availability, refresh_latency,
) -> int:
    """Per candidate: call matching _refresh_* with cache={}. try/except per
    helper; failures degrade to ROOT via existing cache={} path."""

def attach_dependents_to_roots(session, dependents: list[dict]) -> int:
    """Re-resolves build_open_parent_index and calls
    _update_propagated_root_events. Idempotent (existing IN guard + size())."""
```

```python
# backend/repositories/topology_repo.py  (additive)
def current_cycle_parent_candidates(
    observations: list[dict],
) -> set[tuple[str, str, str]]:
    """Pure. Subset that could still become ROOT given the depth-three
    DEPENDS_ON|HOSTED_ON|CONNECTS_TO*1..3 walk over OPEN/ACK parents.
    Caller passes the pre-built index; MUST NOT call Neo4j."""
```

## Testing Strategy

| Layer | What | How |
|-------|------|-----|
| Unit | `cycle_root_candidates` order-independence (SCN-001..003) | pytest parametrize over `[parent, child]` permutations |
| Unit | Affected-CI idempotency (SCN-005, SCN-010) | Reuse `_FakeRootUpdateSession` from `test_snmp_worker_correlation.py:286` |
| Unit | Non-propagating metric (SCN-007) | Inject `can_propagate=False`; expect ROOT |
| Integration | `poll_snmp` end-to-end (SCN-001/002/003/004/008) | `MockNeo4jSession.set_sequence_response` per UNWIND; assert one `CREATE (created` per cycle, no duplicate `affected_ci_ids` |
| Integration | Lookup failure (SCN-009) | Patch `build_open_parent_index` to raise; assert UNWIND...CREATE still runs with `cache={}` |
| Integration | All three event families (SCN-011) | Parametrize collection/availability/latency |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary changed.

## Migration / Rollout

No data migration. Rollback = revert the commit. `services/snmp_service.py` and `polling/event_writer.py` untouched (P1/P3 follow-ups).

## Open Questions

None. SCN-008 (parent recovery) is safe: Pass 3's `_update_propagated_root_events` MATCH at `snmp_worker.py:321` filters `root.status IN ['OPEN','ACK','RECOVERED']`, and `_recover_*_events` runs between Pass 2 and Pass 3, so a recovered root no longer accepts new attachments and unresolved dependents fall back to ROOT via Pass 2's `cache={}` enforcement on subsequent cycles.