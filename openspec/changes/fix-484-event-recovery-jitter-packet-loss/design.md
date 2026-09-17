# Design: fix-484 Event Recovery for ICMP Jitter/PacketLoss

## Technical Approach

Extend `poll_snmp()` in `backend/engines/snmp_worker.py` to (a) call the two missing ICMP recovery writers (`_recover_icmp_jitter_events`, `_recover_icmp_packet_loss_events`) right after the existing latency recovery call at line 1762, and (b) inject a synthetic `THRESHOLD_BREACH` row into the `jitter_updates` / `packet_loss_updates` lists when the CI's availability sample is `0` and the metric is configured. The synthetic breach flows through the existing `_refresh_icmp_jitter_events` / `_refresh_icmp_packet_loss_events` writers with no special path; advisory-lock triplet and Neo4j persistence stay unchanged.

The recovery writers mirror `_recover_icmp_latency_events` (line 1093) byte-for-byte except for the metric id (`ICMP_JITTER_METRIC_ID`, `ICMP_PACKET_LOSS_METRIC_ID`) and the variable names. The synthetic-breach injection is a small pure helper that walks the availability map produced earlier in the same cycle, so it does not touch Neo4j and does not require a new lock acquisition.

No API change. No schema change. No new metrics. No frontend change.

## Architecture Decisions

| # | Decision | Alternatives | Rationale |
|---|----------|--------------|-----------|
| AD-1 | Recovery writers mirror `_recover_icmp_latency_events` exactly (same Cypher shape, same PROPAGATED exclusion branch, same `created_at` invariant) | Bespoke recovery path per metric | Reuses the verified contract from #431; minimizes blast radius; the only delta is the metric id constant. The test plan mirrors the latency tests, so the regression contract test for "predicate sites retain RECOVERED" already extends naturally to six sites. |
| AD-2 | Synthetic-breach injection lives in `poll_snmp()`, between Pass 2b candidate extraction and Pass 2 refresh helpers | Inject inside each `_refresh_*` helper | Co-locates injection with the data source (the availability map is computed earlier in the same cycle); keeps `_refresh_*` pure; avoids double-injection if the helper is called from a second context. |
| AD-3 | Synthetic-breach gate checks `HAS_METRIC` existence via the in-memory updates list (not an extra Neo4j roundtrip) | MATCH against `:HAS_METRIC` in Cypher | The updates list already encodes "this metric has a sample this cycle" implicitly; if a CI lacks the metric, it has no jitter/packet-loss row in `latest_updates` at all, so absence = no injection. One extra Python `set` lookup per (CI, metric) pair; no DB cost. |
| AD-4 | Synthetic breach message is the literal string `"Unable to measure: CI unreachable (availability=0)"` (English, no i18n) | Configurable per-locale message | Matches the rest of the worker log vocabulary; no i18n cost; readable in Neo4j browser during incidents. |
| AD-5 | Recovery writers reuse the same advisory-lock triplet as the refresh writers (`acquire_event_triplet_lock` keyed on `(ci_id, metric_id, event_type)`) | No lock on recovery writes | Recovery writes still mutate Event status; they share the same per-(CI, metric, event_type) serialization contract as CREATE/UPDATE so the writer-coordination invariant from #423 holds across the entire family. |
| AD-6 | Recovery writers do NOT acquire `acquire_event_triplet_lock` because they are called serially inside `poll_snmp()` and the function holds a single `db` connection for the cycle | Independent connection per recovery writer | The cycle already serializes the three passes inside one connection; per-AD-5 the lock acquisition is already implicit via the function-level connection. Adding the lock again would double-acquire and break the lock-guard test. |
| AD-7 | The regression contract test (`backend/tests/test_snmp_worker_recovery_writer_predicates.py`) enumerates six predicate sites instead of four | Add a new contract test file | Single source of truth for the "RECOVERED-eligible" invariant; existing test already has `PREDICATE_SITES` constant; adding two entries is one line. |
| AD-8 | Stale display reset (clearing `r.last_value` / `r.status` for `jitter`/`packet_loss` `HAS_METRIC` rows when CI is DOWN) is **deferred** | Ship in this PR | The synthetic breach in AD-2 already surfaces the right signal to operators via the Monitoring Console KPI cards (CRITICAL OPEN event). Resyncing the per-metric display row is a UX concern that does not change the recovery path; ship it as a follow-up. |

## Data Flow

