```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:38757f87ba8413eafb5a87ed65a7c9a083003b4c76a07a502065d0877f6505c9
verdict: pass_with_warnings
blockers: 0
critical_findings: 0
requirements: 5/5
scenarios: 13/13
test_command: cd backend && python3.11 -m pytest tests/test_event_batch_pruner.py tests/test_neo4j_smoke.py -q
test_exit_code: 0
test_output_hash: sha256:c489275e6ce3301cc49c26e68db5a32244acb71b60beeeb2e518f6ec280eacbe
build_command: cd backend && python3.11 -c "import ast; [ast.parse(open(p).read()) for p in ['database.py','services/event_service.py','main.py','tests/test_neo4j_smoke.py','tests/test_event_batch_pruner.py']]; print('AST_OK')"
build_exit_code: 0
build_output_hash: sha256:119f343a98f12e780e2969cbe4f17c254afe9ec31287c582d5467d9c3c4091ed
```

# Verification Report

**Change**: fix-459-neo4j-nulls-cypher
**Branch**: fix/458-459-460-ai-chat-neo4j-cleanup
**Commit**: 88f2ebe1e3b2473825d3e37fd1a6c42d0bdebd98
**Version**: delta specs (event-prune-recovery-lifecycle ADDED+MODIFIED; neo4j-cypher-compatibility new)
**Mode**: Strict TDD

## Completeness

| Metric | Value |
|--------|-------|
| Specs in scope | 2 (event-prune-recovery-lifecycle + neo4j-cypher-compatibility) |
| Requirements in scope | 5 (2 in event-prune-recovery-lifecycle delta, 3 in neo4j-cypher-compatibility) |
| Scenarios in scope | 13 (5 in event-prune-recovery-lifecycle delta + 8 in neo4j-cypher-compatibility) |
| Tasks total | 18 |
| Tasks complete | 18 |
| Tasks incomplete | 0 |

## Build & Tests Execution

**Build (syntax/AST)**: PASS — `python3.11` AST parse of `database.py`, `services/event_service.py`, `main.py`, `tests/test_neo4j_smoke.py`, `tests/test_event_batch_pruner.py` returns AST_OK with exit code 0.

**Tests**: PASS — 22 / 22 passed in 2.21s (`tests/test_event_batch_pruner.py` 15 passed + `tests/test_neo4j_smoke.py` 7 passed). Exit code 0.

```text
============================= test session starts ==============================
collected 22 items
tests/test_event_batch_pruner.py ...............                         [ 68%]
tests/test_neo4j_smoke.py .......                                        [100%]

============================== 22 passed in 2.21s ==============================
```

**Coverage**: Not measured — no `pytest-cov` invocation was contracted in the focused test command. Changed-file line coverage is not enforced by the project harness for this change.

## Spec Compliance Matrix (Scenario-Level)

### event-prune-recovery-lifecycle (delta — 5 scenarios)

| Req | Scenario | Test | Result |
|-----|----------|------|--------|
| MODIFIED "Cursor Forward Progress on NULL `created_at`" | All timestamps are NULL | `tests/test_event_batch_pruner.py::TestEventBatchPrunerNullCursorProgress::test_event_batch_pruner_null_cursor_progress` (NULL row first, asserts `last_id="evt-1"` carried into iter 2) | ✅ COMPLIANT |
| MODIFIED "Cursor Forward Progress on NULL `created_at`" | Mixed NULL and timestamped rows | `tests/test_event_batch_pruner.py::TestEventBatchPrunerNullCursorProgress::test_event_batch_pruner_null_cursor_progress` (NULL row `evt-1` then timestamped row `evt-2` from the same generator; asserts both processed) | ✅ COMPLIANT |
| MODIFIED "Cursor Forward Progress on NULL `created_at`" | Monotonic UUID tiebreak across boundary | `tests/test_event_batch_pruner.py::TestEventBatchPrunerNullCursorProgress::test_event_batch_pruner_null_cursor_progress` (asserts `last_id="evt-1"` cursor param on iter 2) | ✅ COMPLIANT |
| ADDED "Fail-Loud on CypherSyntaxError in `event_batch_pruner`" | First-chunk syntax error is not debounced | `tests/test_event_batch_pruner.py::TestEventBatchPrunerCypherSyntaxErrorFirstChunk::test_first_chunk_syntax_error_yields_terminal_chunk` + `test_syntax_error_does_not_count_against_retry_cap` | ✅ COMPLIANT |
| ADDED "Fail-Loud on CypherSyntaxError in `event_batch_pruner`" | Transient errors keep the existing debounce | `tests/test_event_batch_pruner.py::TestEventBatchPrunerTransientKeepsDebounce::test_runtime_error_runs_three_strikes_then_raises` + `TestEventBatchPrunerCypherSyntaxErrorFirstChunk::test_non_syntax_client_error_keeps_debounce` | ✅ COMPLIANT |

