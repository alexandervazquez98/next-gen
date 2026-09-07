# Proposal: Fix Neo4j `NULLS LAST` CypherSyntaxError (#459)

## Intent

`event_service.py:1537` emits `ORDER BY e.created_at ASC NULLS LAST, e.id ASC`. Cypher 5 (Neo4j 5.15.0) has no `NULLS` keyword — ASC already sorts NULLs last — so the clause is invalid and redundant. Every prune page raises `Neo.ClientError.Statement.SyntaxError`, which `event_batch_pruner` swallows into an SSE chunk: operators see stale data, not a failure. No boot-time check catches this.

## Scope

### In Scope
- Remove `NULLS LAST` at `event_service.py:1537`.
- Add `verify_cypher_smoke()` in `database.py`, wired into startup only.
- Fail-loud predicate: syntax errors bypass the 3-strike chunk debounce.
- Regression scan rejecting `NULLS\s+(FIRST|LAST)` under `backend/services/` and `backend/engines/`.
- Retarget `TestEventBatchPrunerNullCursorProgress`, which asserts the broken clause today.

### Out of Scope
- `cypher-param-fallback` (#340/#343) — its `poll_collector_id` predicate cannot absorb this error.
- `routers/ai.py:304` bare `except Exception: return`.
- The 7 audited `ORDER BY` queries; none are broken and the scan covers them.
- MCP/runtime changes; Neo4j version bump.

## Capabilities

### New Capabilities
- `neo4j-cypher-compatibility`: boot-time Cypher smoke validation plus static scan rejecting unsupported ordering syntax.

### Modified Capabilities
- `event-prune-recovery-lifecycle`: "Cursor Forward Progress on NULL `created_at`" must mandate Cypher-5-valid NULL-safe ordering (implicit ASC placement, no explicit `NULLS`), plus a fail-loud rule for syntax errors.

## Approach

Drop the invalid clause — sort order is unchanged, since the `IS NULL` WHERE tiebreaks (lines 1583/1592) carry cursor progress. Add defense-in-depth so reintroduction fails at boot or in CI, and surface syntax errors on the first chunk.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `event_service.py:1537` | Modified | Bug site |
| `event_service.py:1645-1660` | Modified | Fail-loud predicate |
| `database.py:37-49` | Modified | `verify_cypher_smoke()` |
| `main.py:405` | Modified | Startup wiring |
| `tests/test_event_batch_pruner.py` | Modified | Retarget, add scan |
| `tests/test_neo4j_smoke.py` | New | Smoke coverage |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Smoke inside `verify_connection()` fires every 3s — `main.py:889` calls it per `/system/status` poll | High | Separate helper, wired at `main.py:405` only |
| SSE cannot 5xx after the first `data:` frame | Med | Terminal `error` chunk, log ERROR, close stream |
| Smoke hard-blocks cold start | Med | `DISABLE_NEO4J_SMOKE` kill-switch; `LIMIT 1` reads |
| `conftest.py` stubs `neo4j` as `MagicMock` | Med | Reuse `mock_neo4j_driver`; assert real `ClientError` |

## Rollback Plan

Single PR, read/boot paths only. `git revert` the merge commit restores prior behavior. No schema change, migration, or backfill.

## Dependencies

- Neo4j 5.15.0 (`docker-compose.yml`); no version bump required.

## Success Criteria

- [ ] No `Invalid input 'NULLS'` in logs over a 1-hour post-deploy window.
- [ ] `/api/events/bulk/stream-progress` prunes with `processed > 0`, no `error` chunk.
- [ ] CI fails if `NULLS FIRST/LAST` reappears in `backend/services/` or `backend/engines/`.
- [ ] Startup smoke fails loudly on incompatible Cypher; `/system/status` latency unchanged.
- [ ] `SyntaxError` propagates on the first chunk, not the third.
