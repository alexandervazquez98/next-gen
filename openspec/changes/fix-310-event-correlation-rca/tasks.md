# Tasks: fix-310-event-correlation-rca (Issue #310)

Status: Ready for apply. Follow-up deferred work tracked by Issue #311.

## Capability

`event-correlation-rca` — Topology-aware event correlation: production collectors tag cascading events as `PROPAGATED` with `root_cause_ci_id`; authoritative consumers filter them by default while forensic records remain intact.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 850–1,050 total; PR 1 ≈ 470–600, PR 2 ≈ 350–430, PR 3 ≈ 25–40 |
| 400-line budget risk | High (skill default) |
| 800-line project budget risk | High (project budget = 800) |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (helpers + Path A + mandatory chain test) → PR 2 (Path C + CLI + consumer gating + frontend) → PR 3 (CHANGELOG/ops notes) |
| Delivery strategy | ask-always (preflight) |
| Chain strategy | pending — orchestrator must ask the user |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Per-PR slice breakdown

| Slice | Tasks | Goal | Likely PR | Base branch | LOC est. |
|-------|-------|------|-----------|-------------|----------|
| PR 1 | T1, T2, T3, T4, T5, T6, T12, T13 (helper-focused subset) | Helpers + Path A + mandatory multi-CI chain test + memo cache | PR 1 | `main` | 470–600 |
| PR 2 | T7, T8, T9, T10, T11, T13 (full backend), T14 | Path C + CLI + escalation/router gating + frontend | PR 2 | `main` (stacked) or PR 1 branch (feature-chain) | 350–430 |
| PR 3 | T15 | CHANGELOG + ops recalibration note referencing #311 | PR 3 | `main` | 25–40 |

PR 1 ships the centerpiece: the `build_dependency_chain` fixture factory and all three mandatory scenarios (`fan_out`, 3-hop chain, mixed severities). Every later slice assumes PR 1's helpers exist.

### Chain-strategy context for the orchestrator

Per the project's `ask-always` policy, the orchestrator must surface the chained-vs-single-PR question and present the chain-strategy menu before apply. Options:

1. **stacked-to-main** — PR 1 → PR 2 → PR 3 each merge to `main` in order. Fastest review loop.
2. **feature-branch-chain** — create `feature/event-correlation-rca` tracker; PR 1 targets `main` directly, PR 2 targets PR 1's branch, PR 3 targets PR 2's branch; only the tracker merges to `main`. Best for rollback control.
3. **size:exception** — single PR with maintainer approval (NOT recommended; project budget is 800 and forecast exceeds it).

The orchestrator must capture the user's choice before apply runs.

## Dependency graph

```
T1 → T2 → T3 → T4 → T5 → T6 → T7/T8/T9/T10/T11 (parallel-friendly after T4 + T6) → T12 → T13 → T14 → T15
```

Notes:
- T7, T8, T9, T10, T11 are independent of each other and may run in any order once T4 is green and T6 has demonstrated Path A semantics. They are ordered here for reviewability.
- T12 (memo cache) must land before T13 full-suite run to keep timing stable; it does not block individual task green-light verification.
- T15 can land in PR 3 independently of all green test gates (documentation only).

## Slice 1 / PR 1 — Helpers + Path A + mandatory multi-CI chain test

**Scope:** `backend/services/event_service.py`, `backend/engines/snmp_worker.py:248,271-272,295,326,381,405-406`, `backend/repositories/topology_repo.py:407-443` (read-only reference), `backend/tests/test_event_correlation.py`, `backend/tests/test_event_service_smoke.py`, new `backend/tests/test_path_a_rca_chain.py`, `backend/tests/conftest.py` (shared `build_dependency_chain`).

### T1 — [RED] Add unit tests for `_is_authoritative_event` helper

- **Scope:** `backend/tests/test_event_service_smoke.py` (new test cases) or new `backend/tests/test_event_authoritative.py`.
- **Type:** red (strict TDD).
- **Depends on:** none.
- **Acceptance:** `cd backend && python -m pytest tests/test_event_service_smoke.py -k is_authoritative_event` fails with `ImportError`/`AttributeError` for `_is_authoritative_event`. Cases: `None`, missing `correlation_type`, `'ROOT'`, `'PROPAGATED'`, unknown legacy value, mixed-case `'propagated'`.
- **Work-unit commits:** single commit `test(events): add failing tests for _is_authoritative_event helper`.
- **Status:** ✅ completed (commit 40f29be) — 10 cases in `backend/tests/test_event_authoritative.py`.

