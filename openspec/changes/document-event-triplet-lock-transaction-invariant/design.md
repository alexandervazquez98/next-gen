# Design: Document Event Triplet Lock Transaction Invariant

## Technical Approach

Implement #337 as documentation plus static regression coverage only. Add invariant comments at the production Event triplet lock acquisition/wrapper paths, then extend `backend/tests/test_event_writer_lock_guard.py` so protected writers remain registered and every approved acquisition path is modeled by function-level AST metadata rather than exact line text.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Guard shape | AST/function containment plus explicit approved path metadata | Regex/line-neighbor assertions | Function ownership survives comment wrapping, formatting, and unrelated line movement. |
| Wrapper modeling | Treat `_acquire_sorted_locks` as the production-approved wrapper and `_acquire_unsorted_locks` as an internal callee only | Require direct `acquire_event_triplet_lock` in `batch_update_events` | Queue writer intentionally centralizes sorted acquisition to avoid deadlocks; direct-call-only would create false positives. |
| Runtime scope | No behavior changes; no runtime lock tests added | Add integration/concurrency tests | The requirement is invariant documentation and CI static guard coverage, not proving Postgres contention behavior. |

## Data Flow

Existing flow remains unchanged:

```text
SessionLocal/timescale_db open
  └─ acquire_event_triplet_lock(pg_advisory_xact_lock)
       └─ Neo4j Event OPTIONAL MATCH / FOREACH(CREATE) or UNWIND write
            └─ PostgreSQL transaction/session close releases lock
```

Static guard flow:

```text
test_event_writer_lock_guard.py
  └─ parse protected writer sources with ast
       ├─ find acquire_event_triplet_lock calls
       ├─ map calls to enclosing functions
       └─ compare against approved acquisition/session-path registry
```

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/engines/snmp_worker.py` | Modify | Add invariant comments near the three lock blocks in `_refresh_snmp_collection_failures`, `_refresh_icmp_availability_events`, `_refresh_icmp_latency_events`, and optionally at `poll_snmp()` where cycle-owned `db = SessionLocal()` is passed as `lock_db` until `finally: db.close()`. |
| `backend/polling/event_writer.py` | Modify | Add wrapper comments/docstrings explaining `_acquire_sorted_locks` is the production path, `_acquire_unsorted_locks` is an internal/testable loop, and caller-owned `lock_db` must remain open through the Event UNWIND writes. |
| `backend/services/snmp_service.py` | Modify | Tighten existing near-call wording only if needed; keep the existing `with SessionLocal() as pg_db:` plus `_neo4j_write(pg_db)` structure unchanged. |
| `backend/tests/test_event_writer_lock_guard.py` | Modify | Add AST helper dataclasses/functions and tests for approved lock acquisition/session-lifetime paths. |

## Interfaces / Contracts

No production interfaces change. Test-only metadata should model paths explicitly:

```python
@dataclass(frozen=True)
class ApprovedLockPath:
    module: str
    acquisition_functions: tuple[str, ...]
    approved_callers: tuple[str, ...]
    session_lifetime: str
```

Approved paths:
- `services/snmp_service.py`: `acquire_event_triplet_lock` inside `store_metric_result.<locals>._neo4j_write`; caller path `store_metric_result` opens `SessionLocal()` and calls `_neo4j_write(pg_db)`.
- `engines/snmp_worker.py`: direct calls inside `_refresh_snmp_collection_failures`, `_refresh_icmp_availability_events`, `_refresh_icmp_latency_events`; caller path `poll_snmp` owns `db = SessionLocal()` and passes `lock_db=db` before `db.close()`.
- `polling/event_writer.py`: direct calls only inside `_acquire_unsorted_locks`; production approval comes from `_acquire_sorted_locks` calling `_acquire_unsorted_locks`, and `batch_update_events` calling `_acquire_sorted_locks(lock_db, ...)` before Event UNWIND queries.

Do not assert exact comments, line numbers, or adjacent text. Assert AST call containment, approved function names, and source contains the required invariant keywords near the approved function/docstring scope: `pg_advisory_xact_lock`, `transaction`, `session`, and Event write/lifetime wording.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Static unit | Unapproved lock movement fails | Add synthetic-source tests for module-level/direct wrong-function calls and missing wrapper approval. |
| Static unit | Current production paths pass | Parse current protected writer files and compare calls to approved path metadata. |
| Backend regression | Full guard integrates with pytest | Run `cd backend && python -m pytest tests/test_event_writer_lock_guard.py`; optionally run `cd backend && python -m pytest` if environment allows. |
| Runtime/E2E | Not applicable | No runtime behavior is changed. |

## Migration / Rollout

No migration required. Rollout is comments plus test-only static guard.

## Non-Goals

- No runtime behavior change.
- No transaction redesign.
- No lock primitive migration away from `pg_advisory_xact_lock`.
- No new fail-open/fail-closed/timeout policy.

## Open Questions

None.
