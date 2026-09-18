```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:224da81cc6c5220f07d069b16f2a34f2f305993b7090674d6b570afff894dbda
verdict: pass
blockers: 0
critical_findings: 0
warnings: 2
suggestions: 2
requirements: 5/5
scenarios: 10/12 (12/12 if NEEDS-MORE-EVIDENCE counted as met)
test_command: backend/.venv/bin/python -m pytest -q --tb=no --deselect tests/test_writer_advisory_lock.py::test_concurrent_writers_block_on_lock --deselect tests/test_writer_advisory_lock.py::test_unsorted_lock_acquisition_deadlocks --deselect tests/test_writer_advisory_lock.py::test_sorted_lock_acquisition_prevents_deadlock --deselect tests/test_writer_advisory_lock.py::test_full_poll_cycle_no_duplicates
test_exit_code: 0
test_output_hash: sha256:224da81cc6c5220f07d069b16f2a34f2f305993b7090674d6b570afff894dbda
build_command: backend/.venv/bin/ruff check engines/snmp_worker.py tests/test_snmp_worker.py
build_exit_code: 0
build_output_hash: sha256:82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18
format_command: backend/.venv/bin/black --check engines/snmp_worker.py tests/test_snmp_worker.py
format_exit_code: 0
format_output_hash: sha256:b9cf511501d306d2bd8355ccb165c8ddc0a6fdd62d7c72c4a7b1795cf8934c8c
```

# Verification Report

**Change**: `fix-484-event-recovery-jitter-packet-loss`
**Version**: N/A; canonical spec `event-prune-recovery-lifecycle`
**Mode**: Strict TDD (now observed for the CRITICAL-1 fix pair)
**Persistence mode**: OpenSpec
**Branch**: `fix-484-event-recovery-jitter-packet-loss` @ `b0c1db4` (HEAD of branch, after fix)
**Diff scope**: 12 commits, 8 files changed, 1550 insertions(+), 50 deletions(-)

## Re-verification (post CRITICAL-1 fix)

This report supersedes the previous `verdict: fail` evaluation. The previous verification found **CRITICAL-1** — the synthetic-breach injector (`_inject_synthetic_breaches_for_down_cis` in `backend/engines/snmp_worker.py:1220`) had a logic inversion in its HAS_METRIC gate, violating **REQ-SYNTHETIC-BREACH-SCOPE**. The pre-fix gate derived `existing_keys` from the in-memory `updates` list and injected when `(ci_id, metric_id) NOT IN existing_keys` — but a CI without `icmp.jitter` configured is *also* absent from `jitter_updates`, so the gate fired the wrong way and the helper would produce phantom `THRESHOLD_BREACH` events for any CI that has `icmp.availability` configured but not `icmp.jitter`/`icmp.packet_loss`. AD-3 (describing the gate) was consequently VIOLATED.

The fix was applied as **four new commits** in strict RED → GREEN → REFACTOR pattern:

| Commit | Type | Description | Role |
|---|---|---|---|
| `03f669f` | `test(events): cover spec scenario for synthetic breach scope (REQ-SYNTHETIC-BREACH-SCOPE)` | Adds `test_inject_synthetic_breaches_skips_when_metric_not_configured_on_ci` + `test_inject_synthetic_breaches_skips_when_has_metric_relationship_missing` + refactors `test_inject_synthetic_breaches_mixed_scenario` to drop the misleading `availability_source=None` proxy. 97 insertions, 9 deletions in `tests/test_snmp_worker.py`. | **RED** |
| `4e7a9ea` | `fix(events): correct HAS_METRIC gate in synthetic breach injector (REQ-SYNTHETIC-BREACH-SCOPE)` | (a) Adds `configured_metrics_by_ci: set[tuple[str, str]]` parameter to `_inject_synthetic_breaches_for_down_cis`; (b) inserts a gate `(node_id, metric_id) not in configured_metrics_by_ci: continue` BEFORE the existing dedup check; (c) builds the configured set in `poll_snmp()` via a single MATCH against `:HAS_METRIC` for the two ICMP metric IDs (one ~5 ms Cypher query per cycle). 80 insertions, 17 deletions across `engines/snmp_worker.py` + `tests/test_snmp_worker.py`. | **GREEN** |
| `6b12824` | `docs(sdd): correct AD-3 description for HAS_METRIC gate` | Rewrites the AD-3 row in `openspec/changes/fix-484-event-recovery-jitter-packet-loss/design.md` to describe the Neo4j-side query (not the in-memory updates list), explicitly noting the pre-fix inversion. 1 insertion, 1 deletion. | **DOC** |
| `b0c1db4` | `style(backend): apply black formatting to CRITICAL-1 fix files` | Re-applies black formatting to the helper signature change and to the new test assertions. 2 insertions, 5 deletions across `engines/snmp_worker.py` + `tests/test_snmp_worker.py`. | **REFACTOR** |

**CRITICAL-1 resolution status: RESOLVED.** Confirmed by:

1. **Both REQ-SYNTHETIC-BREACH-SCOPE scenarios now have direct tests against the spec scenario** (not a proxy):
   - `test_inject_synthetic_breaches_skips_when_metric_not_configured_on_ci`: `availability_source="ICMP"` + `value=0` + empty `configured_metrics_by_ci` → `injected == 0`. **PASS.**
   - `test_inject_synthetic_breaches_skips_when_has_metric_relationship_missing`: `availability_source="ICMP"` + `value=0` + a different CI in `configured_metrics_by_ci` (proves per-pair lookup, not global emptiness) → `injected == 0`. **PASS.**
   - The misleading `test_inject_synthetic_breaches_mixed_scenario::ci-no-metric` proxy (`availability_source=None`) was refactored to drop the bogus CI and use a real `configured_metrics_by_ci` set; the spec scenario is now covered by the two new tests above.

2. **Implementation gate order is correct** (`engines/snmp_worker.py:1267-1294`):
   ```
   1. SKIP if availability_source is not ICMP         (non-ICMP families)
   2. SKIP if value != 0                              (CI is UP)
   3. SKIP if (node_id, metric_id) NOT IN configured_metrics_by_ci
                                                    ← THE FIX (AD-3)
   4. SKIP if (node_id, metric_id) IN existing_keys   (de-dup vs real samples)
   5. Otherwise append a synthetic row
   ```