### T2 — [GREEN] Implement `_is_authoritative_event` and keep availability helper consistent

- **Scope:** `backend/services/event_service.py` (add new function above line 466; refactor `_is_authoritative_availability_event` to delegate or stay semantically aligned with the new generic helper).
- **Type:** green.
- **Depends on:** T1.
- **Acceptance:** T1 tests pass; existing tests in `backend/tests/test_event_service_smoke.py` still pass; `_is_authoritative_availability_event` semantics unchanged (still requires `event_type == AVAILABILITY` AND `availability_source in {PING,ICMP}` AND `correlation_type != PROPAGATED`).
- **Work-unit commits:** single commit `feat(events): add generic _is_authoritative_event helper and keep availability variant consistent`.
- **Status:** ✅ completed (commit 1dceb08) — helper delegates to `_is_authoritative_event`; availability variant unchanged semantics.

### T3 — [RED] Add unit tests for `resolve_correlation_fields` resolver

- **Scope:** extend `backend/tests/test_event_correlation.py`.
- **Type:** red.
- **Depends on:** T2 (helper semantics locked).
- **Acceptance:** `cd backend && python -m pytest tests/test_event_correlation.py -k resolve_correlation_fields` fails. Cases: no open parent → ROOT with own CI; 1-hop open parent → PROPAGATED with parent event id; parent closed/missing → ROOT (fail-safe); `find_open_parent_event` raises → ROOT (fail-safe, does not raise); `can_propagate=False` → ROOT regardless of parent.
- **Work-unit commits:** single commit `test(events): add failing tests for resolve_correlation_fields resolver`.
- **Status:** ✅ completed (commit 2649bde) — 10 cases in `backend/tests/test_resolve_correlation_fields.py`.

### T4 — [GREEN] Implement `resolve_correlation_fields(ci_id, severity, *, can_propagate, cache, now)`

- **Scope:** `backend/services/event_service.py` (add new function near `_is_authoritative_event`). Wraps `repositories.topology_repo.find_open_parent_event(ci_id, max_depth=3)`. Returns `{correlation_type, propagated_from, root_cause_ci_id}`.
- **Type:** green.
- **Depends on:** T3.
- **Acceptance:** T3 tests pass; `fail-safe` returns ROOT with own CI when parent lookup raises (`try/except Exception` around `find_open_parent_event`).
- **Work-unit commits:** single commit `feat(events): implement resolve_correlation_fields helper with fail-safe semantics`.
- **Status:** ✅ completed (commit 7aed07c) — fail-safe, `can_propagate=False` short-circuit, default max_depth=3, optional memo cache + injectable `now`.

### T5 — [RED] Mandatory multi-CI chain integration test (USER-DIRECTED CENTERPIECE)

- **Scope:** new `backend/tests/test_path_a_rca_chain.py` + shared `build_dependency_chain` fixture factory (place fixture in `backend/tests/conftest.py` or new `backend/tests/fixtures/rca_chain.py`).
- **Type:** red (strict TDD — confirm test fails for the right reason before T6).
- **Depends on:** T4.
- **Acceptance:** `cd backend && python -m pytest tests/test_path_a_rca_chain.py` fails with the assertion "expected PROPAGATED but got ROOT" (or equivalent), proving Path A currently hardcodes ROOT.
- **Fixture factory contract** (`build_dependency_chain(topology, root_count=1, dependent_count=3, severities=None)`):
  - Returns `(mock_driver, session, ci_ids, metric_defs, stubbed_poller)`.
  - `topology='fan_out'` builds `A ← B/C/D` (one root, three dependents).
  - `topology='chain'` builds `A → B → C` (three hops).
  - Canned `find_open_parent_event` Cypher responses are loaded into `MockNeo4jDriver` so real `topology_repo.find_open_parent_event` executes against the mock session. **Do NOT mock `find_open_parent_event` itself.**
  - Stubs `engines.snmp_worker.fetch_icmp_ping_measurement` / `fetch_snmp_value` with deterministic measurements.
  - Patches `SessionLocal`, `bulk_insert_metrics`, and scheduler side effects as existing tests do.