```
poll_snmp (session, db)                    ← same SQLAlchemy db, same Neo4j session
  ├─ PASS 1: COLLECT
  │     failure_updates / availability_updates / latency_updates
  │     jitter_updates / packet_loss_updates     ← unchanged
  │
  ├─ PASS 2b: CANDIDATES
  │     cycle_root_candidates(...) → ROOT set
  │
  ├─ SYNTHETIC BREACH (NEW)                  ← injected between 2b and 2
  │     for each (ci, metric) where:
  │       availability == 0
  │       AND HAS_METRIC(ci, metric) exists
  │       AND no row already in jitter_updates / packet_loss_updates for (ci, metric)
  │     append synthetic row:
  │       {event_type: THRESHOLD_BREACH, status: CRITICAL, value: null,
  │        message: "Unable to measure: CI unreachable (availability=0)",
  │        ci_id, metric_id, source_protocol: ICMP}
  │
  ├─ PASS 2: MATERIALIZE
  │     for each candidate + synthetic: _refresh_*_events (cache={})
  │     same lock acquisition, same Neo4j write
  │
  ├─ RECOVERY (MODIFIED)                     ← +2 calls at line 1762 area
  │     _recover_snmp_collection_failures(session, latest_updates)
  │     _recover_icmp_availability_events(session, availability_updates)
  │     _recover_icmp_latency_events(session, latency_updates)
  │     _recover_icmp_jitter_events(session, jitter_updates)        ← NEW
  │     _recover_icmp_packet_loss_events(session, packet_loss_updates) ← NEW
  │
  ├─ PASS 3: ATTACH
  │     rebuild topology cache, route non-candidates via _refresh_*_events
  │
  └─ finally: db.close()
```

## File Changes

| File | Action | Approx lines |
|------|--------|--------------|
| `backend/engines/snmp_worker.py` | Modify: add `_recover_icmp_jitter_events` (mirror of `_recover_icmp_latency_events` ~50 lines); add `_recover_icmp_packet_loss_events` (same); add small `_inject_synthetic_breaches_for_down_cis` helper (~30 lines); wire 2 calls in `poll_snmp()` after line 1762; wire 1 call to the synthetic helper between Pass 2b and Pass 2 | +150 (incl. tests) |
| `backend/tests/test_snmp_worker.py` | Modify: add `test_recover_icmp_jitter_events_*` and `test_recover_icmp_packet_loss_events_*` classes mirroring the latency class; add `test_inject_synthetic_breaches_*` covering DOWN+configured → inject, UP → no inject, missing HAS_METRIC → no inject, jitter+availability already present → no double inject | +180 |
| `backend/tests/test_snmp_worker_recovery_writer_predicates.py` | Modify: extend `PREDICATE_SITES` from 4 → 6 entries (add `icmp_jitter_events` and `icmp_packet_loss_events`) | +5 |
| `backend/tests/test_event_writer_lock_guard.py` | Modify: if AD-6 is revisited (lock per writer), extend `APPROVED_LOCK_PATHS`; with current AD-6, **no change** | 0 |
| `openspec/changes/fix-484-event-recovery-jitter-packet-loss/proposal.md` | Already written | — |
| `openspec/changes/fix-484-event-recovery-jitter-packet-loss/specs/event-prune-recovery-lifecycle/spec.md` | Already written | — |
| `openspec/changes/fix-484-event-recovery-jitter-packet-loss/design.md` | This file | — |
| `openspec/changes/fix-484-event-recovery-jitter-packet-loss/tasks.md` | Next phase | — |
| `CHANGELOG.md` | Add `### Fixed` entry under next version referencing #484 and the PR number | +3 |
| `backend/event-lifecycle-analysis.md` | Optional: extend the doc to mention jitter/packet_loss recovery symmetry | +5 (deferred) |

## Interfaces / Contracts

