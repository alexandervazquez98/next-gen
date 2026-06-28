# Apply Progress — fix-event-duplication-cross-writer

> SDD `apply` phase output for the chained-3 delivery strategy
> (`stacked-to-main` chain). PR1 merged as #328; PR2 follows; PR3
> (deadlock + integration) is the final piece.

## PR1 — Test infra + lock helper

### Status
complete (merged via PR #328)

### Status
complete

### Branch
`fix-event-dedup-pr1-test-infra`

### Commits (in order)

| SHA (short) | Message |
|-------------|---------|
| `8926219`   | `chore(deps): add testcontainers[postgres] for advisory lock integration tests` |
| `b8d3...`   | `feat(events): add pg_advisory_xact_lock helper for cross-writer coordination` |
| `d19d3b2`   | `test(events): add testcontainers integration test proving pg_advisory_xact_lock semantics` |

(Full SHAs available via `git log fix-event-dedup-pr1-test-infra ^main`.)

### Tasks completed
- **Task 0** — Dependency setup (`testcontainers[postgres]>=4.0` in `backend/requirements-dev.txt`, installed via `uv pip install -r requirements-dev.txt`).
- **Task 1** — Shared lock helper `acquire_event_triplet_lock` in `backend/services/event_lock.py` + MagicMock smoke test.
- **Task 2** — Real-Postgres concurrency proof using `testcontainers[postgres]` (design §6 "Primary test").

### Tasks remaining (out of PR1 scope)
- Task 3 — Batched writer deadlock-prevention tests (PR3).
- Task 4 — `backend/engines/snmp_worker.py` writer integration + flipped assert (PR2).
- Task 5 — `backend/services/snmp_service.py` session lifetime restructuring (PR2).
- Task 6 — `backend/polling/event_writer.py` batch path with sorted acquisition (PR2).
- Task 7 — `poll_collector_id` persistence across all three writers (PR2).
- Task 8 — Full poll-cycle integration test (PR3).
- Task 9 — Full backend suite verification (PR3).

### Test results

| Scope | Passed | Failed | Notes |
|-------|--------|--------|-------|
| `tests/test_writer_advisory_lock.py` (new) | 2 | 0 | Both unit + integration green |
| Writer-related existing tests (`test_polling_event_writer.py`, `test_snmp_worker.py`, `test_snmp_worker_correlation.py`, `test_snmp_service_collection_failures.py`) | 92 | 0 | No regressions in scope |
| Full `backend/tests/` | 1176 | 146 | 146 failures pre-existed on `main`; net delta +2 passed, +0 failed |

The 146 pre-existing failures are unrelated infrastructure tests
(auth, routers, RTU integration, MQTT subscriber). They reproduce on a
clean `main` checkout; PR1 introduces no new regressions.

### Files changed

| File | Action | Notes |
|------|--------|-------|
| `backend/requirements-dev.txt` | modified | +1 line: `testcontainers[postgres]>=4.0` |
| `backend/services/event_lock.py` | created | `acquire_event_triplet_lock` helper (single primitive) |
| `backend/tests/test_writer_advisory_lock.py` | created | 2 tests: MagicMock smoke + real-Postgres race proof |

### Strict TDD evidence

| Task | Sub-step | RED | GREEN | Refactor |
|------|----------|-----|-------|----------|
| 0 | dep setup | N/A (config) | verified `import testcontainers` | — |
| 1 | 1.1 helper test | `ModuleNotFoundError: No module named 'backend.services.event_lock'` | after 1.2 impl: PASS | docstring refined |
| 1 | 1.2 helper impl | — | PASS | — |
| 2 | 2.1 integration test | Initially RED — required fixing race in thread coordination and psycopg2 stub swap | after fixes: PASS | clean, no debug noise |

### Notes for PR2 (writer integration)

- All three writers (`backend/engines/snmp_worker.py`, `backend/services/snmp_service.py`, `backend/polling/event_writer.py`) currently DO NOT call `acquire_event_triplet_lock`. PR2 must wire them up.
- Per design §3 (Postgres Session Lifecycle):
  - `snmp_worker.py`: refactor `db = SessionLocal()` so it stays open across the Neo4j write; pass into `_refresh_snmp_collection_failures` / `_refresh_icmp_availability_events` / `_refresh_icmp_latency_events`.
  - `snmp_service.py`: extend `with SessionLocal() as pg_db:` to wrap BOTH the Timescale insert AND the Neo4j write (currently closes at line 431, before line 433 Neo4j block).
  - `polling/event_writer.py`: change signature `batch_update_events(driver, envelopes)` → `batch_update_events(driver, envelopes, lock_db)`. Pass the leased `timescale_db` from `writer_pool.py:291`.
- Per design §4 (deterministic ordering): any writer acquiring locks for more than one triplet MUST sort lexicographically before acquiring. This rule applies to `event_writer.py` (batched path) for sure; check `snmp_worker.py` to see if it shares a transaction across multiple CREATE paths.
- Flipped assertions to update in PR2:
  - `backend/tests/test_polling_event_writer.py:195` and `:507` — replace negative MERGE-absent assertions with positive `pg_advisory_xact_lock` required checks.
  - `backend/tests/test_snmp_worker.py:866` — same flip on `_refresh_icmp_latency_events`.
- Per-writer integration tests (similar pattern to `test_concurrent_writers_block_on_lock`) belong in PR2.

### Notes for PR3 (deadlock prevention + integration)

- Task 3 tests will reuse the same `_swap_in_real_psycopg2` helper from PR1. Both new tests should land RED initially (writers don't sort yet), then GREEN after Task 6.2 lands in PR2.

### PR link
https://github.com/alexandervazquez98/next-gen/pull/328

---

## PR2 — Wire all 3 writers to lock helper + poll_collector_id

### Status
complete (PR opened, awaiting review)

### Branch
`fix-event-dedup-pr2-writers` (targets `main` directly — stacked-to-main)

### Chain context

- **Dependency**: depends on PR1's `acquire_event_triplet_lock` helper (PR #328 merged into main).
- **Next**: PR3 (deadlock prevention tests + full-cycle integration + full suite verification) — separate session.
- **Out of scope (this PR)**: Task 3 (deadlock tests), Task 8 (full poll-cycle integration), Task 9 (full suite verification).

### Commits (in order)

| SHA (short) | Message |
|-------------|---------|
| `12a8e50` | `feat(snmp-worker): wire 3 refresh helpers to acquire_event_triplet_lock + persist poll_collector_id` |
| `05a878e` | `feat(snmp-service): restructure session lifetime + acquire pg_advisory_lock + persist poll_collector_id` |
| `e796afe` | `feat(event-writer): add lock_db parameter + sorted triplet acquisition + poll_collector_id` |
| `a40ea7a` | `feat(events): centralize poll_collector_id helper in services.event_lock` |

### Tasks completed
- **Task 4** — `backend/engines/snmp_worker.py` — 3 refresh helpers (`_refresh_snmp_collection_failures`, `_refresh_icmp_availability_events`, `_refresh_icmp_latency_events`) now accept `lock_db` and acquire sorted `pg_advisory_xact_lock` per distinct triplet before `session.run`. `poll_snmp()` passes its `db = SessionLocal()` as `lock_db` to all 3 helpers.
- **Task 5** — `backend/services/snmp_service.py` — `pg_db = SessionLocal() ... pg_db.close()` restructured to ONE `with SessionLocal() as pg_db:` wrapping BOTH the Timescale metric insert AND the Neo4j write. `acquire_event_triplet_lock` called before the existing-Event read at the original line 493. Conditional PG session opening preserved (no PG session when no metric insert and no breach).
- **Task 6** — `backend/polling/event_writer.py` — `batch_update_events` signature `→ (driver, envelopes, lock_db=None)`. New `_acquire_sorted_locks()` helper acquires distinct triplets in lexicographic order BEFORE each UNWIND query (collection failures AND non-collection rows). `writer_pool.run_writer_once` passes `lock_db=timescale_db` (leased session still open).
- **Task 7** — `poll_collector_id` centralized into `backend/services/event_lock.py::get_poll_collector_id()` (cached at module load, raises `RuntimeError` if both `HOSTNAME` and `socket.gethostname()` are empty). All 3 writer modules import the helper; `os` / `socket` imports removed where no longer needed.

### Tasks remaining (out of PR2 scope)
- Task 3 — Batched writer deadlock-prevention tests (PR3, will reuse `_swap_in_real_psycopg2` from PR1).
- Task 8 — Full poll-cycle integration test (PR3).
- Task 9 — Full backend suite verification (PR3).

### Test results

| Scope | Passed | Failed | Notes |
|-------|--------|--------|-------|
| `tests/test_writer_advisory_lock.py` (PR1 + new helper tests) | 5 | 0 | 2 PR1 tests + 3 new tests for `get_poll_collector_id` (non-empty, cache, RuntimeError) |
| `tests/test_snmp_worker.py` (PR1 + new lock test) | 33 | 0 | +1 new test: `test_refresh_icmp_latency_events_acquires_pg_advisory_lock_before_neo4j_write` |
| `tests/test_snmp_service_collection_failures.py` | 13 | 0 | +3 new tests: pg session lifetime, lock acquisition, poll_collector_id persistence |
| `tests/test_snmp_service_snapshots.py` | 6 | 0 | existing tests patched with `_make_context_mock` for `SessionLocal` |
| `tests/test_polling_event_writer.py` | 28 | 0 | +2 flipped asserts (lines 195 & 507), +2 new tests (sorted acquisition + poll_collector_id) |
| `tests/test_polling_writer_pool.py` | 11 | 0 | lambda stubs updated to accept `**kwargs` for `lock_db` |
| Writer-related in-scope total | 122 | 0 | No regressions |
| Full `backend/tests/` (excl. rtu_integration, subscriber_e2e) | **1181** | **139** | +9 new tests passing vs `main` (1172 passed); 139 failures pre-existed on `main` (RTU routers, MQTT subscriber, etc., unrelated per issue #267). PR2 introduces **zero new failures**. |

### Files changed

| File | Action | Notes |
|------|--------|-------|
| `backend/engines/snmp_worker.py` | modified | +62/-15 (whitespace-ignored): 3 helpers gain `lock_db` param; lock acquisition + sorted sort + Cypher `poll_collector_id`; module imports `POLL_COLLECTOR_ID` from `services.event_lock` |
| `backend/services/snmp_service.py` | modified | +46/-14 (whitespace-ignored): session-lifetime restructure (raw diff larger due to `with` block indentation); imports `POLL_COLLECTOR_ID`; new `_neo4j_write` helper to avoid code duplication between the PG-session and no-PG-session paths |
| `backend/polling/event_writer.py` | modified | +63/-6: `batch_update_events` signature change; new `_acquire_sorted_locks` helper; `build_event_rows` includes `poll_collector_id`; UNWIND Cypher passes `poll_collector_id: row.poll_collector_id` |
| `backend/polling/writer_pool.py` | modified | +12/-1: `batch_update_events` call now passes `lock_db=timescale_db` |
| `backend/services/event_lock.py` | modified | +47: new `get_poll_collector_id()` helper + `_CACHED_HOSTNAME` cache + `POLL_COLLECTOR_ID` constant |
| `backend/tests/test_writer_advisory_lock.py` | modified | +67: 3 new tests for `get_poll_collector_id` (non-empty, cache, RuntimeError) |
| `backend/tests/test_snmp_worker.py` | modified | +67: 1 new test (lock acquisition + before-Neo4j ordering) |
| `backend/tests/test_snmp_service_collection_failures.py` | modified | +190: 3 new tests + `_make_context_mock` helper + 3 existing tests patched with the helper |
| `backend/tests/test_snmp_service_snapshots.py` | modified | +16: `_make_context_mock` helper + 2 existing tests updated for context-manager `SessionLocal` |
| `backend/tests/test_polling_event_writer.py` | modified | +153: 2 flipped assertions (lines 195 & 507), 2 new tests (sorted lexicographic + poll_collector_id in built row) |
| `backend/tests/test_polling_writer_pool.py` | modified | +5: 5 `lambda driver, rows:` → `lambda driver, rows, **kwargs:` to accept `lock_db` kwarg |

### Reviewer-relevant diff (whitespace-ignored)

```
backend/engines/snmp_worker.py            +62
backend/polling/event_writer.py           +63
backend/polling/writer_pool.py            +12
backend/services/event_lock.py            +47
backend/services/snmp_service.py          +46
─────────────────────────────────────────────
TOTAL production additions                +230   (well within 400-line budget)
```

Test additions: +498 lines (positive flipped assertions, new lock + collector helper tests). Snmp_service raw diff inflates to ~428 lines due to indentation changes from the `with` block restructure; semantic diff is +46 lines.

### Strict TDD evidence

| Task | Sub-step | RED | GREEN | Refactor |
|------|----------|-----|-------|----------|
| 4 | 4.1 snmp-worker lock test | `AttributeError: ... does not have the attribute 'acquire_event_triplet_lock'` | after 4.2 impl + poll_collector_id Cypher: PASS | docstring on lock acquisition block |
| 5 | 5.1 snmp-service pg lifetime test | `pg context was never entered` (call_order empty) | after 5.3 refactor: PASS | introduced `_make_context_mock` test helper |
| 5 | 5.2 snmp-service lock test | `AttributeError: ... does not have the attribute 'acquire_event_triplet_lock'` | after 5.4: PASS | — |
| 5 | 5.3 snmp-service collector test | `poll_collector_id MUST be set in CREATE clause` | after 5.3: PASS | — |
| 6 | 6.1 event-writer breach flipped assert | `AttributeError: ... does not have the attribute 'acquire_event_triplet_lock'` | after 6.2: PASS | tightened call_order to track query text alongside kind |
| 6 | 6.1 event-writer discriminator flipped assert | `mock_lock.call_count >= 2` (was 1 with single-event-type envelope) | after fixing test envelope shape (NO_DATA + threshold breach): PASS | — |
| 6 | 6.1 event-writer sorted-acquisition test | `assert mock_lock.call_order == [X, Y, Z]` failed (no sort yet) | after 6.2: PASS | proved by reverse-ordered input |
| 6 | 6.2 event-writer poll_collector_id row test | `poll_collector_id MUST be in row` | after 6.2: PASS | — |
| 7 | 7.1 helper returns non-empty | `ImportError: cannot import name 'get_poll_collector_id'` | after helper impl: PASS | — |
| 7 | 7.2 helper is cached | `AttributeError: ... has no attribute '_CACHED_HOSTNAME'` | after impl: PASS | — |
| 7 | 7.3 helper raises on empty hostname | same AttributeError | after impl: PASS | — |

### Discoveries worth noting

- **MagicMock `with` gotcha**: `with FakeMock() as x:` does NOT bind `x` to `FakeMock`. By default `FakeMock.__enter__.return_value` is a NEW MagicMock. Must explicitly set `fake.__enter__.return_value = fake` for identity assertions (`is fake`) to hold. Introduced `_make_context_mock()` helper in two test files.
- **Snmp_service restructure cost**: Wrapping `pg_db = SessionLocal()...pg_db.close()` in `with SessionLocal() as pg_db:` doubles the function's indentation for the entire Neo4j block, inflating the raw diff to ~428 lines. Whitespace-ignored diff is +46/-14; semantic change is small.
- **Lambda mock fragility**: Tests using `monkeypatch.setattr(..., lambda driver, rows: ...)` need `**kwargs` once the function gains new kwargs. The lock_db parameter broke 5 mocks until updated.
- **POLL_COLLECTOR_ID centralization**: Removed `os` / `socket` imports from all 3 writers, replaced inline hostname resolution with single helper import. Future PR (observability #326) can leverage this for metrics.
- **Deterministic lock ordering**: The test that proves sorted acquisition uses REVERSE-ordered envelopes (Z,Y,X) and asserts locks come out in lex order (X,Y,Z). This pattern catches off-by-one sort errors that a same-order test would miss.

### Notes for PR3

- Task 3 deadlock-prevention tests reuse `_swap_in_real_psycopg2` from PR1. The `test_sorted_lock_acquisition_prevents_deadlock` should now pass (writers DO sort). `test_unsorted_lock_acquisition_deadlocks` will fail unless we add a deliberate unsorted path — PR3 may need to construct a synthetic test that bypasses `event_writer._acquire_sorted_locks` to prove the deadlock exists in the unsorted case.
- Task 8 full poll-cycle integration test should now exercise `poll_snmp()`, `store_metric_result()`, and `batch_update_events()` concurrently against the same triplet and assert exactly 1 Event CREATE per triplet.
- Task 9 full suite verification: run `cd backend && uv run pytest backend/tests/...` and confirm 0 new failures. Pre-existing 139 failures on `main` are unrelated (RTU routers, MQTT subscriber) per issue #267.

### PR link
<filled in after `gh pr create`>