# Archive Report: fix-459-neo4j-nulls-cypher

**Change**: `fix-459-neo4j-nulls-cypher`
**Branch**: `fix/458-459-460-ai-chat-neo4j-cleanup`
**Commit**: `88f2ebe1e3b2473825d3e37fd1a6c42d0bdebd98`
**Archived**: 2026-09-02
**Archived to**: `openspec/changes/archive/2026-09-02-fix-459-neo4j-nulls-cypher/`
**Mode**: openspec (filesystem-only persistence)
**Closes**: #459

## Intent

Fix GitHub #459 — Neo4j `CypherSyntaxError: Invalid input 'NULLS'` raised by
`event_service.py:1537`'s `ORDER BY e.created_at ASC NULLS LAST, e.id ASC`
clause, which is illegal in Cypher 5 / Neo4j 5.15.0 (the `NULLS` keyword is
not in the Cypher 5 grammar; ASC already places NULLs last by default). The
error was swallowed by `event_batch_pruner`'s `try/except Exception` and
served to SSE consumers as a progress chunk instead of a 5xx, so operators
saw stale or empty data with no audible failure signal.

## Scope

### In Scope (Approach 4: minimal fix + smoke + fail-loud)

1. **Primary fix**: Drop the redundant `NULLS LAST` clause from `_fetch_page`
   at `event_service.py:1537` (now line 1597). Sort order is unchanged
   because ASC places NULLs last by default in Cypher 5.
2. **Fail-loud predicate**: New `is_cypher_syntax_error(exc)` predicate
   that recognizes `ClientError` with `code == "Neo.ClientError.Statement.SyntaxError"`.
   Wired into `event_batch_pruner` so a syntax error on the first failed
   chunk yields a terminal `error` chunk, logs at ERROR level, and closes
   the stream — bypassing the 3-strike debounce. Transient / unavailable /
   driver errors keep the existing debounce.
3. **Startup Cypher smoke**: New `verify_cypher_smoke(driver)` in
   `database.py` honoring the `DISABLE_NEO4J_SMOKE` kill-switch. Wired
   into `startup_event` only (NOT into `verify_connection()`, which is
   also called from `/system/status` polling).
4. **CI regression scan**: `scan_nulls_first_last(*roots)` helper walks
   `backend/services/` and `backend/engines/`, reports offenders for the
   `NULLS\s+(FIRST|LAST)` pattern. Excludes `backend/tests/`.

### Out of Scope