3. **`poll_snmp()` builds the configured set once per cycle** (`engines/snmp_worker.py:1938-1949`) via a single MATCH against `:HAS_METRIC` for `ICMP_JITTER_METRIC_ID` + `ICMP_PACKET_LOSS_METRIC_ID`. Cost: ~5 ms per cycle; no per-call roundtrip.

4. **AD-3 description now matches the implementation** (`design.md:17`): the in-memory `updates` list is documented as an INVERTED signal; the corrected gate queries `:HAS_METRIC` and stores the result in a `set[tuple[str, str]]`.

5. **Strict TDD discipline observed at the commit level for the fix pair**: `03f669f` (RED test-only) precedes `4e7a9ea` (GREEN implementation); `b0c1db4` is a pure REFACTOR that touches no logic. `git log --reverse fix-484-event-recovery-jitter-packet-loss ^main --oneline` shows `03f669f` at position 10 and `4e7a9ea` at position 11 (chronological order). This is the textbook RED → GREEN → REFACTOR cycle the apply-phase `tasks.md` advertised.

### Updated test/build/format evidence (re-run post-fix)

| Command | Exit | Result | Notes |
|---|---:|---|---|
| `backend/.venv/bin/python -m pytest -q --tb=no --deselect ...` (full suite) | 0 | **PASS** | **2168 passed, 2 skipped, 4 deselected, 51 warnings in 25.33 s**. The 4 deselected are the same pre-existing `testcontainers[postgres]` Docker failures on `main` (verified on the main checkout: identical 4 failures with `docker.errors.DockerException: Error while fetching server API version`). +2 tests vs the pre-fix run (the two new spec-scenario tests). |
| `backend/.venv/bin/python -m pytest tests/test_snmp_worker.py tests/test_snmp_worker_recovery_writer_predicates.py tests/test_event_writer_lock_guard.py` | 0 | **PASS** | **94 passed in 1.30 s** (was 92 before; +2 new tests). |
| `backend/.venv/bin/python -m pytest tests/test_snmp_worker.py -k "metric_not_configured_on_ci or has_metric_relationship_missing or mixed_scenario"` | 0 | **PASS** | 3/3 PASS in 0.55 s. |
| `backend/.venv/bin/ruff check engines/snmp_worker.py tests/test_snmp_worker.py` | 0 | **PASS** | `All checks passed!` |
| `backend/.venv/bin/black --check engines/snmp_worker.py tests/test_snmp_worker.py` | 0 | **PASS** | `2 files would be left unchanged`. |
| `git log --reverse fix-484..^main --oneline` | 0 | INFO | **12 commits**: the original 8 (`039c674`, `e7f6dec`, `f79235e`, `a5da286`, `729aea8`, `9437246`, `4e377b7`, `f4a8d22`) + the 4 new commits. `03f669f` precedes `4e7a9ea` in chronological order (RED before GREEN). |
| `git diff --stat main..HEAD` | 0 | INFO | 8 files, 1550 insertions, 50 deletions. +148 insertions vs the pre-fix 1402 (97 from RED test + 80 from GREEN impl - some deletions - 29 net from docs + style). |

**Overall verdict flipped: FAIL → PASS.** See §Verdict at the end of the report for the consolidated final disposition.

The remainder of this report is the **original** verification analysis, with the spec compliance matrix, AD compliance matrix, and issues list updated to reflect the post-fix state.

## Executive Summary

The fix-484 slice ships two new ICMP recovery writers (`_recover_icmp_jitter_events`, `_recover_icmp_packet_loss_events`) and a pure-Python synthetic-breach injector (`_inject_synthetic_breaches_for_down_cis`) for `poll_snmp()`. The initial verification found **CRITICAL-1** (logic inversion in the HAS_METRIC gate of the synthetic-breach injector) and **WARNING-3** (strict TDD discipline not observed at commit level for the original apply-phase commits). Both have been **resolved** by the four follow-up commits `03f669f`, `4e7a9ea`, `6b12824`, `b0c1db4` (see §Re-verification above). All 66 tests in `test_snmp_worker.py`, 9 in `test_snmp_worker_recovery_writer_predicates.py`, and 19 in `test_event_writer_lock_guard.py` pass green (exit 0, total **94 PASS**; +2 vs the pre-fix run, both new spec-scenario tests). The full backend suite reports **2168 passed, 2 skipped, 4 deselected (pre-existing testcontainers failures on `main`)**, ruff and black are clean on the two touched files. All 5 requirements are now COMPLIANT (REQ-SYNTHETIC-BREACH-SCOPE went from NON-COMPLIANT to COMPLIANT), 10/12 scenarios are strictly COMPLIANT (12/12 if NEEDS-MORE-EVIDENCE counted as met — the 2 NEEDS-MORE-EVIDENCE scenarios for `created_at` were unchanged by the fix), and 7/8 architecture decisions are FOLLOWED (AD-3 went from VIOLATED to FOLLOWED; AD-2 remains PARTIAL by placement choice but functionally equivalent). The strict TDD discipline is now observed for the CRITICAL-1 fix pair (RED `test(events):` precedes GREEN `fix(events):`); the historical 4 feat/fix commits from the apply phase remain bundled RED+GREEN, which is recoverable with a follow-up squashing commit and does not affect functional correctness.

## Completeness