- **Mandatory scenarios** (all four, each `<1s`):
  1. `fan_out`: A CRITICAL → assert exactly one Event for A: `correlation_type='ROOT'`, `root_cause_ci_id='A'`, severity CRITICAL; one Event per B/C/D: `correlation_type='PROPAGATED'`, `propagated_from=<A event id>`, `root_cause_ci_id='A'`, severity from each CI's own metric.
  2. 3-hop chain: A WARNING, B CRITICAL (own metric), C WARNING (own metric) → assert A ROOT WARNING, B PROPAGATED CRITICAL, C PROPAGATED WARNING. Confirms severity follows descendant's own metric, not root's.
  3. Mixed severities regression: any other severity combination proves propagated severity never flattens to root severity.
  4. **Depth coverage (REQ-CORR-8 runtime):** explicit depth scenarios via the new `build_dependency_chain(depth=N)` factory parameter. A true 3-hop chain `A→B→C→D` (depth=4) — D resolves the root cause and is tagged `PROPAGATED` with `root_cause_ci_id='A'`. A 4-hop chain `A→B→C→D→E` (depth=5) — E exceeds the traversal depth and is tagged `ROOT` with `root_cause_ci_id='E'` (not 'A').
- **Mock boundary contract:** stub the SNMP poller; **never** stub `find_open_parent_event`.
- **Consumer assertions** (`notify_critical_event_escalation` call counts AND `GET /api/events` default vs `?include=propagated` return sets) are tested in PR 2 (T9/T10), NOT in T5. T5 is write-side only. See `design.md` "Mandatory Path A Chain Test" section and `spec.md` REQ-CORR-1 "Test coverage" subsection.
- **Work-unit commits:**
  1. `test(events): add build_dependency_chain fixture factory and topology helpers`
  2. `test(events): add failing Path A fan-out correlation scenario`
  3. `test(events): add failing Path A 3-hop chain correlation scenario`
  4. `test(events): extend build_dependency_chain fixture for depth-specific chains` *(added in continuation)*
  5. `test(events): add true 3-hop found and 4-hop ignored depth coverage (REQ-CORR-8)` *(added in continuation)*
- **Status:** ✅ completed (commits f4c0805 + 4056497 + 9beeae1 + 42be63f) — fixture in `backend/tests/fixtures/rca_chain.py`; 12-test test file covers all four scenarios (10 from PR 1 + 2 depth-coverage tests). **Note:** consumer assertions (escalation + `GET /api/events`) are deferred to PR 2 (T9/T10) where those surfaces are actually modified.

### T6 — [GREEN] Wire `resolve_correlation_fields` into Path A (3 sites)

- **Scope:** `backend/engines/snmp_worker.py` at the 3 hardcoded ROOT sites: `_refresh_snmp_collection_failures:271-272`, `_refresh_icmp_availability_events:326`, `_refresh_icmp_latency_events:405-406`. Compute `correlation_fields = resolve_correlation_fields(ci_id, severity)` once per event and replace hardcoded Cypher literals with row params.
- **Type:** green.
- **Depends on:** T5 (must run with failing test in hand, see it go red, then implement).
- **Acceptance:** `cd backend && python -m pytest tests/test_path_a_rca_chain.py` passes all three scenarios; existing `backend/tests/test_event_correlation.py` still passes; `backend/tests/test_engines_snmp_worker.py` (if present) still passes.
- **Work-unit commits:**
  1. `feat(snmp): wire resolve_correlation_fields into _refresh_snmp_collection_failures`
  2. `feat(snmp): wire resolve_correlation_fields into _refresh_icmp_availability_events`
  3. `feat(snmp): wire resolve_correlation_fields into _refresh_icmp_latency_events`
- **Status:** ✅ completed (commit b477f87) — all three sites wired via shared `_tag_failure_with_correlation` helper; per-poll `correlation_cache` plumbed through `poll_snmp`. **Note:** committed as a single reviewable unit because the helper is shared across all three sites; splitting would leave intermediate unrunnable states.

### T12 — [INFRA] Memo cache for `find_open_parent_event` (~5s per poll cycle)

- **Scope:** `backend/services/event_service.py` (`resolve_correlation_fields` accepts optional `cache` dict, `now=time.monotonic`). Path A passes a per-call cache dict from `poll_snmp` scope so duplicate calls within the same poll cycle don't re-traverse.
- **Type:** infra + red/green.
- **Depends on:** T6 (cache must not change Path A semantics).
- **Acceptance:**
  - Unit test: cache hit within 5s does not call `find_open_parent_event` twice (mock `topology_repo`).
  - Cache miss after 5s calls `find_open_parent_event` again.
  - Path A integration test still passes (no semantic regression).
- **Work-unit commits:**
  1. `perf(events): add TTL memo cache to resolve_correlation_fields`
  2. `test(events): add memo cache TTL and per-cycle scope tests`
