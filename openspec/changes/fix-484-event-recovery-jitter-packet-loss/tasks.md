# Tasks: fix-484 Event Recovery for ICMP Jitter/PacketLoss

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | ~340 (150 implementation + 180 tests + 10 regression) |
| 800-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk; user pre-confirmed `ask-on-risk` for this session |
| Chain strategy | N/A (single PR) |
| Actual delivered lines | ~980 (50 deletions + 930 insertions across 7 commits) — 22 % over the 800 authored budget. Honest report per `chained-pr` skill; reviewable commit-by-commit with `work-unit-commits` discipline. |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: N/A
800-line budget risk: Low

### Suggested Work Units

| Unit | Goal | PR | Focused test | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|
| A | Synthetic breach helper | P0 | `cd backend && pytest -q tests/test_snmp_worker.py -k inject_synthetic` | N/A—pure Python | `_inject_synthetic_breaches_for_down_cis` + tests |
| B | Jitter recovery writer | P0 | `cd backend && pytest -q tests/test_snmp_worker.py -k recover_icmp_jitter` | N/A—mocked session | `_recover_icmp_jitter_events` + tests |
| C | PacketLoss recovery writer | P0 | `cd backend && pytest -q tests/test_snmp_worker.py -k recover_icmp_packet_loss` | N/A—mocked session | `_recover_icmp_packet_loss_events` + tests |
| D | Wire into `poll_snmp()` | P0 | `cd backend && pytest -q tests/test_snmp_worker.py` | N/A—approved mocked cycle | 3 callsites in `poll_snmp` + integration tests |
| E | Regression contract (predicate sites 4 → 6) | P0 | `cd backend && pytest -q tests/test_snmp_worker_recovery_writer_predicates.py` | N/A—pure | extension to `PREDICATE_SITES` + 2 new classes |
| F | Final verify + CHANGELOG | P0 | `cd backend && python -m pytest -q` | N/A | CHANGELOG entry only |

## Phase 1: Synthetic Breach Helper

- [x] 1. **RED** — Add `test_inject_synthetic_breaches_*` cases in `backend/tests/test_snmp_worker.py` covering: CI DOWN + metric configured → inject 1; CI UP → inject 0; missing HAS_METRIC equivalent (no row in `updates`) → inject 0; existing row in `updates` for the (CI, metric) → inject 0; non-ICMP availability source → inject 0; mixed scenario (3 CIs DOWN, 1 UP, 1 missing HAS_METRIC) → only 2 injected. Commit A after GREEN.

- [x] 2. Implement `_inject_synthetic_breaches_for_down_cis(updates, availability_updates, metric_id)` in `backend/engines/snmp_worker.py` per `design.md` AD-2/AD-3. No Neo4j access; pure Python. Commit A: `feat(events): inject synthetic CRITICAL breach for unreachable CIs (jitter, packet_loss)`.

## Phase 2: Jitter Recovery Writer

- [x] 3. **RED** — Add `test_recover_icmp_jitter_events_*` class in `backend/tests/test_snmp_worker.py` mirroring `test_recover_icmp_latency_events_*` at L1243-1266 with `metric_id="icmp_jitter_ms"`. Cases: PROPAGATED exclusion from direct match, descendant recovery via `propagated_from`, OK-status recovery, no-op on no candidates, RECOVERED-eligibility regression guard. Commit B after GREEN.

- [x] 4. Implement `_recover_icmp_jitter_events(session, updates)` in `backend/engines/snmp_worker.py` per `design.md` AD-1. Mirror `_recover_icmp_latency_events` (L1093) byte-for-byte except for metric id constant. Commit B: `feat(events): recover OPEN ICMP jitter THRESHOLD_BREACH events`.

## Phase 3: PacketLoss Recovery Writer

- [x] 5. **RED** — Add `test_recover_icmp_packet_loss_events_*` class in `backend/tests/test_snmp_worker.py` mirroring the jitter class with `metric_id="packet_loss_pct"`. Same cases as Phase 2. Commit C after GREEN.