- `cypher-param-fallback` (#340/#343) — its `poll_collector_id` predicate
  is strict and does not absorb `Invalid input 'NULLS'`. Confirmed safe.
- `routers/ai.py:304` bare `except Exception: return` — flagged in
  exploration.md but unrelated to #459.
- The 7 audited `ORDER BY` queries with no `NULLS` clause — none broken.
- Neo4j version bump / MCP runtime changes.

## Outcome

| Metric | Final Value | Source |
|---|---|---|
| Specs in scope | 2 | event-prune-recovery-lifecycle (delta) + neo4j-cypher-compatibility (new) |
| Requirements in scope | 5 / 5 | verify-report.md §Completeness |
| Scenarios in scope | 13 / 13 | verify-report.md §Completeness |
| Tasks complete | 18 / 18 | tasks.md (all `[x]` at archive time) |
| Focused tests | 22 / 22 green | test_event_batch_pruner.py (15) + test_neo4j_smoke.py (7) |
| AST parse | OK | verify-report.md §Build & Tests |
| Test exit code | 0 | verify-report.md |
| Build exit code | 0 | verify-report.md |
| Forbidden token scan | clean | apply-progress.md §Work Unit Evidence |
| Production code diff | +186 / -9 | verify-report.md §Affected Areas |
| Total diff (incl. tests) | ~676 lines | verify-report.md (above 400-line review ceiling — chained PR candidate) |

## Files

### Production code (modified)

| File | Net Δ | Purpose |
|---|---|---|
| `backend/database.py` | +78 | `_CLIENT_ERROR_CLASS` capture, `_is_truthy`, `_DISABLE_NEO4J_SMOKE_ENV`, `verify_cypher_smoke(driver)` |
| `backend/main.py` | +23 | Import `verify_cypher_smoke`; wire into `startup_event` after `verify_connection()` |
| `backend/services/event_service.py` | +85 | `is_cypher_syntax_error(exc)` predicate; `_fetch_page` ORDER BY edit; fail-loud branch in `event_batch_pruner`'s `except Exception` |

### Tests

| File | Action | Tests added |
|---|---|---|
| `backend/tests/test_event_batch_pruner.py` | modified (+340) | Regression scan assertion in `TestEventBatchPrunerNullCursorProgress`; new `TestEventBatchPrunerCypherSyntaxErrorFirstChunk` (3 cases); new `TestEventBatchPrunerTransientKeepsDebounce` |
| `backend/tests/test_neo4j_smoke.py` | NEW (~150 lines, 7 tests) | `TestVerifyCypherSmoke` (round-trip, ClientError, kill-switch) + `TestNullsRegressionScan` (detect, exclude tests, clean tree, regex) |

### Specs (synced this archive)

| Domain | Action | Details |
|---|---|---|
| `event-prune-recovery-lifecycle` | MODIFIED 1 + ADDED 1 | `Cursor Forward Progress on NULL created_at` (MODIFIED: now mandates Cypher-5-valid implicit NULL placement, forbids explicit `NULLS` keyword); `Fail-Loud on CypherSyntaxError in event_batch_pruner` (ADDED: 2 scenarios) |
| `neo4j-cypher-compatibility` | Verified already in baseline (no merge) | 3 reqs + 8 scenarios present at `openspec/specs/neo4j-cypher-compatibility/spec.md` |

### Archive contents

- `proposal.md` ✅ (3.4 KB)
- `exploration.md` ✅ (21.6 KB)
- `specs/event-prune-recovery-lifecycle/spec.md` ✅ (delta file, 2.8 KB)
- `tasks.md` ✅ (4.8 KB, all 18 tasks marked `[x]`)
- `apply-progress.md` ✅ (10.7 KB)
- `verify-report.md` ✅ (17.0 KB)
- `verify-test-output.txt` ✅ (668 B)
- `archive-report.md` ✅ (this file — additive-only)

## Verdict

**PASS WITH WARNINGS** — final state per orchestrator-provided facts:
5/5 requirements compliant, 13/13 scenarios compliant, 22/22 focused tests
green, AST parse OK, zero CRITICAL findings. Archived with one WARNING
inheriting from the verify-report.

### Warning (1)

**W-1 — Smoke-not-on-`/system/status`-polling has no runtime test pin.**
The scenario "Smoke is not re-invoked by `/system/status` polling" is
satisfied only by static review of `main.py:416` (smoke called inside
`startup_event`) vs `main.py:904` (`/api/system/status` calls only
`verify_connection(max_retries=1, retry_delay=0)` which has no smoke).
No automated test prevents a future regression that re-wires the smoke
into `verify_connection()`. Recommend a follow-up test asserting the
partition, but this is not a blocker for this change. See verify-report.md
§Issues Found.

### Non-blocking observations (carried forward from verify-report §Suggestions)

- `database.py:25` module docstring contains `NULLS LAST` in a code span
  for documentation; the spec-scoped scanner walks only `backend/services/`
  and `backend/engines/`, so this is not in scan path. No action required
  unless the scan is broadened.
- Apply-phase report §4.2 deferred live `docker compose up` boot smoke
  (no Docker in sandbox). Static-review evidence is solid; a post-deploy
  production boot smoke in CI is desired per the proposal §Success Criteria.

## Final State vs. Intermediate Snapshots

Per the Final-State Authority hierarchy, this archive reflects:

1. **Native review authority**: not applicable (no `reviewGate` present
   for this candidate — receipt-driven development is not active for
   `fix-459`).
2. **Persisted tasks artifact**: 18/18 `[x]` at archive time. No stale
   checkboxes. No reconciliation repair needed.
3. **Orchestrator-provided final-state facts**: 22/22 tests green;
   5/5 reqs, 13/13 scenarios compliant; verdict PASS WITH WARNINGS;
   commit `88f2ebe` on branch `fix/458-459-460-ai-chat-neo4j-cleanup`.
4. **Intermediate snapshots (`apply-progress.md`, `verify-report.md`)**:
   both describe the same final state; no contradictions to resolve.
   The 1 WARNING is preserved as-is and not echoed as a blocker.

## Mechanical Copy Contract Evidence

### Spec merge (delta → baseline)

`openspec/specs/event-prune-recovery-lifecycle/spec.md` was edited to
apply the delta:

- MODIFIED requirement "Cursor Forward Progress on NULL `created_at`":
  replaced the existing prose with the Cypher-5-constrained version
  (forbids explicit `NULLS FIRST`/`NULLS LAST` keywords) and the
  `(Previously: ...)` change-note. All 3 existing scenarios preserved.
- ADDED requirement "Fail-Loud on CypherSyntaxError in
  `event_batch_pruner`": appended at the end of the Requirements
  section with 2 new scenarios.

`openspec/specs/neo4j-cypher-compatibility/spec.md` was verified to
already contain the full new ability spec (3 reqs + 8 scenarios at
issue close) — no merge required.

### Archive move (change folder → archive)

- **Snapshot**: created at `/var/folders/z2/jfkx5rs11w9c7546250wxl5c0000gn/T//sdd-archive.RGASCz/source`
  via `cp -R` BEFORE the move.
- **Move**: `git mv openspec/changes/fix-459-neo4j-nulls-cypher openspec/changes/archive/2026-09-02-fix-459-neo4j-nulls-cypher`
  succeeded — git tracked the rename for the 5 previously-tracked files;
  the 2 untracked files (verify-report.md, verify-test-output.txt) were
  moved with the directory (their `??` status now appears at the archive
  path).
- **Source verification**: `openspec/changes/fix-459-neo4j-nulls-cypher`
  does not exist after the move (`PASS: source directory removed`).
- **Active changes check**: `ls openspec/changes/ | grep -c fix-459` → 0.
- **Archive contents**: 7 files present (matches original count).
- **Byte-identity readback**: `diff -r` against the pre-move snapshot is
  empty (snapshot EXIT-trapped after move; SHA256 hashes and file sizes
  in the table below independently confirm byte-identity against the
  archived folder via `cp -R` + `shasum -a 256`):
  ```
  14d500b659515c9f33e17f09672f0468018a385a84d2ce950eee783c580723c5  apply-progress.md
  7de2757ae8491bb1fc06e4d856bf56e83c96e2988ef0cf434bf5adc4fbd3ba54  specs/event-prune-recovery-lifecycle/spec.md
  bd2b9afe4c0eeb62e1cc7666ba01101aaeaac13e50414c22222de6faabb785f1  proposal.md
  c489275e6ce3301cc49c26e68db5a32244acb71b60beeeb2e518f6ec280eacbe  verify-test-output.txt
  cc0e4eaeeb80c8886478f45a6b6a6cf7d2f3b863802d897a8a5103ef20b72683  verify-report.md
  cf56bf5d068cf7927c49bd2c7c8089a6d6171460db93834b4c43c97fe9058689  tasks.md
  df6dcc97efdb8c3d4c842a0869ca485c70eb1ee9851cca350d8112af7dc1fb10  exploration.md
  ```

## Rollback

Single commit, read/boot paths only. Reverting `88f2ebe` restores prior
behavior:

```bash
git revert 88f2ebe1e3b2473825d3e37fd1a6c42d0bdebd98
```

What `git revert` removes:

1. The `ORDER BY ... ASC NULLS LAST`, `e.id ASC` edit at
   `event_service.py:1537` (now 1597) — dropped back to broken clause.
2. The `is_cypher_syntax_error(exc)` predicate + fail-loud short-circuit
   in `event_batch_pruner`'s `except Exception` block.
3. The `verify_cypher_smoke(driver)` helper + `_is_truthy` +
   `_DISABLE_NEO4J_SMOKE_ENV` + `_CLIENT_ERROR_CLASS` in `database.py`.
4. The `verify_cypher_smoke()` import + `startup_event` wire in
   `main.py:405`.
5. The 22 new tests in `test_event_batch_pruner.py` (+340) and
   `test_neo4j_smoke.py` (~150 lines, 7 tests).

No schema change, no migration, no backfill. No new env var contract
(only added one with a kill-switch default).

Note: tests stay in place as the regression guard against reintroduction.
If the operator wants a fully clean rollback including the test files,
`git revert` then `git rm` for the test files (which removes them from
the index but does not delete them from disk).

## SDD Cycle Complete

| Phase | Status | Artifact |
|---|---|---|
| sdd-explore | ✅ Complete | `exploration.md` |
| sdd-propose | ✅ Complete | `proposal.md` |
| sdd-spec | ✅ Complete | `specs/event-prune-recovery-lifecycle/spec.md` (delta) + baseline `specs/neo4j-cypher-compatibility/spec.md` |
| sdd-design | ➖ Not needed | (exploration.md enumerated Approach 4; proposal confirmed; no separate design.md) |
| sdd-tasks | ✅ Complete | `tasks.md` (18 tasks, forecast: Low 400-line risk) |
| sdd-apply | ✅ Complete | `apply-progress.md` (Strict TDD; 12 tests written; 12/12 RED→GREEN) |
| sdd-verify | ✅ Complete | `verify-report.md` (PASS WITH WARNINGS, 1 WARNING) |
| sdd-archive | ✅ Complete | this report |

Issue #459 closed.