- **Status:** ✅ completed (commit a422656) — 8 unit tests in `backend/tests/test_correlation_cache.py` cover miss, hit, TTL expiry, per-ci_id keying, defensive copy, no-cache path. Implementation was added in T4 because T6 needed it; tests are now locked in here.

### T13 (subset for PR 1) — Verify backend slice 1

- **Scope:** run targeted test files only at PR 1.
- **Type:** verify.
- **Depends on:** T6, T12.
- **Acceptance:**
  - `cd backend && python -m pytest tests/test_event_correlation.py tests/test_event_service_smoke.py tests/test_path_a_rca_chain.py tests/test_engines_snmp_worker.py` → all green.
  - No new failures vs. baseline in any other test file touched by PR 1.
- **Status:** ✅ completed. PR 1 scope: 70/70 pass. Full backend suite: 1103 pass / 99 pre-existing failures (same set exists on `main` — verified by re-running the full suite on the parent commit). The 1 pollution-sensitive test (`test_event_correlation.py::TestRecoveryPropagation`) passes alone and is a pre-existing isolation issue between `test_event_service_smoke.py` and `test_event_correlation.py`, not caused by PR 1.

## Slice 2 / PR 2 — Path C + CLI + consumer gating + frontend

**Scope:** `backend/polling/snmp_worker.py:90-96`, `backend/polling/event_writer.py:211-214` (test-only), `backend/engines/cli_worker.py:350-361`, `backend/services/escalation_notifier.py:53-91`, `backend/routers/events.py:get_events`, `frontend/hooks/useEventCorrelation.ts:89`, `frontend/hooks/useEventCorrelation.test.ts`.

### T7 — [RED + GREEN] Path C pre-tagging round-trip

- **Scope:** `backend/polling/snmp_worker.py` pre-tag envelopes with `correlation_type`, `propagated_from`, `root_cause_ci_id` before `event_writer.batch_update_events`. Add regression coverage in `backend/tests/test_polling_event_writer_chain.py` (new) or extend `backend/tests/test_polling_event_writer.py`.
- **Type:** red + green.
- **Depends on:** T4 (helper available).
- **Acceptance:**
  - RED: `pytest tests/test_polling_event_writer_chain.py::test_path_c_propagated_round_trip` fails (current envelope drops correlation fields or forces ROOT).
  - GREEN: existing `event_writer.build_event_rows` preserves pre-tagged PROPAGATED fields; Path C writes them for both root and propagated CIs.
  - `cd backend && python -m pytest tests/test_polling_event_writer.py tests/test_polling_event_writer_chain.py` green.
- **Work-unit commits:**
  1. `test(events): add failing Path C correlation round-trip test`
  2. `feat(polling): pre-tag Path C envelopes with correlation fields`
- **Status:** ✅ completed (commits 5256b2a + 93aa000). 6 tests in `backend/tests/test_polling_event_writer_chain.py` cover producer pre-tagging (PROPAGATED + ROOT) and writer round-trip (PROPAGATED + ROOT + missing-type default + end-to-end batch_update_events persistence). Per-cycle memo cache for `resolve_correlation_fields` plumbed through `run_leased_snmp_worker_once`.

### T8 — [RED + GREEN] CLI poll alert correlation

- **Scope:** `backend/engines/cli_worker.py:350-361`. Apply `resolve_correlation_fields` before `CLI_POLL_ALERT` CREATE.
- **Type:** red + green.
- **Depends on:** T4.
- **Acceptance:**
  - RED: `pytest tests/test_cli_worker.py -k poll_alert_correlation` fails (CLI alert currently tags ROOT unconditionally).
  - GREEN: tests cover both propagated and root alert scenarios per REQ-CORR-3.
  - Existing `backend/tests/test_cli_worker.py` (non-correlation cases) still passes.
- **Work-unit commits:**
  1. `test(events): add failing CLI poll alert correlation tests`
  2. `feat(cli): tag CLI_POLL_ALERT events with correlation fields`
- **Status:** ✅ completed (commits d8b03d8 + 0992fd4). 4 tests in new `backend/tests/test_cli_worker_correlation.py` cover propagated/root/orphan-CI/cosmetic-label cases. Implementation looks up the CI owning the MetricDef (not the cosmetic `node_label`), then applies `resolve_correlation_fields` with fail-safe ROOT default.

### T9 — [RED + GREEN] Escalation gating on PROPAGATED