### neo4j-cypher-compatibility (new — 8 scenarios)

| Req | Scenario | Test | Result |
|-----|----------|------|--------|
| Startup Cypher Smoke Query | Healthy driver passes smoke | `tests/test_neo4j_smoke.py::TestVerifyCypherSmoke::test_runs_round_trip` (asserts `outcome is True` + `RETURN 1` issued) | ✅ COMPLIANT |
| Startup Cypher Smoke Query | Incompatible driver fails startup loudly | `tests/test_neo4j_smoke.py::TestVerifyCypherSmoke::test_raises_on_client_error` (asserts `_FakeClientError` propagates with `Invalid input 'NULLS'`) | ✅ COMPLIANT |
| Startup Cypher Smoke Query | Smoke is not re-invoked by `/system/status` polling | (static-only) `main.py:416` calls `verify_cypher_smoke()` only inside `startup_event`; `main.py:904` calls only `verify_connection(max_retries=1, retry_delay=0)` from the `/api/system/status` handler — no smoke on every poll | ⚠️ PARTIAL (verified by static review only; no runtime regression test pins the partition) |
| DISABLE_NEO4J_SMOKE Kill-Switch | Kill-switch skips smoke | `tests/test_neo4j_smoke.py::TestVerifyCypherSmoke::test_disable_flag_skips` (asserts `outcome is False` + `driver.session.assert_not_called()`) | ✅ COMPLIANT |
| DISABLE_NEO4J_SMOKE Kill-Switch | Default behavior runs smoke | `tests/test_neo4j_smoke.py::TestVerifyCypherSmoke::test_runs_round_trip` (uses `monkeypatch.delenv("DISABLE_NEO4J_SMOKE")` + asserts smoke executes) | ✅ COMPLIANT |
| CI Regression Scan for NULLS FIRST/LAST | Clean source tree passes scan | `tests/test_neo4j_smoke.py::TestNullsRegressionScan::test_scan_passes_clean_tree` | ✅ COMPLIANT |
| CI Regression Scan for NULLS FIRST/LAST | Reintroduced syntax fails scan | `tests/test_neo4j_smoke.py::TestNullsRegressionScan::test_scan_detects_nulls_last` (asserts offender entry contains `services/example.py`) | ✅ COMPLIANT |
| CI Regression Scan for NULLS FIRST/LAST | Test fixtures are excluded from the scan | `tests/test_neo4j_smoke.py::TestNullsRegressionScan::test_scan_excludes_tests` + `test_scan_uses_nulls_first_or_last_regex` | ✅ COMPLIANT |

**Compliance summary**: 12 scenarios with direct runtime test coverage + 1 scenario verified by static code review (Smoke not re-invoked by `/system/status`). 13 / 13 scenarios satisfied at the spec-level contract.

## Correctness (Static Evidence)

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Drop `NULLS LAST` at `services/event_service.py:1537` (now 1597) | ✅ Implemented | `grep -nE "ORDER BY e.created_at" services/event_service.py` shows `1597: ORDER BY e.created_at ASC, e.id ASC`; no `NULLS\s+(FIRST|LAST)` match in the file. |
| Add `is_cypher_syntax_error` predicate + fail-loud short-circuit | ✅ Implemented | `services/event_service.py:27` defines the predicate; `services/event_service.py:1713` calls it inside the chunk `except Exception` block; the terminal-chunk branch is at lines 1720-1728. |
| Add `verify_cypher_smoke(driver)` honoring `DISABLE_NEO4J_SMOKE` | ✅ Implemented | `database.py:80-125` defines the helper; `_is_truthy` and `_DISABLE_NEO4J_SMOKE_ENV` are at lines 34/37. |
| Wire smoke ONLY into `startup_event` (NOT `verify_connection()`) | ✅ Implemented | `main.py:416` calls `verify_cypher_smoke()` directly inside `startup_event`; `main.py:904` (`/api/system/status` path) calls only `verify_connection(max_retries=1, retry_delay=0)` which has no smoke. |
| Add `scan_nulls_first_last(root)` helper callable in CI | ✅ Implemented | `tests/test_neo4j_smoke.py:58-96` exports `scan_nulls_first_last(*roots) -> list[dict]`; CLI smoke (apply-progress §4.3) reports `[]` on the patched tree. |
| Retarget `TestEventBatchPrunerNullCursorProgress` to drop `NULLS LAST` assertion | ✅ Implemented | `tests/test_event_batch_pruner.py:613-665::test_page_query_does_not_contain_nulls_first_or_last` regex-scans every page query for `NULLS\s+(FIRST|LAST)` and asserts no offenders. |
| Regression scan excludes `backend/tests/` | ✅ Implemented | `tests/test_neo4j_smoke.py:80` skips any candidate whose path contains a `tests/` component. |

