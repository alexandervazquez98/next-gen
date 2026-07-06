# Tasks: Document Event Triplet Lock Transaction Invariant

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 120-220 |
| 800-line budget risk | Low |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low
800-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Static guard and invariant docs | PR 1 | Keep tests, comments, spec/doc updates, and focused pytest together. |

## Phase 1: TDD Guard Expansion (RED)

- [x] 1.1 In `backend/tests/test_event_writer_lock_guard.py`, add AST helpers/dataclass metadata for approved lock paths and enclosing functions.
- [x] 1.2 Add synthetic-source tests proving module-level, wrong-function, and missing-wrapper `acquire_event_triplet_lock` placement fails.
- [x] 1.3 Add current-source guard tests for `services/snmp_service.py`, `engines/snmp_worker.py`, and `polling/event_writer.py`; confirm they fail before metadata/comment support is complete.

## Phase 2: Static Guard Implementation (GREEN)

- [x] 2.1 Implement approved path metadata in `backend/tests/test_event_writer_lock_guard.py` for `store_metric_result._neo4j_write`, SNMP worker refresh functions, and polling wrapper flow.
- [x] 2.2 Assert production lock calls are contained only in approved acquisition functions and approved caller/session paths.
- [x] 2.3 Assert approved function/docstring scope includes invariant keywords: `pg_advisory_xact_lock`, transaction, session, and Event write lifetime wording.

## Phase 3: Invariant Documentation

- [x] 3.1 Add near-call invariant comments in `backend/engines/snmp_worker.py` for the three refresh lock blocks and the `poll_snmp()` cycle-owned `db` path.
- [x] 3.2 Tighten docstrings/comments in `backend/polling/event_writer.py` for `_acquire_sorted_locks`, `_acquire_unsorted_locks`, `batch_update_events`, and caller-owned `lock_db` lifetime.
- [x] 3.3 Review `backend/services/snmp_service.py` existing `SessionLocal()`/`_neo4j_write(pg_db)` comment and adjust wording only if required by the guard.
- [x] 3.4 Update `openspec/changes/document-event-triplet-lock-transaction-invariant/specs/event-writer-coordination-observability/spec.md` only if implementation reveals wording gaps.

## Phase 4: Verification and Cleanup

- [x] 4.1 Run focused pytest with the temp venv interpreter from `backend` (`python -m pytest tests/test_event_writer_lock_guard.py` equivalent) and fix only guard/comment issues.
- [x] 4.2 Optionally run `cd backend && python -m pytest` if the environment is ready; otherwise document focused pytest evidence.
- [x] 4.3 Ensure no production behavior, lock primitive, timeout policy, transaction ownership, or runtime interfaces changed.
