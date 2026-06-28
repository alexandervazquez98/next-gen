# Apply Progress — fix-event-duplication-cross-writer

> SDD `apply` phase output for the chained-3 delivery strategy
> (`stacked-to-main` chain). PR1 only; PR2 and PR3 are separate apply
> sessions.

## PR1 — Test infra + lock helper

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
<filled in after `gh pr create`>