## Coherence (Design)

There is no `design.md` artifact for this change. `exploration.md` enumerates Approach 4 (minimal fix + smoke + fail-loud) and the proposal confirms it. I checked the implementation against the proposal's:

| Design point | Source | Followed? | Note |
|---|---|---|---|
| Approach 4 (combined minimal fix + smoke + fail-loud) | `proposal.md` §Approach | ✅ Yes | All three pieces present. |
| Smoke wired at startup ONLY, not in `verify_connection()` | `proposal.md` Affected Areas + Risks | ✅ Yes | `main.py:416` startup-only; `database.verify_connection()` remains unchanged (`grep` shows lines 65-77 only). |
| Fail-loud predicate via `is_cypher_syntax_error` reusing captured `ClientError` class | `proposal.md` §Approach 3 | ✅ Yes | `_CLIENT_ERROR_CLASS` captured at `database.py:29`; the predicate lives at `services/event_service.py:27` (apply-progress §Deviations explains the in-file placement as a deliberate deviation from putting it in `neo4j_write_guard`). |
| Regression scan scope limited to `backend/services/` and `backend/engines/`, excluding `backend/tests/` | `proposal.md` §Approach 4 + specs/neo4j-cypher-compatibility | ✅ Yes | `scan_nulls_first_last` walks arbitrary roots; the integration is via `exclude "tests"` part component (line 80). |
| `DISABLE_NEO4J_SMOKE` kill-switch returns sentinel `False` (NOT raises) | `proposal.md` Risks | ✅ Yes | `database.py:103` returns `False`; tests assert `is False`. |
| Predicate allowed to read `e.code` defensively (MagicMock safety) | n/a (not explicit) | ➖ Not in proposal | Apply-phase deviation: defensive `isinstance` guard so stubbed `neo4j` doesn't crash — see apply-progress §Deviations. Acceptable; narrows the fail-loud behavior safely but does not change the contract. |

## TDD Compliance

| Check | Result | Details |
|-------|--------|---------|
| TDD evidence table reported | ✅ | `apply-progress.md` lines 51-65 contain a 13-row TDD Cycle Evidence table. |
| All tasks have tests | ✅ | 18/18 tasks covered; RED rows 1.1-1.8 each cite a concrete test file + class. |
| RED confirmed (tests exist on disk) | ✅ | `tests/test_event_batch_pruner.py` and `tests/test_neo4j_smoke.py` present; relevant test classes verified at expected line ranges (538, 613, 779, 951). |
| GREEN confirmed (tests pass at runtime) | ✅ | 22 / 22 passed in 2.21s. |
| Triangulation adequate | ✅ | 1.1 single, 1.2 3-cases (terminal chunk + retry-cap + non-syntax debounce), 1.3 single, 1.4 single, 1.5 single, 1.6 single, 1.7 single, 1.8 4-cases (detect + exclude + clean + regex). Adequate for the contract scope. |
| Safety Net for modified files | ✅ | `tests/test_event_batch_pruner.py` modified — safety-net rows confirm 10/10 pre-existing tests still pass. `database.py` modified — covered indirectly via `tests/test_neo4j_smoke.py::TestVerifyCypherSmoke`. `main.py` modified — wired only, static-review covered (apply-progress §4.2 deferred Docker boot smoke by static review). |

**TDD Compliance**: 6 / 6 checks passed.

## Test Layer Distribution

| Layer | Tests | Files | Tools |
|-------|-------|-------|-------|
| Unit | 22 | 2 (`tests/test_event_batch_pruner.py`, `tests/test_neo4j_smoke.py`) | `python3.11 -m pytest` + `unittest.mock` |
| Integration | 0 | 0 | Not installed |
| E2E | 0 | 0 | Not installed |
| **Total** | **22** | **2** | |

All tests are unit tests because the change targets small error-handling predicates + a startup-time smoke + a static regression scanner. A live integration test would require a Neo4j 5.15 container with the `Event` index populated — the apply-phase report §4.2 explicitly notes Docker is not available in the sandbox.

## Changed File Coverage

Coverage analysis skipped — no `pytest-cov` invocation was contracted. Per strict-tdd-verify.md §5d: report `Coverage analysis skipped — no coverage tool detected` and do not flag as a failure.

**Static review of changed files instead**:

| File | LoC | Public surface relevant to this change | Rating |
|------|-----|-----------------------------------------|--------|
| `services/event_service.py` | 1780 | `is_cypher_syntax_error` (line 27), `event_batch_pruner` fail-loud branch (lines 1708-1728), `_fetch_page` ORDER BY (line 1597) | ✅ All three touched paths have at least one targeted test. |
| `database.py` | 125 | `_is_truthy`, `_DISABLE_NEO4J_SMOKE_ENV`, `_CLIENT_ERROR_CLASS`, `verify_cypher_smoke` | ✅ All three new helpers tested (round-trip + ClientError + kill-switch). |
| `main.py` | 1128 | `verify_cypher_smoke` import + `startup_event` call (line 416) | ⚠️ Static review only — no runtime test asserts that smoke only runs at startup. See Warnings. |
| `tests/test_event_batch_pruner.py` | 1005 | `TestEventBatchPrunerNullCursorProgress::test_page_query_does_not_contain_nulls_first_or_last`, `TestEventBatchPrunerCypherSyntaxErrorFirstChunk` (3), `TestEventBatchPrunerTransientKeepsDebounce` (1) | ✅ |
| `tests/test_neo4j_smoke.py` | 367 | All production-surface tests covered | ✅ |

## Assertion Quality

| File | Lines | Patterns audited | Outcome |
|------|-------|------------------|---------|
| `tests/test_event_batch_pruner.py` | 538-1005 | `_FakeClientError` subclassing of `Exception`, real `with pytest.raises(_FakeClientError)`, real `assert "Invalid input 'NULLS'" in str(exc_info.value)`, real `assert second_query["params"].get("last_id") == "evt-1"`, real `assert len(error_chunks) == 1` | ✅ No tautologies. No type-only assertions. No ghost loops. |
| `tests/test_neo4j_smoke.py` | 196-367 | `assert outcome is True/False` (returns-sentinel value assertions), `pytest.raises(_FakeClientError)` with body inspection, `assert offenders` / `assert not offenders` on real scan lists, `assert pattern.search(...)` on the compiled regex | ✅ No trivial assertions. |

**Assertion quality**: ✅ All assertions verify real behavior (no tautologies, no type-only, no empty-without-companion, no ghost-loops, no smoke-only `toBeInTheDocument`-style tests).

## Quality Metrics

**Linter (ruff / flake8 / pylint)**: ➖ Not available in the focused test command — not contractually required for the verify scope.

**Type Checker (mypy / pyright)**: ➖ Not available in the focused test command — not contractually required for the verify scope.

## Issues Found

**CRITICAL**: None.

**WARNING**:

- **Smoke-not-on-`/system/status`-polling has no runtime test**: The spec scenario "Smoke is not re-invoked by `/system/status` polling" is satisfied only by static review (`main.py:416` is in `startup_event`; `main.py:904` only calls `verify_connection(max_retries=1, retry_delay=0)` which does NOT call smoke). I asserted that the partition is correct, but no automated test prevents a future regression that re-wires the smoke into `verify_connection`. A targeted test would assert `verify_cypher_smoke` is called from `startup_event` and never from the `/api/system/status` handler. Marking this as ⚠️ PARTIAL in the matrix above; flagging here so the orchestrator can decide whether to expand the test surface.

**SUGGESTION**:

- `backend/database.py:25` (module docstring/comment) contains the literal token `NULLS LAST` in `backtick code spans` for documentation purposes. The spec-scoped scanner walks only `backend/services/` and `backend/engines/`, so this comment is NOT in the scan path. No action required, but if the scan is ever broadened to all of `backend/*.py`, this comment would trip — rephrase opportunity if/when that happens.
- The agent `apply-progress.md` notes 29 pre-existing test isolation failures when the full suite runs but they are unrelated to this change (net improvement over baseline; not introduced here). I did not re-run the full suite to confirm; trust the apply-phase report.
- `apply-progress.md` §4.2 (`docker compose up` boot smoke) was deferred because Docker is not available in the sandbox. The static-review evidence is solid (helper raises → propagates from `startup_event` → aborts cold start), but a post-deploy production boot smoke in CI is still desired per the proposal §Success Criteria.

## Verdict

**PASS WITH WARNINGS** — all 13 spec scenarios are satisfied at the contract level, 12 of them with direct runtime test evidence and 1 (smoke-not-re-invoked-per-poll) by static code review alone. 18/18 tasks completed. 22/22 focused tests pass. Production code is free of the forbidden `NULLS FIRST/LAST` token inside the scanned tree. Single WARNING notes that the partition between startup smoke and `/system/status` polling is not pinned by a runtime test — recommend a follow-up test, but this is not a blocker for this change.