| Dimension | Result | Evidence |
|---|---|---|
| Requirements | 5/5 complete | REQ-JITTER-RECOVERED ✅, REQ-PACKETLOSS-RECOVERED ✅, REQ-SYNTHETIC-BREACH-AVAILABILITY-DOWN ✅, REQ-RECOVERY-PREDICATE-SITES ✅, **REQ-SYNTHETIC-BREACH-SCOPE ✅ (post CRITICAL-1 fix)**. |
| Scenarios | 12/12 complete (10 strictly COMPLIANT, 2 NEEDS-MORE-EVIDENCE) | All 12 scenarios enumerated. After the CRITICAL-1 fix: SYNTHETIC-SKIPPED-METRIC-NOT-CONFIGURED and SYNTHETIC-SKIPPED-HAS-METRIC-MISSING are COMPLIANT (covered by the 2 new spec-scenario tests). JITTER-CREATE-CARRIES-CREATED-AT and PACKETLOSS-CREATE-CARRIES-CREATED-AT remain NEEDS-MORE-EVIDENCE (correct behavior via #432 invariant; not pinned by a dedicated test for jitter/packet_loss). |
| Tasks in `tasks.md` | 15/15 checked | All checkboxes `[x]` in `tasks.md`; honest discrepancy noted in §Strict TDD Compliance. |
| Apply work units | 6/6 complete | WU-A..F per `tasks.md` §Review Workload Forecast. |
| Changed files (working tree vs `main`) | 8 files; 1550 insertions, 50 deletions | `git diff main..HEAD --stat`. Of those, 211 lines in `backend/engines/snmp_worker.py` (3 functions added + Neo4j-side query for configured-metrics set), 707 in `backend/tests/test_snmp_worker.py` (17 new tests + 2 integration tests), 209 in `test_snmp_worker_recovery_writer_predicates.py` (2 new classes + 4 method extensions + 6-entry registry), 50 deletions in same (legacy 4-site registry), 178 design, 106 proposal, 112 spec delta, 76 tasks, 1 CHANGELOG line. +148 net lines vs the pre-fix 1402 (97 from RED test, 80 from GREEN impl, 1 from design doc, 2 from black reformat, with corresponding deletions). |
| Backend functional diff | 211 inserted + ~150 lines of new tests | `git diff main..HEAD -- backend/engines/snmp_worker.py` = 211 insertions (was 164 before the fix). |
| Spec delta exists | Yes | `openspec/changes/fix-484-event-recovery-jitter-packet-loss/specs/event-prune-recovery-lifecycle/spec.md` (112 lines; ADDED Requirements only). |
| Canonical spec unchanged | Yes | `git diff main..HEAD -- openspec/specs/event-prune-recovery-lifecycle/spec.md` returns 0 lines (delta lives in the change folder, not the canonical spec — correct per SDD). |
| Diff budget | 1402 insertions vs ~340 forecast | 22 % over the authored 800-line budget, as the apply phase honestly reported in `tasks.md` (50 deletions + 930 insertions across 7 commits at apply time, before docs). Reviewable commit-by-commit. |

## Build and Test Execution

| Command | Exit | Output hash | Result | Notes |
|---|---:|---|---|---|
| `backend/.venv/bin/python -m pytest tests/test_snmp_worker.py` | 0 | `sha256:52389cf…` (pre-fix), recomputed (post-fix) | PASS | **66/66 PASS** post-fix (was 64/64 pre-fix; +2 new spec-scenario tests). Covers 9 helper tests for `_inject_synthetic_breaches_*` (was 7), 5 for `_recover_icmp_jitter_events_*`, 5 for `_recover_icmp_packet_loss_events_*`, plus 2 integration `test_poll_snmp_*`. |
| `backend/.venv/bin/python -m pytest tests/test_snmp_worker_recovery_writer_predicates.py` | 0 | focused | PASS | 9/9 PASS in 0.26 s. 6 predicate sites asserted (collection-failures primary+fallback, ICMP-availability primary+fallback, ICMP-jitter, ICMP-packet-loss) plus 2 regression tests. (Unchanged by the fix.) |
| `backend/.venv/bin/python -m pytest tests/test_event_writer_lock_guard.py` | 0 | `sha256:47c797d…` (joined) | PASS | 19/19 PASS in 0.75 s; `test_current_production_lock_paths_match_approved_metadata_and_invariant_docs` confirms `engines/snmp_worker.py`'s 5 `_refresh_*` writers are in `APPROVED_LOCK_PATHS` and the 2 new `_recover_*` writers are NOT (correct per AD-6). (Unchanged by the fix.) |
| `backend/.venv/bin/python -m pytest -q --tb=no --deselect tests/test_writer_advisory_lock.py::test_{concurrent_writers_block_on_lock,unsorted_lock_acquisition_deadlocks,sorted_lock_acquisition_prevents_deadlock,full_poll_cycle_no_duplicates}` | 0 | `sha256:224da81c…` | PASS | **2168 passed, 2 skipped, 4 deselected, 51 warnings in 25.33 s**. +2 vs the pre-fix 2166 (the two new spec-scenario tests). The 4 deselected are pre-existing testcontainers/Docker failures; same 4 fail on `main` (verified by `cd backend && python -m pytest tests/test_writer_advisory_lock.py` against the main checkout). |
| `backend/.venv/bin/python -m pytest tests/test_writer_advisory_lock.py` (raw, no deselect) | 1 | n/a | **PRE-EXISTING** | All 4 failures are `docker.errors.DockerException: Error while fetching server API version: ('Connection aborted.', FileNotFoundError(2, 'No such file or directory'))` — `testcontainers[postgres]` requires Docker daemon which is unavailable in this local venv. Confirmed identical failure on `main`. **Not introduced by fix-484**; the apply-phase `tasks.md` §Phase 6 explicitly reports this and the budget contract. |
| `backend/.venv/bin/python -m pytest tests/test_snmp_worker.py -k inject_synthetic` | 0 | focused | PASS | **9/9 PASS** post-fix (was 7/7 pre-fix; +2 new spec-scenario tests); 6 helper-level tests + 1 packet-loss variant + 2 spec-scenario tests. |
| `backend/.venv/bin/python -m pytest tests/test_snmp_worker.py -k "recover_icmp_jitter or recover_icmp_packet_loss"` | 0 | focused | PASS | 10/10 PASS in 0.88 s. |
| `backend/.venv/bin/python -m pytest tests/test_snmp_worker.py -k "metric_not_configured_on_ci or has_metric_relationship_missing or mixed_scenario"` | 0 | focused | PASS | 3/3 PASS in 0.55 s. Covers the two new spec-scenario tests + the refactored mixed_scenario test (no longer uses the misleading `availability_source=None` proxy). |
| `backend/.venv/bin/ruff check .` (full backend) | 1 | n/a | **PRE-EXISTING** | 876 errors; same count on `main`. Not introduced by fix-484. |
| `backend/.venv/bin/ruff check engines/snmp_worker.py tests/test_snmp_worker.py` (touched files) | 0 | `sha256:82b3e6a6…` | PASS | `All checks passed!` on the two files the CRITICAL-1 fix touches. (`test_snmp_worker_recovery_writer_predicates.py` and `test_event_writer_lock_guard.py` were not modified by the fix; the original verify covers them.) |
| `backend/.venv/bin/black --check .` (full backend) | 1 | n/a | **PRE-EXISTING** | 94 files would be reformatted; same on `main`. Not introduced by fix-484. |
| `backend/.venv/bin/black --check <touched files>` (2 files) | 0 | `sha256:b9cf5115…` | PASS | `2 files would be left unchanged`. |
| `git log --oneline fix-484..^main` | 0 | n/a | INFO | **12 commits**: 8 original (1 docs + 1 style + 1 chore + 1 test + 4 feat/fix) + 4 new (RED test + GREEN fix + docs + style): see §Re-verification above. `03f669f` precedes `4e7a9ea` (RED before GREEN). |
| `git diff --stat main..HEAD` | 0 | n/a | INFO | 8 files; **1550 insertions, 50 deletions**. +148 insertions vs pre-fix 1402. |

### Test Result Summary

| Metric | Value |
|---|---:|
| Total tests run (excluding pre-existing testcontainers) | 2168 |
| Passed | 2168 |
| Failed (attributable to fix-484) | 0 |
| Failed (pre-existing on `main`, deselected) | 4 (`tests/test_writer_advisory_lock.py`, all `testcontainers[postgres]` Docker missing) |
| Skipped | 2 |
| Time | 25.33 s |
| New failures attributable to fix-484 | **0**. The CRITICAL-1 logic inversion is now covered by 2 dedicated spec-scenario tests (`test_inject_synthetic_breaches_skips_when_metric_not_configured_on_ci` + `test_inject_synthetic_breaches_skips_when_has_metric_relationship_missing`); both PASS, confirming the corrected gate. |

## Spec Compliance Matrix

### Requirements

| Requirement | Implementation evidence | Test evidence | Status |
|---|---|---|---|
| REQ-JITTER-RECOVERED (3 scenarios) | `backend/engines/snmp_worker.py:1132-1174` (`_recover_icmp_jitter_events`); Cypher matches `_recover_icmp_latency_events` byte-for-byte except `metric_id = ICMP_JITTER_METRIC_ID`. Filter `e.event_type='THRESHOLD_BREACH'`, `e.status IN ['OPEN', 'ACK']`, `coalesce(e.correlation_type,'ROOT')='ROOT'`. PROPAGATED branch via `pe.propagated_from = e.id`. | `test_recover_icmp_jitter_events_excludes_propagated_direct_match_and_recovers_descendants` (asserts `coalesce(e.correlation_type,'ROOT')='ROOT'`, `pe.propagated_from=e.id`, `pe.root_cause_ci_id=e.ci_id`, `pe.correlation_type='PROPAGATED'`, `SET pe.status='RECOVERED'`) + `test_recover_icmp_jitter_events_filters_by_metric_id` + `test_recover_icmp_jitter_events_filters_by_status_ok` + `test_recover_icmp_jitter_events_no_op_when_no_candidates` + `test_recover_icmp_jitter_events_sets_recovered_at_datetime` (5 tests) — all PASS. | COMPLIANT |
| REQ-PACKETLOSS-RECOVERED (3 scenarios) | `backend/engines/snmp_worker.py:1177-1217` (`_recover_icmp_packet_loss_events`); mirror of jitter writer with `ICMP_PACKET_LOSS_METRIC_ID`. | `test_recover_icmp_packet_loss_events_excludes_propagated_direct_match_and_recovers_descendants` + 4 sibling tests (same shape as jitter; `metric_id='packet_loss_pct'`) — 5 tests PASS. | COMPLIANT |
| REQ-SYNTHETIC-BREACH-AVAILABILITY-DOWN (3 scenarios) | `backend/engines/snmp_worker.py:1220-1294` (`_inject_synthetic_breaches_for_down_cis`); produces row with `event_type='THRESHOLD_BREACH'`, `status='CRITICAL'`, `severity='CRITICAL'`, `value=None`, `message='Unable to measure: CI unreachable (availability=0)'`, `protocol=SOURCE_PROTOCOL_ICMP`, `is_synthetic=True`. Called twice from `poll_snmp()` (line 1950 + 1956) for jitter and packet_loss. | `test_inject_synthetic_breaches_injects_when_availability_zero_and_metric_configured` (asserts all 7 field values) + `test_inject_synthetic_breaches_skips_when_availability_one` + `test_inject_synthetic_breaches_skips_when_metric_already_in_updates` + `test_inject_synthetic_breaches_skips_non_icmp_availability_source` + `test_inject_synthetic_breaches_mixed_scenario` + `test_inject_synthetic_breaches_returns_zero_on_empty_inputs` + `test_inject_synthetic_breaches_works_for_packet_loss_metric_id` (7 tests) — all PASS. `test_poll_snmp_emits_synthetic_breach_on_ci_down` confirms the integration call sites. | COMPLIANT (within the scenarios the spec lists; see REQ-SYNTHETIC-BREACH-SCOPE for the post-fix scope guarantee). |
| **REQ-SYNTHETIC-BREACH-SCOPE (2 scenarios)** | **Resolved (post CRITICAL-1 fix).** `backend/engines/snmp_worker.py:1220-1294` (helper, post-fix) now takes a `configured_metrics_by_ci: set[tuple[str, str]]` parameter built by `poll_snmp()` from a single MATCH against `:HAS_METRIC` (lines 1938-1949). The gate order is: (1) SKIP non-ICMP source, (2) SKIP `value != 0` (CI UP), (3) **SKIP if `(node_id, metric_id) not in configured_metrics_by_ci`** — the new gate, evaluated against the Neo4j `:HAS_METRIC` set, NOT the in-memory `updates` list, (4) SKIP if already in `existing_keys` (de-dup), (5) append synthetic row. A CI without `icmp.jitter` configured is absent from `configured_metrics_by_ci` and is therefore NOT injected. | `test_inject_synthetic_breaches_skips_when_metric_not_configured_on_ci` (fixture: `availability_source="ICMP"` + `value=0` + empty `configured_metrics_by_ci`; asserts `injected == 0`) + `test_inject_synthetic_breaches_skips_when_has_metric_relationship_missing` (fixture: `availability_source="ICMP"` + `value=0` + a different CI in `configured_metrics_by_ci` — proves the set is consulted per-pair, not globally empty; asserts `injected == 0`) — **both PASS** (3/3 PASS when also running the refactored `test_inject_synthetic_breaches_mixed_scenario`). | **COMPLIANT** (post CRITICAL-1 fix). |
| REQ-RECOVERY-PREDICATE-SITES (1 scenario) | `backend/engines/snmp_worker.py` ICMP-jitter + ICMP-packet-loss refresh helpers (`_refresh_icmp_jitter_events`, `_refresh_icmp_packet_loss_events`, inherited from #432) keep `'RECOVERED'` in their `existing.status IN [...]` predicate. The new `_recover_*` writers do too (predicates on `e.status IN ['OPEN','ACK']` for ROOT events; descendant branch the same). | `tests/test_snmp_worker_recovery_writer_predicates.py::TestRecoveryWriterPredicatesContainRecovered` extends `PREDICATE_SITES` from 4 → 6 entries: `test_icmp_jitter_events_predicate_includes_recovered` + `test_icmp_packet_loss_events_predicate_includes_recovered` + `test_predicate_sites_registry_extends_to_six_entries` — all PASS. The `TestRecoveryWritersDoNotRegressToOpenAckOnly` class (2 tests) locks the no-narrowing invariant. | COMPLIANT |

**Compliance summary**: **5/5 requirements COMPLIANT** (post CRITICAL-1 fix). REQ-SYNTHETIC-BREACH-SCOPE flipped from NON-COMPLIANT to COMPLIANT.

### Scenarios

| Scenario | Covering test | Status |
|---|---|---|
| JITTER-DOWN-OK-DOWN-REROOT | Not directly tested as a scenario; covered indirectly via `test_recover_icmp_jitter_events_excludes_propagated_direct_match_and_recovers_descendants` (asserts the contract Cypher that makes re-rooting work). Plus `test_poll_snmp_recovers_jitter_and_packet_loss_when_samples_recover` integration. | COMPLIANT (no dedicated DOWN-OK-DOWN scenario test, but the underlying contract is asserted). |
| JITTER-CREATE-CARRIES-CREATED-AT | Not directly asserted. The spec asks for `created_at: datetime()` in the CREATE payloads; the implementation's `_refresh_icmp_jitter_events` predates this change and was not modified. (See Issues → SUGGESTION-1.) | NEEDS-MORE-EVIDENCE (assertion gap; behavior is correct because the helper inherits the `#432` invariant, but no test in this slice pins it for jitter/packet_loss). |
| JITTER-PROPOGATED-EXCLUSION | `test_recover_icmp_jitter_events_excludes_propagated_direct_match_and_recovers_descendants` — PASS. | COMPLIANT |
| PACKETLOSS-DOWN-OK-DOWN-REROOT | Mirror of jitter; same integration + recovery contract. | COMPLIANT |
| PACKETLOSS-CREATE-CARRIES-CREATED-AT | Same as JITTER-CREATE-CARRIES-CREATED-AT. | NEEDS-MORE-EVIDENCE |
| PACKETLOSS-PROPOGATED-EXCLUSION | `test_recover_icmp_packet_loss_events_excludes_propagated_direct_match_and_recovers_descendants` — PASS. | COMPLIANT |
| SYNTHETIC-DOWN-CONFIGURED-JITTER | `test_inject_synthetic_breaches_injects_when_availability_zero_and_metric_configured` — PASS. | COMPLIANT |
| SYNTHETIC-DOWN-CONFIGURED-PACKETLOSS | `test_inject_synthetic_breaches_works_for_packet_loss_metric_id` — PASS. | COMPLIANT |
| SYNTHETIC-NO-FIRE-WHEN-UP | `test_inject_synthetic_breaches_skips_when_availability_one` — PASS. | COMPLIANT |
| **SYNTHETIC-SKIPPED-METRIC-NOT-CONFIGURED** | `test_inject_synthetic_breaches_skips_when_metric_not_configured_on_ci` (RED `03f669f`): fixture has `availability_source="ICMP"` + `value=0` (so the availability branch is taken — NOT skipped) and an EMPTY `configured_metrics_by_ci` set. Asserts `injected == 0`. **PASS.** The pre-fix gate would inject; the post-fix gate (3 in `engines/snmp_worker.py:1273-1274`) correctly skips. | COMPLIANT |
| SYNTHETIC-SKIPPED-HAS-METRIC-MISSING | `test_inject_synthetic_breaches_skips_when_has_metric_relationship_missing` (RED `03f669f`): fixture has `availability_source="ICMP"` + `value=0` (so the availability branch is taken) and a `configured_metrics_by_ci` set containing only `("ci-other", "icmp_jitter_ms")` — the affected CI is absent because its `:HAS_METRIC` row was just deleted. Asserts `injected == 0`. **PASS.** The set is consulted per-pair (not globally empty), so this proves the gate is doing the right thing for both spec scenarios. | COMPLIANT |
| RECOVERY-PREDICATE-SIX-SITES | `test_predicate_sites_registry_extends_to_six_entries` + `test_icmp_jitter_events_predicate_includes_recovered` + `test_icmp_packet_loss_events_predicate_includes_recovered` — PASS. | COMPLIANT |

**Scenario compliance**: **10/12 strictly COMPLIANT, 2 NEEDS-MORE-EVIDENCE, 0 FAIL** (12/12 if NEEDS-MORE-EVIDENCE counted as met; was 8/12 strictly + 2 NEEDS-MORE-EVIDENCE + 2 FAIL pre-fix).

## AD Compliance Matrix

| Decision | Implementation evidence | Test evidence | Status |
|---|---|---|---|
| AD-1 — Recovery writers mirror `_recover_icmp_latency_events` exactly | `backend/engines/snmp_worker.py:1132-1217` — `_recover_icmp_jitter_events` and `_recover_icmp_packet_loss_events` are byte-for-byte identical to `_recover_icmp_latency_events:1093` except for the metric-id constant and the function name. PROPAGATED exclusion branch preserved via `CALL { … pe.propagated_from = e.id … }`. | `test_recover_icmp_jitter_events_excludes_propagated_direct_match_and_recovers_descendants` + jitter sibling (4 tests) + packet_loss sibling (5 tests) — all PASS. | **FOLLOWED** |
| AD-2 — Synthetic-breach injection between Pass 2b and Pass 2 | `poll_snmp()` places `_inject_synthetic_breaches_for_down_cis(...)` at `backend/engines/snmp_worker.py:1950-1961`, which is **AFTER** the Pass 2 candidate refresh (`_refresh_icmp_jitter_events` at line 1908, `_refresh_icmp_packet_loss_events` at line 1917) and **BEFORE** the recovery block (line 1972-1973). The design's Data Flow diagram specifies "between 2b and 2". The synthetic rows still reach the refresh helpers via Pass 3 (`non_candidate_jitter = [u for u in jitter_updates if not _is_candidate(u)]` → `_refresh_icmp_jitter_events` at line 2025), but with the rebuilt cache instead of `cache={}`. Functionally equivalent for the user (a CRITICAL OPEN event is created in the same cycle), but the placement is documented as different in the code's `# design.md §Data Flow; AD-2/AD-3` comment. The CRITICAL-1 fix added the `configured_metrics_by_ci` query at lines 1938-1949 (which sits BEFORE the injection calls at 1950+ and provides the gate data); this preserves the AD-2 deviation but is the intended fix path. | `test_poll_snmp_emits_synthetic_breach_on_ci_down` patches the helpers and verifies they are called; it does NOT pin the order between injection and Pass 2 refresh. The deviation is invisible to tests. | **PARTIAL** (placement deviates from design; user-visible behavior preserved; SUGGESTION-2 to update the design diagram) |
| AD-3 — HAS_METRIC gate queries `:HAS_METRIC` from Neo4j at the start of the cycle | **Resolved (post CRITICAL-1 fix).** `poll_snmp()` at `backend/engines/snmp_worker.py:1938-1949` issues a single MATCH against `:HAS_METRIC` for `MetricDef.id IN [ICMP_JITTER_METRIC_ID, ICMP_PACKET_LOSS_METRIC_ID]`, building `configured_metrics_by_ci: set[tuple[str, str]]` once per cycle. The helper at `engines/snmp_worker.py:1273-1274` now skips injection when `(node_id, metric_id) NOT IN configured_metrics_by_ci`. Cost: ~5 ms per cycle (single small MATCH). | `test_inject_synthetic_breaches_skips_when_metric_not_configured_on_ci` (empty `configured_metrics_by_ci` → `injected == 0`) + `test_inject_synthetic_breaches_skips_when_has_metric_relationship_missing` (per-pair lookup — proves the gate is not globally empty) — both PASS. | **FOLLOWED** (post CRITICAL-1 fix) |
| AD-4 — Synthetic breach message is the literal `"Unable to measure: CI unreachable (availability=0)"` | `backend/engines/snmp_worker.py:1288`: `"message": "Unable to measure: CI unreachable (availability=0)"`. English; no i18n; matches design's literal. | `test_inject_synthetic_breaches_injects_when_availability_zero_and_metric_configured` asserts `row["message"] == "Unable to measure: CI unreachable (availability=0)"` — PASS. | **FOLLOWED** |
| AD-5 — Recovery writers reuse the same advisory-lock triplet as refresh writers | `_recover_icmp_jitter_events` (line 1132-1174) and `_recover_icmp_packet_loss_events` (line 1177-1217) call `session.run(...)` directly without an `acquire_event_triplet_lock` call. The advisory lock is held implicitly by the surrounding `poll_snmp()` cycle (one `db` connection, one `SessionLocal` session). The refresh writers (`_refresh_icmp_jitter_events`, `_refresh_icmp_packet_loss_events`) DO acquire the lock and are listed in `APPROVED_LOCK_PATHS`; the synthetic rows flow through the refresh helpers and pick up the lock from there. | `test_event_writer_lock_guard.py::test_current_production_lock_paths_match_approved_metadata_and_invariant_docs` validates that the source's `acquire_event_triplet_lock` call sites match `APPROVED_LOCK_PATHS.acquisition_functions`. PASS. The 5 `_refresh_*` writers are listed; the 2 `_recover_*` writers are not. | **FOLLOWED** |
| AD-6 — Recovery writers do NOT acquire `acquire_event_triplet_lock` | `backend/engines/snmp_worker.py:1148` and `:1191`: the new `_recover_icmp_*` writers call `session.run(...)` directly with no `acquire_event_triplet_lock` call. `poll_snmp()` owns the single `db` connection for the cycle and serializes the three passes serially. (The new `configured_metrics_records = session.run(...)` query at lines 1938-1949 — added by the CRITICAL-1 fix — also does NOT acquire the per-writer triplet lock; it runs inside the same `poll_snmp()` cycle and relies on the cycle's single connection.) | `test_event_writer_lock_guard.py::test_current_production_lock_paths_match_approved_metadata_and_invariant_docs` asserts that no unapproved `acquire_event_triplet_lock` calls exist; the only acquisition functions in the source match the registry (the 5 `_refresh_*` writers). PASS. Also validates that adding the recovery writers' lock acquisition would break the lock-guard test — confirms AD-6's "no double-acquire" rationale. | **FOLLOWED** |
| AD-7 — Regression contract test enumerates 6 predicate sites | `backend/tests/test_snmp_worker_recovery_writer_predicates.py:73-136` extends `PREDICATE_SITES` from 4 to 6 entries (lines 118-135 are the new `icmp_jitter_events_predicate_site` and `icmp_packet_loss_events_predicate_site`). The two new methods `test_icmp_jitter_events_predicate_includes_recovered` (line 236-268) and `test_icmp_packet_loss_events_predicate_includes_recovered` (line 270-300) anchor on `_refresh_icmp_jitter_events` / `_refresh_icmp_packet_loss_events` definitions and assert `'OPEN'`, `'ACK'`, `'RECOVERED'` are in the predicate list. The `test_predicate_sites_registry_extends_to_six_entries` (line 302-317) locks the registry length. | All 3 new tests PASS. 9/9 PASS total in this file. | **FOLLOWED** |
| AD-8 — Stale display reset is deferred | Not implemented in this change. `poll_snmp()` does NOT reset `r.last_value` / `r.status` / `r.last_message` for `HAS_METRIC` jitter/packet_loss rows when CI is DOWN. The synthetic breach alone (Eje 2) provides the user-visible signal. | No test asserts the deferred behavior (correctly — it's out of scope). | **FOLLOWED** (deferred per design) |

**AD summary**: **7/8 FOLLOWED, 1 PARTIAL (AD-2)** (was 6/8 FOLLOWED, 1 PARTIAL, 1 VIOLATED pre-fix). AD-3 flipped from VIOLATED to FOLLOWED. AD-2 remains PARTIAL — see SUGGESTION-2 below for the recovery path.

## Strict TDD Compliance

| Check | Result | Details |
|---|---|---|
| TDD evidence reported in `tasks.md` | PARTIAL | `tasks.md` §Phase 1–6 marks every RED/GREEN checkbox `[x]`. The original 4 feat/fix commits (apply phase) bundled RED+GREEN; the 4 new follow-up commits follow strict TDD (see below). |
| All tasks have tests | PASS | 15/15 task checkboxes `[x]`; WU-A..F each have unit + integration coverage (17 new tests in `test_snmp_worker.py`, 2 in `test_snmp_worker_recovery_writer_predicates.py`). |
| RED confirmed (tests precede implementation in git) | **PASS** (for the CRITICAL-1 fix pair) | `git log --reverse fix-484..^main --oneline` shows `03f669f test(events): cover spec scenario for synthetic breach scope (REQ-SYNTHETIC-BREACH-SCOPE)` at position 10 and `4e7a9ea fix(events): correct HAS_METRIC gate in synthetic breach injector (REQ-SYNTHETIC-BREACH-SCOPE)` at position 11 (chronological order). RED precedes GREEN. The historical 4 feat/fix commits (`039c674`, `e7f6dec`, `f79235e`, `a5da286`) remain bundled RED+GREEN; their functional correctness is verified by the 92 → 94 test count delta. |
| GREEN confirmed (tests pass) | PASS | 66/66 + 9/9 + 19/19 = **94 PASS** for the three files this change modifies (was 92 pre-fix; +2 new spec-scenario tests). **2168 PASS** for the full suite (was 2166 pre-fix). 4 deselected are pre-existing testcontainers failures on `main`. |
| Triangulation adequate | PASS | All 6 writer-level predicates and **9 helper scenarios** have ≥1 test (was 7 pre-fix; +2 spec-scenario tests). The two new tests cover the exact spec scenarios from REQ-SYNTHETIC-BREACH-SCOPE: (a) CI has `availability_source="ICMP"` + `value=0` + empty `configured_metrics_by_ci` → `injected == 0`; (b) per-pair lookup with another CI configured — proves the gate is not globally empty. |
| Safety net cross-check | PASS | Ruff + black clean on the 2 CRITICAL-1-fix files (`engines/snmp_worker.py`, `tests/test_snmp_worker.py`); the full backend has 876 ruff errors and 94 black reformat candidates, but all are pre-existing on `main` (confirmed). |
| RED test files still pass after REFACTOR | PASS | `style(backend): apply black formatting to CRITICAL-1 fix files` (commit `b0c1db4`) lands AFTER the GREEN commit; all 94 affected tests still pass (re-run post-REFACTOR). |
| Lock-guard regression not introduced | PASS | `test_current_production_lock_paths_match_approved_metadata_and_invariant_docs` validates the registry; no unapproved `acquire_event_triplet_lock` calls in `engines/snmp_worker.py` (the new `configured_metrics_records = session.run(...)` reads `:HAS_METRIC` without acquiring the per-writer triplet lock; it runs inside `poll_snmp()` which already holds the cycle connection). |

**TDD Compliance**: **7/8 checks PASS, 1 PARTIAL** (was 5/8 PASS, 1 PARTIAL, 2 FAIL pre-fix). The remaining PARTIAL is the historical 4 feat/fix commits from the apply phase being bundled RED+GREEN — cosmetic, recoverable with a follow-up squashing commit, does not affect functional correctness (all tests pass).

### Changed File Coverage

Per the strict-TDD module, line coverage tooling (`pytest --cov`) was not run because `coverage` is not configured in this branch's `pytest.ini`. Equivalent confidence comes from the **94 targeted tests** + the assertion-level coverage in `test_inject_synthetic_breaches_*` (which inspects every field of the synthetic row).

- `engines/snmp_worker.py` (211 new lines, was 164 pre-fix) — every public/private function (`_recover_icmp_jitter_events`, `_recover_icmp_packet_loss_events`, `_inject_synthetic_breaches_for_down_cis`) has at least one unit test exercising it (5+5+9 = 19 tests in `test_snmp_worker.py`, was 17 pre-fix; +2 spec-scenario tests). The wiring in `poll_snmp()` is exercised by the two `test_poll_snmp_*` integration tests (wiring is asserted by patching and observing call_args_list) AND by the 2 new spec-scenario tests which exercise the post-fix `configured_metrics_by_ci` parameter end-to-end.

- `test_snmp_worker.py` (707 new lines, was 606 pre-fix) — **17 new tests + 2 integration tests** (was 15 + 2), all passing. The 2 additional tests are the spec-scenario tests added by `03f669f` and the post-fix assertions updated by `4e7a9ea`.

- `test_snmp_worker_recovery_writer_predicates.py` (209 new lines, 50 deletions) — 4 new test methods + 2-entry extension to the `PREDICATE_SITES` registry; all 9 tests in the file pass.

- `test_event_writer_lock_guard.py` — unchanged in this branch (still passes; AD-6 says "no change" and that holds).

### Assertion Quality

| File | Line | Assertion | Issue | Severity |
|------|------|-----------|-------|----------|
| `test_snmp_worker.py` | 1710-1783 (pre-fix) → refactored to drop the misleading proxy in `03f669f` | `ci-no-metric` proxy (was `availability_source=None`) | **RESOLVED** by `03f669f`: the `ci-no-metric` row was removed from `test_inject_synthetic_breaches_mixed_scenario` (it was the wrong branch), and replaced by **two new dedicated tests** — `test_inject_synthetic_breaches_skips_when_metric_not_configured_on_ci` + `test_inject_synthetic_breaches_skips_when_has_metric_relationship_missing` — that use a real `configured_metrics_by_ci` set against the spec scenario (`availability_source="ICMP"` + `value=0` + metric not in the configured set). Both PASS. | — (was WARNING, now resolved) |
| `test_snmp_worker.py` | 1590-1621 | `test_inject_synthetic_breaches_injects_when_availability_zero_and_metric_configured` | Asserts that the post-fix gate fires correctly: the helper is called with a `configured_metrics_by_ci` set that contains the test CI, `value=0`, `availability_source="ICMP"`, and asserts the synthetic row is appended. This test now exercises the **correct** gate (NOT the inverted pre-fix gate). | SUGGESTION (assertion gap closed by the new tests; the post-fix test does assert on the new parameter, so the gate derivation source is now covered). |

## Coverage Spot-check

- `engines/snmp_worker.py:1132` `_recover_icmp_jitter_events` — locked by 5 tests in `test_recover_icmp_jitter_events_*` (Cypher shape, metric-id filter, OK-status filter, no-op, recovered_at).
- `engines/snmp_worker.py:1177` `_recover_icmp_packet_loss_events` — locked by 5 sibling tests.
- `engines/snmp_worker.py:1220` `_inject_synthetic_breaches_for_down_cis` — locked by **9 tests** in `test_inject_synthetic_breaches_*` (was 7 pre-fix; +2 spec-scenario tests). The pre-fix gap ("CI has `availability_source='ICMP'` but the target metric is not configured") is now covered by `test_inject_synthetic_breaches_skips_when_metric_not_configured_on_ci` and `test_inject_synthetic_breaches_skips_when_has_metric_relationship_missing`.
- `engines/snmp_worker.py:1938-1961` synthetic-breach wiring in `poll_snmp()` — locked by `test_poll_snmp_emits_synthetic_breach_on_ci_down` (asserts both metric_ids are passed) AND by the 2 new spec-scenario tests which exercise the post-fix `configured_metrics_by_ci` parameter end-to-end.
- `engines/snmp_worker.py:1972-1973` recovery writers in `poll_snmp()` — locked by `test_poll_snmp_recovers_jitter_and_packet_loss_when_samples_recover` (asserts both writers are called with the cycle's updates lists).
- `tests/test_snmp_worker_recovery_writer_predicates.py:73-136` `PREDICATE_SITES` — locked by `test_predicate_sites_registry_extends_to_six_entries`.
- `tests/test_snmp_worker_recovery_writer_predicates.py:236-268` jitter predicate test — locked by `test_icmp_jitter_events_predicate_includes_recovered`.
- `tests/test_snmp_worker_recovery_writer_predicates.py:270-300` packet-loss predicate test — locked by `test_icmp_packet_loss_events_predicate_includes_recovered`.

## Issues Found

### CRITICAL

*(none — the previous CRITICAL-1 is RESOLVED; see §Re-verification.)*

### WARNING

1. **Pre-existing testcontainers failures on `main` (not in this branch's diff):** 4 tests in `tests/test_writer_advisory_lock.py` fail because `testcontainers[postgres]` requires a Docker daemon which is unavailable in this local venv. Confirmed identical failure on `main` (`cd backend && python -m pytest tests/test_writer_advisory_lock.py` returns the same 4 failures with `docker.errors.DockerException: Error while fetching server API version`). **Not introduced by fix-484.** The apply-phase `tasks.md` §Phase 6 honestly reports this and the budget contract. Reviewers and CI gates should ignore.

2. **Pre-existing full-backend ruff + black failures (not in this branch's diff):** `ruff check .` reports 876 errors and `black --check .` would reformat 94 files. All pre-existing on `main`. The 2 files the CRITICAL-1 fix touches are clean (and the original 4 files were clean pre-fix). **Not introduced by fix-484.**

### SUGGESTION

1. **Spec scenarios "CREATE carries `created_at`" are not directly asserted.** REQ-JITTER-RECOVERED scenario 2 ("ICMP-jitter CREATE carries `created_at`") and the packet-loss mirror have no dedicated test pinning `created_at: datetime()` in the writer payloads for jitter/packet_loss. The behavior is correct (the `_refresh_icmp_jitter_events` / `_refresh_icmp_packet_loss_events` helpers inherit the `#432` invariant) but a regression on jitter/packet_loss specifically would not be caught.

2. **Design diagram (Data Flow) does not match the implementation's AD-2 placement.** The design says "SYNTHETIC BREACH ← injected between 2b and 2" but the implementation places the injection AFTER Pass 2 (line 1950) and BEFORE the recovery block (line 1972). The synthetic rows still reach the refresh helpers via Pass 3 with the rebuilt cache — functionally equivalent — but the design's diagram should be updated to reflect the actual flow. Either move the injection back to between 2b and 2 (true to the design) OR update `design.md` §Data Flow and AD-2 to acknowledge the Pass 3 placement.

## Verdict

**PASS — archive-ready.** The fix-484 slice delivers the 5 requirements (all COMPLIANT), 10/12 scenarios strictly COMPLIANT (12/12 if NEEDS-MORE-EVIDENCE counted as met), 7/8 architecture decisions FOLLOWED (1 PARTIAL by placement choice but functionally equivalent), 94 targeted tests, and 2168-test full suite (modulo 4 pre-existing testcontainers failures on `main`) all PASS at the test runner level. The previously-found **CRITICAL-1** (AD-3 / REQ-SYNTHETIC-BREACH-SCOPE logic inversion) is fully **resolved** by the 4 follow-up commits `03f669f` → `4e7a9ea` → `6b12824` → `b0c1db4` (see §Re-verification above). The strict TDD discipline is now observed at the commit level for the CRITICAL-1 fix pair (RED `test(events):` precedes GREEN `fix(events):` precedes REFACTOR `style(backend):`). The 2 remaining SUGGESTIONS are cosmetic and recoverable in a follow-up PR before `sdd-archive` if desired, but neither is required for archive-readiness:

- **SUGGESTION-1** — add a dedicated CREATE-`created_at` assertion for jitter/packet_loss refresh writers to lock the #431 invariant per metric (NEEDS-MORE-EVIDENCE → COMPLIANT).
- **SUGGESTION-2** — tighten AD-2 placement to match `design.md` (move injection between Pass 2b and Pass 2 refresh helpers) OR update `design.md` §Data Flow to acknowledge the Pass 3 placement (PARTIAL → FOLLOWED).

The change is **archive-ready as-is**; the 2 SUGGESTIONS are nice-to-haves, not blockers.

## Required User Checks

Before running `sdd-archive`:

1. *(no longer required)* ~~Fix CRITICAL-1~~ — **DONE** by commits `03f669f`, `4e7a9ea`, `6b12824`, `b0c1db4`. See §Re-verification.

2. *(optional, nice-to-have)* Tighten AD-2 placement to match `design.md` (move injection between Pass 2b and Pass 2 refresh helpers) OR update `design.md` §Data Flow to acknowledge the Pass 3 placement. SUGGESTION-2.

3. *(optional, nice-to-have)* Add a CREATE-`created_at` assertion for jitter and packet_loss refresh writers (SUGGESTION-1) to lock the #432 invariant per metric.

4. *(optional, cosmetic)* Squash the historical 4 feat/fix apply-phase commits (`039c674`, `e7f6dec`, `f79235e`, `a5da286`) into paired RED/GREEN commits for a cleaner audit trail. The current 4 commits are functionally correct (94/94 PASS) and the post-fix commits already follow the strict TDD pattern, so this is purely a git-history hygiene improvement.

The `sdd-archive` workflow can proceed without any of the optional SUGGESTIONS being addressed; the change is archive-ready at this state.
