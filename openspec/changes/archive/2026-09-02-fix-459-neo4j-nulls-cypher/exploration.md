# Exploration: fix-459-neo4j-nulls-cypher

## Current State

A recurring `Neo4j CypherSyntaxError` with the message fragment `Invalid input 'NULLS': expected ...` is being logged from the running backend (Neo4j container `neo4j:5.15.0`, `docker-compose.yml`). The query that surfaces this is the page query inside `event_batch_pruner` at `backend/services/event_service.py:1537`:

```cypher
MATCH (e:Event)
WHERE e.status = 'RECOVERED'
  AND (e.ack IS NULL OR e.ack = false)
  {cursor_filter}
RETURN e.id as event_id, e.status, e.created_at as created_at
ORDER BY e.created_at ASC NULLS LAST, e.id ASC
LIMIT $limit
```

The `NULLS LAST` clause was added in commit `0d4fab1` (fix-423 PR #1, August 2026) to express "NULL `created_at` legacy rows should sort after timestamped rows" when paginating the recovered-event batch pruner. The author's intent was that the cursor should keep making forward progress across NULL-bearing rows.

### Cypher 5 vs NULLS FIRST/LAST

This is the root cause. I verified the Cypher specification explicitly:

- **Neo4j 5.x / Cypher 5 / Cypher 25 ORDER BY clause** does NOT expose `NULLS FIRST` or `NULLS LAST` as valid subclause syntax. The official manual (`https://neo4j.com/docs/cypher-manual/25/clauses/order-by/`, "Null values" section) states: *"When sorting, null values appear last in ascending order and first in descending order."* — i.e. **default behavior already places NULLs LAST in ASC and NULLs FIRST in DESC**.
- The full Cypher 25 reserved-keyword list (`https://neo4j.com/docs/cypher-manual/25/syntax/keywords/`) does NOT include `NULLS`. Only the singular literal `null` appears under section N. This confirms there is no parser entry point for the keyword.
- Therefore `ORDER BY e.created_at ASC NULLS LAST` is a Cypher syntax error in Neo4j 5.x: the parser sees `ASC` and then expects either `,`, `LIMIT`, `SKIP`, or end-of-clause, NOT `NULLS`. The exception surfaces as `Neo.ClientError.Statement.SyntaxError: Invalid input 'NULLS': expected ...`.

The `NULLS LAST` keyword was redundant to begin with — in an ASC sort, NULLs already sort LAST by default in Cypher 5. The whole clause can be dropped without changing the sort semantics.

### How the error is swallowed today

`event_batch_pruner` (`backend/services/event_service.py:1416-1667`) is an async generator that yields progress dicts. Each chunk wraps `_fetch_page` (line 1526-1542) in a `try/except Exception` (line 1595/1648):

```python
try:
    page = await asyncio.to_thread(_fetch_page, cursor_filter, cursor_params)
    ...
except Exception as e:
    consecutive_failures += 1
    if consecutive_failures > MAX_CONSECUTIVE_CHUNK_FAILURES:
        raise
    yield {
        "total": total, "processed": total_processed,
        "remaining": max(0, total - total_processed),
        "batch": batch, "error": str(e),
    }
```

`MAX_CONSECUTIVE_CHUNK_FAILURES = 3` (line 1413). The comment at line 1406-1412 explains why the cap exists: prior to it, an infinite loop swallowed every failure.

Net effect on the SSE endpoint `GET /api/events/bulk/stream-progress` (`backend/routers/events.py:350-416`):
- A CypherSyntaxError on the first page query produces an SSE `data: {"error": "..."}` frame.
- The client (and the curl/`useEventStream` consumer) sees a "progress" event with `total=N, processed=0, error="Invalid input 'NULLS'..."`, not a 5xx.
- The generator only re-raises after three consecutive chunk failures, but in practice the generator can also break out earlier if `len(event_ids) < batch_size` (line 1645) — so a single failing chunk followed by zero matching events ends the stream with no error to the operator.
- The `@app.exception_handler(Exception)` at `backend/main.py:383-392` never sees this because the exception is consumed inside the async generator before any `await` returns to FastAPI's handler chain.

This matches the issue's description exactly: "many requests continue serving stale or empty data instead of failing loudly."

### Adjacent error swallowing

- `backend/routers/ai.py:304-305` has `except Exception: return` which silently discards upstream errors. This is unrelated to #459 but is in the same `fix-458-459-460` branch; flagged for awareness.
- `backend/routers/auth.py:279,281,336` and `backend/routers/dictionaries.py:486` wrap Cypher-callable endpoints in `except Exception` without distinguishing Neo4j syntax errors. Most of these re-raise as `HTTPException(500, ...)`, which is acceptable, but the global handler at `main.py:383-392` already handles unhandled exceptions with a clean 500 JSON. The asymmetry is only inside `event_batch_pruner`.

### Startup coverage gap

`backend/database.py:37-49` `verify_connection()` calls `driver.verify_connectivity()` only. It does NOT issue a real Cypher query. `backend/main.py:404-405` invokes it once at startup, but only as a connectivity ping. There is no startup smoke query that catches a malformed Cypher at process boot.

### Test infrastructure

- `backend/tests/conftest.py:35-38` already stubs `sys.modules["neo4j"]` and `sys.modules["neo4j.exceptions"]` to `MagicMock`, so tests can import service modules without a live Neo4j. Production code captures the real `neo4j.exceptions.ClientError` class at module load via `neo4j_write_guard.py:51`.
- `backend/tests/test_event_batch_pruner.py:491-558` is the relevant regression class. It includes `TestEventBatchPrunerNullCursorProgress.test_event_batch_pruner_null_cursor_progress` which currently asserts the query string contains `NULLS LAST`. With the fix, that assertion must be updated to assert the query is still NULL-safe (the *cursor* logic) without requiring the invalid `NULLS LAST` syntax. The cursor uses `IS NULL`-safe WHERE tiebreak (lines 1583, 1592), which is independent of ORDER BY.

## Findings

### Cypher queries using explicit NULLS FIRST/LAST

- `backend/services/event_service.py:1537` — `ORDER BY e.created_at ASC NULLS LAST, e.id ASC` inside `_fetch_page`. **Confirmed broken** against Neo4j 5.15.0.
- `backend/tests/test_event_batch_pruner.py:497` — comment-only mention in test docstring.
- No other production Cypher queries in the repository use `NULLS FIRST/LAST` syntax. (`grep -rEn "NULLS\s+(FIRST|LAST)" backend/` returned only the two lines above.)

### Cypher queries with potential ordering issues (audit, not yet proven broken)

The following queries use `ORDER BY` with `RETURN` placement that may have parsing edge cases against older Cypher 5 versions. None are reported as broken today, but they are the only candidates worth re-eyeballing before this change ships:

- `backend/services/event_service.py:683-701` — `RETURN e, ci, category ORDER BY e.created_at ASC` (no NULLS clause; OK).
- `backend/services/event_service.py:731-746` — `RETURN e, ci, category ORDER BY e.created_at ASC` (no NULLS clause; OK).
- `backend/services/event_service.py:1057` — `ORDER BY e.created_at DESC` after `RETURN e, ci, m` (no NULLS; OK).
- `backend/services/event_service.py:1103-1110` — `RETURN e, m` then `ORDER BY CASE e.severity WHEN ... END ASC, e.created_at DESC` (no NULLS clause; OK).
- `backend/repositories/topology_repo.py:769` — multi-line `ORDER BY CASE pe.severity WHEN ... END ASC, pe.created_at ASC` (no NULLS; OK).
- `backend/services/ai_chat_service.py:535` — `ORDER BY e.created_at DESC` (no NULLS; OK).
- `backend/engines/snmp_worker.py:265` — `ORDER BY time DESC LIMIT 1` (no NULLS; OK).

None of these need to be modified for issue #459. They are listed so the proposal/spec phase knows the audit boundary.

### Error-swallowing call sites for Cypher exceptions

- `backend/services/event_service.py:1595,1648` — `event_batch_pruner` chunk loop. **Primary suspect** for the silent-failure symptom in the issue.
- `backend/services/event_service.py:1618` — per-event `_close_one` failure swallow inside the same generator; intentionally tolerant to keep the chunk moving.
- `backend/routers/ai.py:304-305` — generic `except Exception: return` (separate issue scope).
- `backend/services/neo4j_write_guard.py` — explicit `cypher-param-fallback` for the unrelated issue #340/#343 bare `poll_collector_id` rejection. **Different Cypher error class.** Strict predicate (`is_poll_collector_id_undefined_error`) so it does NOT cover `Invalid input 'NULLS'`. Safe to leave untouched.

### CypherSyntaxError / Neo4jError handling

- `backend/services/neo4j_write_guard.py:43,51,61` — only place that imports `neo4j.exceptions` for predicate use.
- No production code currently distinguishes `ClientError` (Cypher compile/syntax) from `ServiceUnavailable`, `TransientError`, or other driver errors. The fallback at `neo4j_write_guard.py:81-85` reads `error.message` strictly, so a syntax error that mentions `poll_collector_id` would be caught — but a syntax error mentioning `NULLS` would not match the predicate and would propagate.
- The `@app.exception_handler(Exception)` at `backend/main.py:383-392` is a single global handler that returns 500 with the exception string. It works for synchronous router paths but is bypassed by `event_batch_pruner` (the exception never re-enters the FastAPI handler chain).

## Root cause analysis

**Most likely root cause: `backend/services/event_service.py:1537` is the only production query that uses `NULLS LAST` syntax.** The Cypher 5 grammar (the version Neo4j 5.15 ships) does not include `NULLS FIRST/LAST` as a subclause; only the singular `null` literal is a reserved keyword. The Neo4j manual documents NULL ordering as default behavior: NULLs LAST in ASC, NULLs FIRST in DESC. The `NULLS LAST` clause is therefore both **invalid syntax** AND **redundant** (the default in ASC already places NULLs last).

Secondary root cause: `event_batch_pruner` swallows the `CypherSyntaxError` inside its `try/except Exception` and yields it as a progress dict error chunk instead of failing the SSE stream. After `MAX_CONSECUTIVE_CHUNK_FAILURES = 3` consecutive failures the generator re-raises — but the operator typically sees the empty/stale data first and only finds the log trace on inspection. This is what the issue means by "many requests continue serving stale or empty data instead of failing loudly."

Tertiary (defensive) observation: there is no startup smoke query. A new regression that reintroduces `NULLS LAST` (or any other invalid syntax) will not be caught at process boot — only by the next `/api/events/bulk/stream-progress` traffic.

## Affected Areas

- `backend/services/event_service.py:1537` — the malformed `ORDER BY e.created_at ASC NULLS LAST, e.id ASC` inside `_fetch_page`. **Bug site.**
- `backend/services/event_service.py:1595-1661` — the chunk-level `try/except Exception` that swallows the error before it reaches the global ASGI handler. **Hardening opportunity.**
- `backend/services/event_service.py:1413` — `MAX_CONSECUTIVE_CHUNK_FAILURES = 3`. If the proposal lowers the cap or makes the cap apply per CypherSyntaxError type, this constant changes.
- `backend/tests/test_event_batch_pruner.py:491-558` — `TestEventBatchPrunerNullCursorProgress`. Its docstring and assertions reference `NULLS LAST`. Must be updated to assert the same NULL-safe semantics without requiring the broken syntax.
- `backend/main.py:404-405` — `startup_event` only calls `verify_connection()`. **Hardening opportunity:** add a Cypher smoke query against the Event index/label here so cold-start catches the syntax regression immediately.
- `backend/database.py:37-49` — `verify_connection()` itself; if we add a smoke query, this is the natural home (`verify_cypher_smoke()` or similar).
- `backend/services/neo4j_write_guard.py` — confirmed NOT to swallow this error (predicate is strict on `poll_collector_id not defined`). No change needed.

## Approaches

### Approach 1 — Minimal fix: drop the redundant `NULLS LAST` clause

Rewrite the query at `event_service.py:1537` to:
```cypher
ORDER BY e.created_at ASC, e.id ASC
```
Update `TestEventBatchPrunerNullCursorProgress` to assert that:
1. The query is NULL-safe (the WHERE clauses already use `IS NULL` checks; cursor logic is unchanged).
2. The query does NOT contain `NULLS LAST`/`NULLS FIRST` (regression guard against reintroduction).

- **Pros**: Smallest diff (1 query, 1 test docstring/assertion update). Pure root-cause fix. Preserves the cursor's forward-progress contract via the existing `IS NULL`-safe WHERE tiebreaks (lines 1583, 1592). No new infrastructure.
- **Cons**: Does NOT address the "fail loud" requirement from the issue's "Expected Behavior". A future regression that re-introduces invalid syntax will still be swallowed by `event_batch_pruner`'s try/except.
- **Effort**: Low (~15-25 LOC: 1 line production, ~5-10 lines test).

### Approach 2 — Minimal fix + startup smoke query

Same production fix as Approach 1, plus add `verify_cypher_smoke()` in `backend/database.py` that runs `RETURN 1 AS ok` (or a representative compiled `MATCH (e:Event) RETURN e.id LIMIT 1` plus the actual `_fetch_page` query against a labeled probe node) at startup, and wire it into `startup_event` after `verify_connection()`.

- **Pros**: Matches the issue's "Add a backend startup smoke query that fails loudly on cold start". Catches the regression class (any malformed Cypher that ships in production) at boot, not at the first `/api/events/bulk/stream-progress` request. Defense-in-depth.
- **Cons**: Adds startup latency (a few hundred ms for one round-trip; acceptable). Need to decide whether the smoke query should cover ALL Cypher paths (impractical) or just the representative ones (event pruning, system status). Need a kill-switch for tests where Neo4j is stubbed.
- **Effort**: Low-Medium (~40-60 LOC: 1 helper + 1 main.py wire + 2-3 tests).

### Approach 3 — Minimal fix + fail-loud middleware for CypherSyntaxError

Same production fix as Approach 1, plus refine `event_batch_pruner`'s chunk loop to let `CypherSyntaxError` (or `ClientError` whose `code` matches `Neo.ClientError.Statement.SyntaxError`) propagate immediately instead of being debounced by `MAX_CONSECUTIVE_CHUNK_FAILURES`. Other Cypher errors (`TransientError`, `ServiceUnavailable`) keep the existing 3-strike behavior.

- **Pros**: Matches the issue's "fail loudly with clean 5xx, not swallowed exception inside ASGI middleware". Operators see a real error the first time it happens, not after three silent chunks.
- **Cons**: Subtle — the SSE protocol cannot return a 5xx after the first `data:` frame is already sent. Need to decide between: (a) terminating the SSE stream and returning a final `error` chunk then closing, or (b) keeping the SSE flow but logging at ERROR level and surfacing the syntax-error message distinctly. Approach (b) is what `event_batch_pruner` already does for `error` chunks; we just need to skip the 3-strike debounce for syntax errors.
- **Effort**: Low-Medium (~25-40 LOC: predicate + tests).

### Approach 4 — All three (minimal fix + smoke query + fail-loud)

Combine Approaches 1, 2, and 3.

- **Pros**: Fully addresses the issue's "Expected Behavior" bullets: (a) the broken query compiles, (b) if future syntax is unsupported, startup smoke fails loudly, (c) the SSE stream surfaces the error instead of silently serving stale data.
- **Cons**: Larger diff. The 400-line review budget (per `openspec/config.yaml:7`) is at risk; estimate ~100-150 LOC total (30 prod + 30 smoke + 30 fail-loud + 30-60 tests). Achievable in a single PR but stretches the budget. Could split into chained PRs per the work-unit-commits skill.
- **Effort**: Medium (~100-150 LOC total).

## Recommendation

**Approach 4** — land all three. The issue body explicitly enumerates each of the three sub-fixes ("compile against 5.15.0", "startup smoke query", "fail-loud middleware") as separate acceptance criteria, and the change set is small enough to fit in one chained PR if needed.

Concrete plan for the proposal/spec phase:

1. **Primary fix (Approach 1)**: rewrite `event_service.py:1537` to `ORDER BY e.created_at ASC, e.id ASC`; update `TestEventBatchPrunerNullCursorProgress` to drop the `NULLS LAST` assertion and add a regression assertion that the query does NOT contain `NULLS FIRST/LAST`.
2. **Smoke query (Approach 2)**: add `verify_cypher_smoke(driver)` in `backend/database.py` that runs:
   - `RETURN 1 AS ok` (basic connectivity)
   - `MATCH (e:Event) RETURN e.id LIMIT 1` (representative Event read)
   - One read-only query mirroring the new `_fetch_page` query against the labeled `:Event` index.
   Call from `startup_event()` after `verify_connection()` and `logger.exception` on `ClientError` so a malformed query fails the cold start.
3. **Fail-loud (Approach 3)**: in `event_batch_pruner`, add a `CypherSyntaxError`-or-syntax-equivalent predicate that lets the exception propagate on the first chunk instead of being debounced. Keep the 3-strike behavior for `ServiceUnavailable`/`TransientError`. Document this in the chunk-level docstring so future reviewers understand the asymmetry.
4. **Tests (strict TDD)**:
   - `backend/tests/test_event_batch_pruner.py` — update `TestEventBatchPrunerNullCursorProgress` to assert the new query string and add a regression test that asserts no query in `event_service.py` contains `NULLS FIRST/LAST`.
   - `backend/tests/test_neo4j_smoke.py` (new) — verify `verify_cypher_smoke` raises on `ClientError`, returns True on success, and is no-op when `DISABLE_NEO4J_SMOKE=true` (test kill-switch).
   - `backend/tests/test_event_batch_pruner.py` — extend `TestEventBatchPrunerChunkFailures` (or add sibling) to assert that a `ClientError` whose `code == "Neo.ClientError.Statement.SyntaxError"` propagates on the first failure rather than after 3.

Keep `cypher-param-fallback` (issue #340/#343) untouched. The predicate is strict on `poll_collector_id not defined` and will not absorb `Invalid input 'NULLS'` errors — confirmed by reading `neo4j_write_guard.py:54-85`.

## Risks

- **Split-PR vs single-PR trade-off**: total LOC estimate (~100-150) sits at the edge of the 400-line review budget. A single PR is feasible if the test additions stay focused. A chained PR split (smoke query first, syntax fix second, fail-loud third) is also reasonable. The orchestrator should default to single PR unless `sdd-tasks` forecasts a High budget risk.
- **Smoke query performance**: a `MATCH (e:Event) RETURN e.id LIMIT 1` against a populated Event set is sub-millisecond in production. Acceptable for cold start. The mirror of `_fetch_page` is also bounded (the same `LIMIT 1`); no row scans.
- **Test stub collision**: `conftest.py` already stubs `neo4j` and `neo4j.exceptions` to `MagicMock`. The smoke-query tests need to either patch `database.driver` (already supported via `mock_neo4j_driver` fixture at line 301-323) or set a `DISABLE_NEO4J_SMOKE=true` flag at import time. Verify the test fixture isolation does not leak the real `neo4j.exceptions.ClientError` reference into the unit test process.
- **SSE protocol and syntax errors**: FastAPI's `StreamingResponse` cannot turn a streamed SSE sequence into a 5xx after the first `data:` frame is sent. The fail-loud approach must either (a) emit a final `error` chunk and close, or (b) raise the exception after the response headers are flushed (which the client will see as a truncated stream). Approach (b) is closer to "fail loud" semantics; document the operator-visible behavior in the chunk loop docstring.
- **Other queries not yet audited**: the audit list above includes seven queries with `ORDER BY ... RETURN ...` patterns. None are reported broken today, but a strict TDD discipline asks for a regression test that scans `backend/services/*.py` and `backend/engines/*.py` for any `NULLS FIRST/LAST` token, so a reintroduction (in any file) is caught at test time. This is a small extra test (~15 LOC) that closes the loop on the issue's "investigation step 1".
- **Behavior change for legacy NULL `created_at` rows**: the cursor's NULL-safe WHERE tiebreaks (lines 1583, 1592) already handle NULL rows. Removing `NULLS LAST` is a no-op for sort order because ASC places NULLs last by default. The fix-423 regression test (`test_event_batch_pruner_null_cursor_progress`) must be re-checked to confirm it still verifies the cursor makes forward progress without relying on the broken clause. Its `IS NULL`-safe WHERE assertions (lines 553-556) remain valid.

## Ready for Proposal

Yes — the orchestrator can hand off to `sdd-propose` for `fix-459-neo4j-nulls-cypher`. Tell the user:

1. Root cause verified: `backend/services/event_service.py:1537` uses `ORDER BY ... ASC NULLS LAST` which is not supported in Cypher 5 / Neo4j 5.15. The Cypher 5 grammar treats NULL ordering as default behavior (NULLs LAST in ASC, NULLs FIRST in DESC). The `NULLS` keyword is not in the Cypher 5/25 reserved-keyword list.
2. The clause is also redundant — removing it does not change the sort.
3. The "silent empty/stale data" symptom comes from `event_batch_pruner`'s `try/except Exception` that swallows the syntax error and yields it as a progress chunk instead of failing the SSE stream.
4. Recommended scope: ship Approach 4 (1-line query fix + 1 smoke query helper + 1 fail-loud predicate in the chunk loop + focused tests). Total estimated ~100-150 LOC.
5. The 400-line review budget is reachable in a single PR if test additions stay focused; a chained PR split is acceptable if `sdd-tasks` forecasts High budget risk.
6. Keep `cypher-param-fallback` (issue #340/#343) untouched — its predicate is strict on `poll_collector_id not defined` and will not absorb `Invalid input 'NULLS'`.