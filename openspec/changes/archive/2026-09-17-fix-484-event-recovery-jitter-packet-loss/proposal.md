# Proposal: fix(events): recover OPEN jitter/packet_loss THRESHOLD_BREACH events when CI returns to normal

## Intent

Close the documented follow-up in [#431](https://github.com/alexandervazquez98/next-gen/issues/431) (PR [#432](https://github.com/alexandervazquez98/next-gen/pull/432) merged 2026-08-28). The 2026-08-28 fix landed `_refresh_icmp_jitter_events` and `_refresh_icmp_packet_loss_events` so that jitter and packet_loss would emit CRITICAL events during outages, but it explicitly listed in its "Known follow-ups" that `_recover_icmp_jitter_events` and `_recover_icmp_packet_loss_events` were out of scope. Three weeks later, OPEN THRESHOLD_BREACH events for these two metrics accumulate and never transition to RECOVERED; the Monitoring Console also keeps showing the last OK value (stale display) when a CI is DOWN by ping.

Issue: [#484](https://github.com/alexandervazquez98/next-gen/issues/484).

## Scope

### In

- **Recovery symmetry.** Add `_recover_icmp_jitter_events(session, jitter_updates)` and `_recover_icmp_packet_loss_events(session, packet_loss_updates)` in `backend/engines/snmp_worker.py`, mirroring `_recover_icmp_latency_events` at line 1093. Add the two calls immediately after line 1762 inside `poll_snmp()`.
- **Synthetic breach on CI DOWN.** In `poll_snmp()`, when a CI has `availability=0` for this cycle and has `icmp.jitter` or `icmp.packet_loss` configured, inject synthetic `THRESHOLD_BREACH` rows (`severity='CRITICAL'`, `value=NULL`, `message='Unable to measure: CI unreachable (availability=0)'`) into the corresponding `jitter_updates` / `packet_loss_updates` before the refresh helpers run.
- **Lock guard registry.** If the new `_recover_*` writers acquire `acquire_event_triplet_lock`, register their `acquisition_functions` paths in `backend/tests/test_event_writer_lock_guard.py::APPROVED_LOCK_PATHS` so CI does not regress.
- **Tests.** Mirror `test_recover_icmp_latency_events_*` in `backend/tests/test_snmp_worker.py` for both new recovery helpers (PROPAGATED exclusion, descendant recovery, no false positive on OK status). Mirror `test_refresh_icmp_jitter_events_*` / `test_refresh_icmp_packet_loss_events_*` for the synthetic-breach path (CI DOWN → CRITICAL row generated; CI UP → no synthetic row).
- **Spec delta.** ADDED Requirements in `openspec/specs/event-prune-recovery-lifecycle/spec.md` extending the ICMP-Latency RECOVERED-eligibility contract to ICMP-Jitter and ICMP-PacketLoss (predicate sites count goes from 4 to 6).

### Out

- **Backfill of the 153 stuck OPEN legacy events** (`event_type IS NULL` × 138 + `metric_name IS NULL` × 15). Decision: deliberately deferred to a separate change. Reason: (a) different code path (one-shot Cypher migration vs. runtime fix), (b) different ownership (data ops vs. backend engineers), (c) does not block the user-visible symptom and would inflate the change budget.
- Changes to `backend/polling/icmp_measurements.py` evaluators. They already return `CRITICAL` on `None` (per #431); no change needed.
- New metrics, new UI components, new API endpoints. The Monitoring Console already renders RECOVERED transitions the same way as today; the fix is invisible to the API surface.
- Re-opening or commenting on #431. Closing the gap is the goal; the conversation there has aged.

## Capabilities

### New

- `_recover_icmp_jitter_events(session, jitter_updates): None` — `backend/engines/snmp_worker.py`. Same shape as `_recover_icmp_latency_events` but matched on `ICMP_JITTER_METRIC_ID`. Filters `e.event_type='THRESHOLD_BREACH'`, `e.status IN ['OPEN','ACK']`, `coalesce(e.correlation_type,'ROOT')='ROOT'`, `row.status=='OK'`. Recovers descendants via `propagated_from = e.id` with `correlation_type='PROPAGATED'`.
- `_recover_icmp_packet_loss_events(session, packet_loss_updates): None` — `backend/engines/snmp_worker.py`. Same shape, matched on `ICMP_PACKET_LOSS_METRIC_ID`.
- Synthetic-breach injection inside `poll_snmp()` — small helper that walks the availability map for this cycle and injects one CRITICAL row per (CI, metric) pair where the real sample is missing and availability is 0.

### Modified

- `poll_snmp()` — `backend/engines/snmp_worker.py:1760-1762`. Two new calls + the synthetic-breach injection (between Pass 2b candidates and Pass 2 refresh helpers, so the synthetic rows pass through the same lock-and-write path as real ones).
- `openspec/specs/event-prune-recovery-lifecycle/spec.md` — ADDED Requirements scenario extending RECOVERED eligibility to ICMP-Jitter and ICMP-PacketLoss.
- `backend/tests/test_snmp_worker.py` — new test classes mirroring `test_recover_icmp_latency_events_*` and `test_refresh_icmp_jitter_events_*` / `test_refresh_icmp_packet_loss_events_*` for the synthetic-breach path.
- `backend/tests/test_event_writer_lock_guard.py` — extend `APPROVED_LOCK_PATHS` if the new recovery writers acquire `acquire_event_triplet_lock`.

## Approach

### Eje 1: Recovery symmetry (the actual bug)

Mirror `_recover_icmp_latency_events` (line 1093, ~50 lines including the descendant branch) for the two missing metric IDs. The Cypher shape is identical except for `m.id = $ICMP_JITTER_METRIC_ID` / `m.id = $ICMP_PACKET_LOSS_METRIC_ID`. Wire both calls from `poll_snmp()` after line 1762 so the recovery pass executes in the same order as the rest of the recovery block. The new functions must filter `e.event_type='THRESHOLD_BREACH'` exactly like the latency version, otherwise they will catch the wrong events.

### Eje 2: Synthetic breach on CI DOWN (the user-visible "stale" symptom)

Today, when `availability=0` for a CI, the ICMP sidecar does not produce jitter/packet_loss samples in that cycle, so `latest_updates` carries no row for those metrics. The refresh helpers therefore see nothing to act on, and `r.HAS_METRIC` keeps the last OK `last_value` / `status` (the stale display). To close this, walk the availability map for the cycle after Pass 2b candidate extraction. For every CI with `availability=0` AND a configured jitter/packet_loss metric, append a synthetic row to the corresponding updates list with `event_type='THRESHOLD_BREACH'`, `status='CRITICAL'`, `value=None`, `message='Unable to measure: CI unreachable (availability=0)'`. The existing `_refresh_icmp_jitter_events` / `_refresh_icmp_packet_loss_events` then persist it as a normal CRITICAL event — no special path. The synthetic breach must NOT fire when the metric is genuinely missing for other reasons (no measurement ever started); gate on `r.HAS_METRIC` existence.

### Eje 3: Stale display reset (optional, deferred)

Cosmetic: after the bulk insert, walk every CI with `availability=0` and reset `r.last_value=NULL`, `r.status='UNKNOWN'`, `r.last_message='CI unreachable'` for `jitter`/`packet_loss` `HAS_METRIC` rows. Decision: deferred. The synthetic breach from Eje 2 already produces a CRITICAL OPEN event that surfaces in the Monitoring Console KPI cards, so the operator gets the right signal. Resyncing the per-metric row is a separate UX concern and would inflate the budget without changing the bug's resolution path.

## Affected Areas

| Area | Files | Impact |
|---|---|---|
| SNMP worker | `backend/engines/snmp_worker.py` | Add 2 functions, 2 callsites, 1 small injection helper. ~120 lines including tests. |
| ICMP measurements | none | No changes needed; evaluators already fail-closed (post #431). |
| Lock guard test | `backend/tests/test_event_writer_lock_guard.py` | Extend `APPROVED_LOCK_PATHS` if needed. |
| Worker tests | `backend/tests/test_snmp_worker.py` | New test classes for both axes. |
| Spec | `openspec/specs/event-prune-recovery-lifecycle/spec.md` | ADDED Requirements scenario. |
| Frontend | none | No UI changes; the Monitoring Console already renders RECOVERED transitions. |
| API surface | none | No new endpoints; existing `/api/events` query already exposes RECOVERED status. |
| Neo4j schema | none | No node/property changes; uses existing `:Event` / `:HAS_METRIC` / `:HAS_AVAILABILITY_SAMPLE`. |
| TimescaleDB | none | No new metrics; uses existing `metric_values` hypertable. |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| New recovery writers accidentally recover events that should not recover (e.g. metric mismatch). | Medium | Tests assert the same filter set as `_recover_icmp_latency_events` (`e.event_type='THRESHOLD_BREACH'`, `metric_id` exact match, `row.status=='OK'`). Synthetic-breach injection is gated on `r.HAS_METRIC` existence to avoid touching CIs without the metric configured. |
| Synthetic breach generates excessive events during transient flapping. | Low | The synthetic row only fires when `availability=0`, which requires sustained unreachability across poll cycles; the existing OPEN→RECOVERED lifecycle handles flap correctly. |
| `poll_snmp()` cycle time grows past `POLLING_CYCLE_SECONDS`. | Low | Two extra Cypher queries (≈10 ms each on the existing topology), one extra Python iteration over the availability map (linear in CI count, ~hundreds). Total cycle delta well under the 10 s budget. |
| Lock guard regression in CI. | Medium | Mirror the existing lock acquisition pattern from `_recover_icmp_latency_events`; register acquisition paths in `APPROVED_LOCK_PATHS` to surface any omission in CI. |
| Spec delta diverges from implementation. | Low | Tests use the same predicate sites listed in the spec; the spec delta is co-authored with the implementation. |

## Rollback Plan

1. Revert the two new functions and the two new calls in `poll_snmp()`. Net: removes ~50 lines + 2 callsites.
2. Revert the synthetic-breach injection helper. Net: removes the per-cycle walk; nothing else changes.
3. Revert `APPROVED_LOCK_PATHS` registration if added.
4. Revert tests.
5. Revert the spec delta (or keep it — it documents the desired contract and is harmless without code).
6. Any OPEN events created by the synthetic breach during the rollout will auto-recover when the CI comes back up via the existing recovery paths OR be pruned by the APScheduler `Event Prune Recovered Events` (1 h cadence, already running).

No data migration required; no Neo4j schema change; no frontend change.

## Success Criteria

- [ ] `_recover_icmp_jitter_events` and `_recover_icmp_packet_loss_events` exist in `backend/engines/snmp_worker.py`, both called from `poll_snmp()`.
- [ ] When a CI oscillates DOWN → UP, an OPEN THRESHOLD_BREACH event for `icmp_jitter_ms` transitions to RECOVERED in the same cycle; same for `icmp_packet_loss_pct`.
- [ ] When `availability=0` for a CI with `icmp.jitter` or `icmp.packet_loss` configured, a CRITICAL THRESHOLD_BREACH event is created within the same cycle (synthetic breach path).
- [ ] Tests added: ≥ 4 strict-TDD test classes mirroring the latency recovery tests, plus ≥ 2 tests covering the synthetic-breach path (CI DOWN → row injected; CI UP → no row).
- [ ] `cd backend && python -m pytest -m event -m metric` green; full suite `cd backend && python -m pytest` green.
- [ ] Spec delta in `openspec/specs/event-prune-recovery-lifecycle/spec.md` lists the new predicate sites (count goes from 4 to 6).
- [ ] `APPROVED_LOCK_PATHS` reflects any new lock acquisitions; CI lock-guard test green.
- [ ] PR merged; CHANGELOG entry under the next version's `### Fixed` referencing #484 and the PR number.

## Dependencies

- **Hard upstream**: PR [#432](https://github.com/alexandervazquez98/next-gen/pull/432) merged 2026-08-28 already shipped `_refresh_icmp_jitter_events` and `_refresh_icmp_packet_loss_events`. Without it, this change would have no events to recover. Verified present on `main`.
- **Hard downstream**: None. The change is self-contained and additive.
- **Related but independent**: Issue #423 (RECOVERED event accumulation / auto-prune) is already fixed; APScheduler job is confirmed running on the production host. This proposal does not touch prune cadence.
- **Related but independent**: The 153 OPEN legacy events backfill is deferred to a separate change. No cross-blocking.
