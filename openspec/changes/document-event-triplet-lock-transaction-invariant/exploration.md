## Exploration: document-event-triplet-lock-transaction-invariant

### Current State
`acquire_event_triplet_lock` is defined in `backend/services/event_lock.py` and executes `SELECT pg_advisory_xact_lock(hashtext(:key))` through the caller-provided SQLAlchemy session/execute object. The helper docstring already says the lock is transaction-scoped and requires the session to stay open through the following Neo4j Event write.

Current production call sites are limited to the three Event writer paths from the prior cross-writer deduplication work:

- `backend/services/snmp_service.py` calls the helper inside `_neo4j_write(pg_db)` while `store_metric_result` holds `with SessionLocal() as pg_db:` around both metric persistence and the Neo4j write path.
- `backend/engines/snmp_worker.py` calls the helper in `_refresh_snmp_collection_failures`, `_refresh_icmp_availability_events`, and `_refresh_icmp_latency_events` only when `lock_db` is provided; `poll_snmp()` creates one `db = SessionLocal()` for the cycle and passes it as `lock_db` before closing it in `finally`.
- `backend/polling/event_writer.py` calls the helper through `_acquire_unsorted_locks`, normally reached through `_acquire_sorted_locks`; `backend/polling/writer_pool.py` passes the live `timescale_db` session into `batch_update_events(..., lock_db=timescale_db)`.

Existing tests already guard lock presence/order and writer coverage, but not the specific session/transaction-lifetime invariant requested by #337. `backend/tests/test_event_writer_lock_guard.py` is the best home for a static guard because it already discovers production Event emitters, validates protected-writer metadata, and uses file-source inspection patterns that run under normal backend pytest. Existing test configuration is `backend/pytest.ini` with `testpaths = tests`; no GitHub workflow file was found in this workspace, so CI scope should assume the normal backend pytest command from `openspec/config.yaml`: `cd backend && python -m pytest`.

### Affected Areas
- `backend/services/event_lock.py` — helper definition and central docstring for the transaction-scoped advisory lock.
- `backend/services/snmp_service.py` — legacy writer call site; already has the strongest inline session-lifetime comment near the call.
- `backend/engines/snmp_worker.py` — external worker call sites; comments mention serialization/sorted ordering but not the `pg_advisory_xact_lock` transaction/session-lifetime invariant at each acquisition block.
- `backend/polling/event_writer.py` — batched queue writer wrapper; comments document sorted acquisition but should explicitly warn that locks must remain inside the caller's open transaction/session.
- `backend/polling/writer_pool.py` — supplies the queue writer's `lock_db`; existing comment says the session stays open for `batch_update_events`.
- `backend/tests/test_event_writer_lock_guard.py` — likely location for a regression test using static source checks around protected writer lock call sites.
- `openspec/specs/event-writer-coordination-observability/spec.md` — existing main spec already contains a coordination-invariants requirement that likely fits this documentation/CI-guard chore.

### Approaches
1. **Add a focused static guard in `test_event_writer_lock_guard.py`** — Extend the existing protected-writer guard with source-level checks that each production `acquire_event_triplet_lock` call is nested in an approved transaction/session context or an approved wrapper whose caller supplies a live session.
   - Pros: Reuses existing CI-friendly static-test pattern; catches import-time/top-level calls; keeps #337 small and aligned with existing writer registry.
   - Cons: AST/source-context logic must avoid overclaiming runtime transaction semantics, especially for wrapper functions that receive `lock_db` from callers.
   - Effort: Low/Medium

2. **Add dedicated runtime tests per writer path** — Patch sessions/locks in each writer test file and assert call order/lifetime behavior separately.
   - Pros: Closer to actual execution paths; complements existing positive lock-order tests.
   - Cons: More duplication; less effective at catching future top-level/import-time lock movement; broader than the chore's documentation/static-regression scope.
   - Effort: Medium

### Recommendation
Use approach 1. Add the inline invariant comment at the lock-acquisition blocks that currently lack it (`engines/snmp_worker.py` and `polling/event_writer.py`; `services/snmp_service.py` already has near-call wording but can be tightened if needed). Then add a focused static regression test in `backend/tests/test_event_writer_lock_guard.py` that scans protected Event writer sources for `acquire_event_triplet_lock` calls and verifies they are not module-level/import-time calls and are contained in approved writer functions/wrappers whose session is supplied by an active `SessionLocal()`/caller-owned `lock_db` path.

OpenSpec scope should be a small chore under the existing Event writer coordination domain, likely modifying `event-writer-coordination-observability` to require inline documentation and CI regression coverage for the transaction/session-lifetime invariant. No behavior change or session-level lock migration should be included.

### Risks
- Static checks can become brittle if they assert exact line structure instead of semantic containment; use AST where practical and keep approved wrapper metadata explicit.
- `polling/event_writer.py` intentionally acquires through `_acquire_sorted_locks`/`_acquire_unsorted_locks`, so the guard must understand wrappers or it will create false positives.
- SQLAlchemy `Session` implicitly opens a transaction on execute; the test should guard that calls are inside approved writer/session lifetimes, not require literal `engine.begin()` syntax everywhere.
- `backend/engines/snmp_worker.py` has multiple helper-level lock calls; the guard must ensure the production caller still passes a live session, not merely that helpers accept `lock_db`.

### Ready for Proposal
Yes — proceed to `sdd-propose`. Tell the user the change is documentation plus static CI guard only, scoped to the existing protected Event writers and the existing Event writer coordination OpenSpec domain.