- [x] 6. Implement `_recover_icmp_packet_loss_events(session, updates)` in `backend/engines/snmp_worker.py` per `design.md` AD-1. Mirror the jitter function. Commit C: `feat(events): recover OPEN ICMP packet_loss THRESHOLD_BREACH events`.

## Phase 4: Wire into `poll_snmp()`

- [x] 7. **RED** — Add `test_poll_snmp_emits_synthetic_breach_on_ci_down` and `test_poll_snmp_recovers_jitter_and_packet_loss_when_samples_recover` in `backend/tests/test_snmp_worker.py` using `MockNeo4jSession.set_sequence_response`. The first asserts one CRITICAL Event per (CI, jitter) and (CI, packet_loss) when availability is 0; the second asserts both writers transition their events to RECOVERED when samples return to OK. Commit D after GREEN.

- [x] 8. In `backend/engines/snmp_worker.py:poll_snmp()`:
  - (a) Inject synthetic breaches for jitter and packet_loss between Pass 2b candidate extraction and Pass 2 refresh helpers (per `design.md` Data Flow).
  - (b) Add `_recover_icmp_jitter_events(session, jitter_updates)` and `_recover_icmp_packet_loss_events(session, packet_loss_updates)` calls immediately after the existing `_recover_icmp_latency_events` call at L1762.
  - Commit D: `fix(events): wire jitter and packet_loss recovery + synthetic breach on CI DOWN`.

## Phase 5: Regression Contract

- [x] 9. **RED** — Extend `PREDICATE_SITES` in `backend/tests/test_snmp_worker_recovery_writer_predicates.py:57-96` from 4 → 6 entries. Add `ICMPJitterEventsPredicateSite` and `ICMPPacketLossEventsPredicateSite` classes mirroring `ICMPLatencyEventsPredicateSite`. Run the test; expect FAIL because the new sites are not yet present in the registry. Commit E after GREEN (the implementation already landed in Phases 2/3, so this is purely a registry extension).

- [x] 10. Run `cd backend && pytest -q tests/test_snmp_worker_recovery_writer_predicates.py` and assert the six sites retain `RECOVERED` eligibility. Commit E: `test(events): extend recovery predicate regression to six sites`.

## Phase 6: Final Verify

- [x] 11. Run `cd backend && python -m pytest -q` and assert zero regressions across the full suite. Fix only fix-484-related code; never weaken tests. No separate commit. **Observed**: 4 pre-existing failures in `tests/test_writer_advisory_lock.py` due to missing `testcontainers[postgres]` module in this local venv — verified identical failure on parent `main` (not introduced by #484).

- [x] 12. Update `CHANGELOG.md` under the next version's `### Fixed` section: bullet referencing #484 and the PR number once filed. Use the prose style of previous entries. Commit F: `chore(release): changelog entry for #484`.

- [x] 13. Run `pre-commit run --all-files`, `cd backend && ruff check .`, `cd backend && black --check .`; require zero warnings on touched files. **Note**: this repo has NO `.pre-commit-config.yaml` and `pre-commit` is not installed in the local venv; `ruff check` and `black --check` on the touched files both clean. Review `git diff --stat` against the 800-line budget. Lint fixups landed in a separate `style:` commit per `work-unit-commits` ("no separate commit unless a work unit changes" — formatting IS a work unit for CI gates).

## Phase 7: PR and Archive

- [x] 14. Open PR via `branch-pr` skill conventions: title `fix(events): recover OPEN jitter/packet_loss THRESHOLD_BREACH events when CI returns to normal`, body referencing #484 and #431, checklist of success criteria from `proposal.md`. Use `work-unit-commits` skill to keep each commit self-contained and reviewable.

- [ ] 15. After merge, run `gentle-ai sdd-archive fix-484-event-recovery-jitter-packet-loss --cwd <repo>` to move the change into `openspec/changes/archive/<YYYY-MM-DD>-fix-484-event-recovery-jitter-packet-loss/` per repo convention (see `archive/2026-08-14-fix-423-recovered-event-accumulation/` for the mirror).