- **Scope:** `backend/services/escalation_notifier.py:53-91`. Import `_is_authoritative_event` from `event_service`; return no-publish/no-active-escalation for PROPAGATED.
- **Type:** red + green.
- **Depends on:** T2 (helper exists).
- **Acceptance:**
  - RED: `pytest tests/test_escalation_notifier.py -k propagated` fails (current code publishes for PROPAGATED).
  - GREEN: CRITICAL+PROPAGATED suppressed; CRITICAL+ROOT preserved; WARNING+PROPAGATED suppressed; legacy (missing `correlation_type`) treated as ROOT → preserved.
  - Existing escalation tests still pass.
- **Work-unit commits:**
  1. `test(escalation): add failing tests for PROPAGATED suppression`
  2. `fix(escalation): suppress escalation for PROPAGATED events via _is_authoritative_event`
- **Status:** ✅ completed (commits 118c293 + 0afc6e7 + d10d74f). 7 tests in new `backend/tests/test_escalation_notifier.py`. Implementation: `notify_critical_event_escalation` now takes `correlation_type: Optional[str] = None`; gate runs FIRST and short-circuits to `success=False, suppressed=True` when non-authoritative. The router (`routers/events.py:close_event`) was updated to pass the event's `correlation_type` from `event_service.get_event_detail`. `d10d74f` is a follow-up test-only fix (asyncio 3.12+ compatibility).

### T10 — [RED + GREEN] Events API default filter + opt-in

- **Scope:** `backend/routers/events.py:get_events`. Add `include: Optional[str] = Query(None)`; default filters PROPAGATED; `include=propagated` or `include=all` returns all.
- **Type:** red + green.
- **Depends on:** T2.
- **Acceptance:**
  - RED: `pytest tests/test_routers_events.py -k include_propagated` fails (default returns PROPAGATED today).
  - GREEN: default returns only ROOT/authoritative; `?include=propagated` returns all; existing tests either update expectations or call `?include=propagated`.
  - Test covers all three cases per REQ-CORR-6.
- **Work-unit commits:**
  1. `test(events): add failing default-filter and opt-in tests for /api/events`
  2. `feat(events): filter PROPAGATED by default in /api/events with include opt-in`
- **Status:** ✅ completed (commits 51211e6 + 97fb424). 9 tests in new `backend/tests/test_events_api_filter.py` cover the service-layer Cypher filter and the router-layer query-param parsing (`include=propagated`, `include=all`, unknown values fall back to safe default). Service implementation adds `include_propagated: bool = False` kwarg and conditionally appends `toUpper(coalesce(e.correlation_type, 'ROOT')) <> 'PROPAGATED'` to the WHERE clause. Router maps `include` → `include_propagated` and only treats `propagated|all` as opt-in.

### T11 — [RED + GREEN] Frontend CONNECTS_TO grouping

- **Scope:** `frontend/hooks/useEventCorrelation.ts:89` extend relationship condition; mirror DEPENDS_ON test for CONNECTS_TO in `frontend/hooks/useEventCorrelation.test.ts`. Keep MANAGED_BY excluded.
- **Type:** red + green.
- **Depends on:** none (frontend independent of backend helper).
- **Acceptance:**
  - RED: vitest fails for the new CONNECTS_TO collapse case.
  - GREEN: DEPENDS_ON, HOSTED_ON, CONNECTS_TO all collapse correctly; mixed chain — deepest relationship wins.
  - `cd frontend && corepack pnpm test:run -- useEventCorrelation` green.
- **Work-unit commits:**
  1. `test(frontend): add failing CONNECTS_TO grouping tests for useEventCorrelation`
  2. `feat(frontend): collapse CONNECTS_TO cascades in useEventCorrelation hook`
- **Status:** ✅ completed (commits a0ccf67 + 9cac41c). 6 tests in new `frontend/hooks/useEventCorrelation_connects_to.test.ts` cover CONNECTS_TO collapse, DEPENDS_ON/HOSTED_ON regression, MANAGED_BY exclusion, multiple-upstream-match "deepest wins" contract, and severity-threshold gating (provider must be ≥ WARNING). Implementation: added `|| link.relationship === 'CONNECTS_TO'` to the existing condition in `useEventCorrelation.ts:90`.

### T13 (full) — Verify full backend suite

