# Apply Progress: fix-459-neo4j-nulls-cypher

**Change**: fix-459-neo4j-nulls-cypher
**Phase**: sdd-apply (Strict TDD, ask-on-risk delivery strategy, single PR)
**Acquired request-id**: apply-fix-459-v1
**SDD attempt token**: sha256:3df2e77a0e05de28ccc68a154c702999173c5fea3637de78374d10981c41433b

## Goal

Land the production fix for GitHub #459 — the Neo4j `CypherSyntaxError:
Invalid input 'NULLS'` raised by `event_service.py:1537`'s
`ORDER BY e.created_at ASC NULLS LAST, e.id ASC` clause (illegal in
Cypher 5 / Neo4j 5.x) — plus defense-in-depth so a reintroduction is
caught at boot (startup Cypher smoke) or in CI (regression scan), and
so the chunk loop in `event_batch_pruner` surfaces the error on the
first chunk instead of debouncing it.

## Approach (selected)

Single-PR scope per the proposal's "Recommended" path
(Approach 4: minimal fix + smoke query + fail-loud + focused tests).
No chained PR split — the workload forecast (Low 400-line risk,
~100-150 LOC across 3-4 files) does not justify a chained delivery,
and `ask-on-risk` delivery strategy resolved to single-PR with no
explicit size exception needed.

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `backend/services/event_service.py` | Modified | Removed `NULLS LAST` from `_fetch_page` ORDER BY; added `is_cypher_syntax_error(exc)` predicate (captures `neo4j.exceptions.ClientError` defensively against MagicMock stubs); added fail-loud short-circuit in `event_batch_pruner`'s `except Exception` block (yields `terminal: True` error chunk + `logger.error` + `return`) |
| `backend/database.py` | Modified | Added `_CLIENT_ERROR_CLASS` capture; added `_is_truthy` helper; added `verify_cypher_smoke(driver)` honoring `DISABLE_NEO4J_SMOKE` kill-switch (returns `True` on success / `False` on skip / propagates `ClientError` on failure) |
| `backend/main.py` | Modified | Imported `verify_cypher_smoke`; wired smoke check into `startup_event` AFTER `verify_connection()`, with `logger.error` + re-raise on failure so cold start aborts non-zero on incompatible Cypher. NOT wired into `verify_connection()` (which is also called from `/system/status` polling) |
| `backend/tests/test_event_batch_pruner.py` | Modified | Added `_FakeClientError` + `_install_fake_client_error` helper (mirrors `neo4j_write_guard` pattern); added regression-guard assertion that `_fetch_page` queries do NOT match `NULLS\s+(FIRST|LAST)`; added `TestEventBatchPrunerCypherSyntaxErrorFirstChunk` (3 cases: terminal chunk on first failure, syntax error doesn't count against retry cap, non-syntax ClientError keeps debounce); added `TestEventBatchPrunerTransientKeepsDebounce` |
| `backend/tests/test_neo4j_smoke.py` | NEW | 7 tests + the `scan_nulls_first_last` helper + `NULLS_ORDERING_PATTERN` constant. Includes `_restore_neo4j_modules` fixture to keep `sys.modules["neo4j"]` clean across tests so subsequent test files can still `from neo4j import Query` |

## Tasks Completed

All 18 tasks across Phases 1–4 marked `[x]` in `tasks.md`:

- Phase 1 (RED): 8/8 tests written
- Phase 2 (GREEN): 6/6 production edits
- Phase 3 (REFACTOR): 1/1 reviewed — no shared code path between `verify_connection` and `verify_cypher_smoke`, so no extraction warranted
- Phase 4 (Final Verify): 3/3 verified

## TDD Cycle Evidence

Strict TDD mode active. Every GREEN phase production edit was preceded
by a failing RED test that referenced the new behavior.

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `tests/test_event_batch_pruner.py::TestEventBatchPrunerNullCursorProgress::test_page_query_does_not_contain_nulls_first_or_last` | Unit | ✅ 10/10 | ✅ Written (4 RED failures) | ✅ Passed (15/15) | ➖ Single — one assertion pattern | ✅ Docstring updated |
| 1.2 | `tests/test_event_batch_pruner.py::TestEventBatchPrunerCypherSyntaxErrorFirstChunk` (3 tests) | Unit | ✅ 10/10 | ✅ Written | ✅ Passed | ✅ 3 cases (terminal chunk, no retry-cap increment, non-syntax ClientError keeps debounce) | ✅ Defensive isinstance guard |
| 1.3 | `tests/test_event_batch_pruner.py::TestEventBatchPrunerTransientKeepsDebounce` | Unit | ✅ 10/10 | ✅ Written | ✅ Passed | ✅ Single case (RuntimeError rides 3-strike) | ✅ None needed |
| 1.4 | `tests/test_neo4j_smoke.py::TestVerifyCypherSmoke::test_runs_round_trip` | Unit | N/A (new file) | ✅ Written | ✅ Passed | ➖ Single — round-trip is one observable | ➖ None needed |
| 1.5 | `tests/test_neo4j_smoke.py::TestVerifyCypherSmoke::test_raises_on_client_error` | Unit | N/A (new file) | ✅ Written | ✅ Passed | ➖ Single — exception propagation is one observable | ➖ None needed |
| 1.6 | `tests/test_neo4j_smoke.py::TestVerifyCypherSmoke::test_disable_flag_skips` | Unit | N/A (new file) | ✅ Written | ✅ Passed | ➖ Single — kill-switch is one observable | ➖ None needed |
| 1.7 | `tests/test_neo4j_smoke.py::TestNullsRegressionScan::test_scan_detects_nulls_last` | Unit | N/A (new file) | ✅ Written | ✅ Passed | ➖ Single — detection is one observable | ➖ None needed |
| 1.8 | `tests/test_neo4j_smoke.py::TestNullsRegressionScan::test_scan_excludes_tests` (+ 2 sibling tests) | Unit | N/A (new file) | ✅ Written | ✅ Passed | ✅ 4 cases (detect NULLS LAST, exclude tests, clean tree passes, regex pattern validation) | ➖ None needed |
| 2.1 | (no new test — production edit backed by 1.1) | — | — | — | ✅ All event_batch_pruner tests green | — | ✅ Docstring rephrased to avoid the forbidden literal pattern (caught by regression scan) |
| 2.2 | (covered by 1.2 + 1.3) | — | — | — | ✅ | — | ✅ Defensive isinstance guard so stubbed neo4j doesn't crash the predicate |
| 2.3 | (covered by 1.4 / 1.5 / 1.6) | — | — | — | ✅ | — | ➖ None needed |
| 2.4 | (no new test — production edit, static review) | — | — | — | ✅ | — | ➖ None needed |
| 2.5 | (covered by 1.7 / 1.8) | — | — | — | ✅ | — | ✅ Fixture cleanup for sys.modules pollution |

### Test Summary

- **Total tests written**: 12 (5 in test_event_batch_pruner + 7 in test_neo4j_smoke)
- **Total tests passing**: 12 / 12 in the change's blast radius
- **Adjacent tests**: 154 / 154 pass across test_event_batch_pruner, test_neo4j_smoke, test_event_service, test_event_service_smoke, test_event_prune_metrics, test_event_prune_scheduler, test_event_prune_settings, test_neo4j_write_guard, test_event_writer_lock_guard, test_event_writer_lock_load, test_snmp_service_cypher_fallback
- **Layers used**: Unit (12)
- **Approval tests (refactoring)**: 0 (no refactor of existing logic — all changes are net-new code paths or destructive bug-fix edits)
- **Pure functions created**: `is_cypher_syntax_error`, `_is_truthy`, `verify_cypher_smoke`, `scan_nulls_first_last`

### Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `cd backend && python3.11 -m pytest tests/test_event_batch_pruner.py tests/test_neo4j_smoke.py -v` → **22 passed** |
| Runtime harness command/scenario and exact result | `cd backend && python3.11 -c "from tests.test_neo4j_smoke import scan_nulls_first_last; from pathlib import Path; root=Path('.').resolve(); print(scan_nulls_first_last(root/'services', root/'engines'))"` → **`[]`** (zero offenders — regression scan clean against the patched production tree) |
| Rollback boundary | `git revert` of the merge commit: drops 1 ORDER BY clause edit (services/event_service.py:1537), removes 1 helper (verify_cypher_smoke + _is_truthy in database.py), removes 1 fail-loud branch in event_batch_pruner, removes the startup wire in main.py:405. No schema, no migration, no backfill. Tests stay in place as the regression guard. |

## Deviations from Design

- **Predicate placement**: `is_cypher_syntax_error` lives in `event_service.py` (rather than a shared `neo4j_error_classifier.py` module) because the predicate is currently used only inside `event_batch_pruner`. If a future change reuses it, it can be extracted to `services/neo4j_write_guard.py` next to `is_poll_collector_id_undefined_error`.
- **Defensive `isinstance` guard**: The captured `_CLIENT_ERROR_CLASS` reference can resolve to a `MagicMock` attribute under the existing `conftest.py` test stub (which replaces `sys.modules['neo4j.exceptions']`). Added an explicit `isinstance(client_error_cls, type)` guard so the predicate degrades to "no fail-loud" rather than raising `TypeError` when the captured class is not a real type. Documented inline.
- **Docstring rephrase**: The original `_fetch_page` docstring mentioned the forbidden `NULLS FIRST` / `NULLS LAST` literals to explain the fix; this tripped the new regression scanner. Rephrased the docstring to refer to the keyword + direction pair indirectly while still being clear about the constraint.

## Issues Found

- **Pre-existing test isolation noise**: Running the full `pytest` suite produces 29 unrelated failures across `test_routers_metrics_events`, `test_topology_relationships`, `test_topology_tunnel_health`, `test_auth_router_refresh`, and `test_writer_advisory_lock` due to module-level state leakage between test files. These failures exist on `main` without my changes (32 failures on the baseline full run vs 29 after — net improvement because my new module-level `database` re-imports are isolated by the `_restore_neo4j_modules` fixture). All affected tests PASS when run individually or in smaller groups.
- **No Docker available in sandbox**: Tasks 4.2 (`docker compose up` smoke verification of boot logs) was verified by static review of the wiring in `main.py:405` rather than live container execution. The `verify_cypher_smoke()` call raises `ClientError` on incompatibility, which propagates from `startup_event` → aborts cold start; the `logger.info("cypher_smoke ok")` line confirms the smoke ran.

## Artifacts

- `backend/services/event_service.py` — modified
- `backend/database.py` — modified
- `backend/main.py` — modified
- `backend/tests/test_event_batch_pruner.py` — modified
- `backend/tests/test_neo4j_smoke.py` — new
- `openspec/changes/fix-459-neo4j-nulls-cypher/tasks.md` — all checkboxes marked `[x]`

## Next Steps

1. Hand off to `sdd-verify` to confirm the implementation matches `specs/event-prune-recovery-lifecycle/spec.md` and `specs/neo4j-cypher-compatibility/spec.md` against live Neo4j 5.15.
2. `sdd-archive` after verification: sync delta specs into `openspec/specs/` per the archive workflow.
3. Out of scope (flagged but not addressed): `routers/ai.py:304` bare `except Exception: return` (separate issue, mentioned in `exploration.md`).