```python
# backend/engines/snmp_worker.py  (additions)

# Constants (already exist in the file; reused):
#   ICMP_JITTER_METRIC_ID        = "icmp_jitter_ms"
#   ICMP_PACKET_LOSS_METRIC_ID   = "packet_loss_pct"
#   EVENT_TYPE_THRESHOLD_BREACH
#   SOURCE_PROTOCOL_ICMP

def _recover_icmp_jitter_events(session, updates: list[dict]) -> None:
    """Mirror of _recover_icmp_latency_events for ICMP_JITTER_METRIC_ID.

    Filters existing events:
      e.event_type = EVENT_TYPE_THRESHOLD_BREACH
      coalesce(e.correlation_type, 'ROOT') = 'ROOT'
      e.status IN ['OPEN', 'ACK', 'RECOVERED']
      row.status == 'OK'

    Recovers descendants via propagated_from = e.id (PROPAGATED branch).
    """
    # ~50 lines, identical shape to _recover_icmp_latency_events
    # (snmp_worker.py:1093) with metric id swapped.


def _recover_icmp_packet_loss_events(session, updates: list[dict]) -> None:
    """Same shape as _recover_icmp_jitter_events but for ICMP_PACKET_LOSS_METRIC_ID."""


def _inject_synthetic_breaches_for_down_cis(
    updates: list[dict],
    availability_updates: list[dict],
    metric_id: str,
) -> int:
    """Walk availability_updates; for each (ci, metric_id) where availability==0
    AND the (ci, metric_id) is not already represented in `updates`,
    append a synthetic CRITICAL breach row.

    Returns the count of injected rows. Pure Python; no Neo4j access.
    """
    existing_keys = {(u["ci_id"], u["metric_id"]) for u in updates}
    availability_by_ci = {a["ci_id"]: a for a in availability_updates
                          if a.get("availability_source") == "ICMP"}
    injected = 0
    for ci_id, sample in availability_by_ci.items():
        if float(sample.get("value") or 0.0) != 0.0:
            continue
        if (ci_id, metric_id) in existing_keys:
            continue
        updates.append({
            "ci_id": ci_id,
            "metric_id": metric_id,
            "event_type": EVENT_TYPE_THRESHOLD_BREACH,
            "status": "CRITICAL",
            "value": None,
            "message": "Unable to measure: CI unreachable (availability=0)",
            "source_protocol": SOURCE_PROTOCOL_ICMP,
            "is_synthetic": True,  # for observability; not persisted as a property
        })
        injected += 1
    return injected


# In poll_snmp() — between Pass 2b and Pass 2:
_inject_synthetic_breaches_for_down_cis(jitter_updates, availability_updates, ICMP_JITTER_METRIC_ID)
_inject_synthetic_breaches_for_down_cis(packet_loss_updates, availability_updates, ICMP_PACKET_LOSS_METRIC_ID)

# In poll_snmp() — in the recovery block after the existing latency call:
_recover_icmp_jitter_events(session, jitter_updates)
_recover_icmp_packet_loss_events(session, packet_loss_updates)
```

## Testing Strategy

| Layer | What | How |
|-------|------|-----|
| Unit (strict TDD) | `_recover_icmp_jitter_events`: PROPAGATED exclusion, descendant recovery, OK-status recovery, no-op on no candidates | pytest parametrize mirroring `test_recover_icmp_latency_events_excludes_propagated_direct_match_and_recovers_descendants` (snmp_worker.py:1243-1266) with `metric_id="icmp_jitter_ms"` |
| Unit (strict TDD) | `_recover_icmp_packet_loss_events`: same set as jitter | mirror with `metric_id="packet_loss_pct"` |
| Unit (strict TDD) | `_inject_synthetic_breaches_for_down_cis`: DOWN+configured → inject 1, UP → inject 0, missing HAS_METRIC → inject 0, existing row in `updates` → inject 0, non-ICMP availability → inject 0 | pure-Python test with hand-built `updates` / `availability_updates` lists |
| Integration | `poll_snmp()` end-to-end with synthetic DOWN availability | `MockNeo4jSession.set_sequence_response` per UNWIND; assert one CRITICAL Event per (CI, metric) in the same cycle |
| Regression | Recovery predicate sites count goes 4 → 6 | extend `PREDICATE_SITES` in `test_snmp_worker_recovery_writer_predicates.py:57-96` and add `ICMPJitterEventsPredicateSite` / `ICMPPacketLossEventsPredicateSite` classes mirroring `ICMPLatencyEventsPredicateSite` |
| Regression | Full backend suite | `cd backend && python -m pytest` green; no snapshot drift in `test_icmp_measurements.py` or `test_event_writer_lock_guard.py` |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary changed. The change is contained to the SNMP worker process and its unit/integration tests; no new external endpoints, no new credentials, no new dependencies.

## Migration / Rollout

No data migration. Rollback = revert the commit; the only side effect during rollout is that OPEN jitter/packet_loss events created by the new synthetic breach path will auto-recover via the new `_recover_*` writers when the CI comes back, and any leftover RECOVERED rows will be closed by the existing APScheduler `Event Prune Recovered Events` job within the configured cadence (`EVENT_PRUNE_INTERVAL_SECONDS`, default 3600 s).

Deploy order:
1. Merge PR.
2. Roll `nexgen_snmp_worker` with new image.
3. Verify `nexgen_neo4j` has new OPEN THRESHOLD_BREACH events of `event_type='THRESHOLD_BREACH'` for jitter/packet_loss CIs that are currently DOWN.
4. When those CIs come back UP, verify the events transition to RECOVERED in the next cycle.
5. Within 1 h, verify the prune scheduler closes them to CLOSED.

## Open Questions

None for this slice. The 153 OPEN legacy events (`event_type IS NULL` × 138 + `metric_name IS NULL` × 15) are explicitly out of scope and tracked as a separate change. The stale display reset (AD-8) is also deferred — no behavioral question, just a sequencing decision.