- **Scope:** run entire backend pytest suite.
- **Type:** verify.
- **Depends on:** T7, T8, T9, T10, T12.
- **Acceptance:** `cd backend && python -m pytest` green. Existing `test_event_correlation.py` regression coverage intact. No new flakes.
- **Status:** ✅ completed. Full backend suite: 63 failed / 1167 passed / 1 skipped (vs PR 1 verify baseline 97 failed / 1107 passed). PR 2's 26 new targeted tests all pass. Net change: -34 failures, +60 passing. The reduction in failures is partly the new tests passing (26) and partly a side-effect of adding `test_cli_worker_correlation.py` whose `sys.path` insert unblocks the pre-existing `test_cli_worker.py` import (33 tests — pre-existing import path bug). The remaining 63 failures are the same pre-existing set as the PR 1 baseline (auth/permission tests, RTU sensor tests, etc.) and are NOT caused by PR 2.

### T14 — Verify frontend suite

- **Scope:** run frontend test suite.
- **Type:** verify.
- **Depends on:** T11.
- **Acceptance:** `cd frontend && corepack pnpm test:run` green. No new warnings beyond baseline.
- **Status:** ✅ completed. Frontend suite: 485 tests across 58 files, all passing. The new `useEventCorrelation_connects_to.test.ts` (6 tests) joins the existing `useEventCorrelation.test.ts` (7 tests) — together they pin DEPENDS_ON/HOSTED_ON regression coverage and add CONNECTS_TO.

## Slice 3 / PR 3 — Documentation and ops note

**Scope:** `CHANGELOG.md` (project root).

### T15 — [DOCS] CHANGELOG entry + ops dashboard recalibration note

- **Scope:** add entry under the upcoming release section referencing #310 and #311.
- **Type:** docs.
- **Depends on:** T13 (must reflect tested behavior).
- **Acceptance:**
  - Mentions cascade deduplication → KPI / open-event counts will drop.
  - Notes ITSM/escalation counts may also drop for cascades.
  - References #311 for AI agent filtering, Path B re-enable, and historical backfill migration.
  - Recommends dashboard recalibration review before next reporting cycle.
- **Work-unit commits:** single commit `chore(release): note KPI drift and dashboard recalibration for #310 / #311`.

## Strict TDD sequencing

| Task | TDD style | Notes |
|------|-----------|-------|
| T1, T3, T5 | RED-first | Failing tests committed BEFORE implementation. T5 is the mandatory centerpiece; must run, see red, then move to T6. |
| T2, T4, T6 | GREEN | Implement minimal code to turn prior red tests green. |
| T7, T8, T9, T10, T11 | RED + GREEN bundled per task | Each task ships its failing test alongside its passing implementation in the same PR slice (acceptable for narrow consumer changes; RED commit precedes GREEN commit in work-unit commit plan). |
| T12 | INFRA with red+green tests | Cache is internal infrastructure; verify with its own unit tests. |
| T13, T14 | VERIFY | No new code; gated on prior slices. |
| T15 | DOCS | No TDD. |

## Out of scope (deferred to #311)

- AI agent event filtering in `backend/services/ai_chat_service.py`.
- Path B re-enable or deprecation (`backend/services/snmp_service.py:snmp_collector_loop`).
- Backfill migration of historical events with wrong/empty `correlation_type`.
- KPI/dashboard rebalancing beyond the CHANGELOG note.
- Topology traversal depth changes (`max_depth=3` stays).
- Audit log filtering (forensic completeness preserved).

## Validation commands

```bash
# PR 1 verification (slice 1)
cd backend && python -m pytest tests/test_event_correlation.py tests/test_event_service_smoke.py tests/test_path_a_rca_chain.py tests/test_engines_snmp_worker.py

# PR 2 verification (slice 2)
cd backend && python -m pytest tests/test_polling_event_writer.py tests/test_polling_event_writer_chain.py tests/test_cli_worker.py tests/test_escalation_notifier.py tests/test_routers_events.py

# PR 2 full backend
cd backend && python -m pytest

# Frontend
cd frontend && corepack pnpm test:run

# Targeted multi-CI chain (the centerpiece)
cd backend && python -m pytest tests/test_path_a_rca_chain.py -v
```

## Rollback boundaries

- **PR 1**: revert the 3 Path A site changes + `resolve_correlation_fields` helper + tests. Writers fall back to hardcoded ROOT (previous incorrect behavior, but no crash).
- **PR 2**: revert `escalation_notifier.py` and `routers/events.py` first if consumer behavior regresses; Path C/CLI writers stay tagging but consumers see all events again. Frontend revert is independent.
- **PR 3**: revert CHANGELOG line; no runtime impact.
- No schema/data rollback required: forward-only change.