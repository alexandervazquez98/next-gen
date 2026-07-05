# Tasks: Event Writer Coordination Observability

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 550-750 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 metrics/settings → PR 2 writer/status wiring → PR 3 docs/polish |
| Delivery strategy | auto-forecast |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Add lock metrics/settings/logging in `backend/services/event_lock.py` and `backend/config.py` | PR 1 | Include unit tests for metrics, thresholds, SQL preservation, and no timeout behavior. |
| 2 | Wire writer contexts and status payload in backend call sites | PR 2 | Depends on PR 1; include propagation and status tests. |
| 3 | Document operational invariants and verify full suite scope | PR 3 | Depends on PR 2; include runbook update and final verification. |

PR1 boundary: this slice is complete when metrics/settings/logging core and focused lock-helper tests are review-ready. Phase 3 writer/status rows and Phase 4 documentation/final-verification rows intentionally remain unchecked for later chained slices.

## Phase 1: RED Foundation Tests

- [x] 1.1 Add failing tests in `backend/tests/test_writer_advisory_lock.py` for acquisition count, wait distribution, p95/p99 alert thresholds, and raw triplet IDs excluded from labels.
- [x] 1.2 Add failing tests in `backend/tests/test_writer_advisory_lock.py` for structured slow-lock logging at 250ms and no INFO log below threshold.
- [x] 1.3 Add failing tests proving `pg_advisory_xact_lock(hashtext(:key))` remains blocking-only with no timeout or fail-open/fail-closed SQL/settings.

## Phase 2: GREEN Lock Observability Core

- [x] 2.1 Add env-backed `EventLockSettings` defaults in `backend/config.py`: INFO 250ms, p95 WARNING 1000ms, p99 CRITICAL 5000ms, bounded sample window.
- [x] 2.2 Implement bounded in-process metrics, percentiles, alert derivation, and test reset helper in `backend/services/event_lock.py`.
- [x] 2.3 Update `acquire_event_triplet_lock(..., writer_context="unknown")` to time acquisition, record metrics after success, and emit bounded structured slow-lock logs.

## Phase 3: RED/GREEN Writer and Status Wiring

- [x] 3.1 Add failing assertions in `backend/tests/test_snmp_worker.py`, `backend/tests/test_snmp_service_collection_failures.py`, and `backend/tests/test_polling_event_writer.py` for expected writer contexts and unchanged lock counts/order.
- [x] 3.2 Thread writer contexts through `backend/engines/snmp_worker.py`, `backend/services/snmp_service.py`, and `backend/polling/event_writer.py` without changing sorted acquisition or session lifetime.
- [x] 3.3 Add failing status tests in `backend/tests/test_system_status.py` for `event_lock` snapshot presence and unchanged health/status behavior.
- [x] 3.4 Expose `get_event_lock_observability_snapshot()` from `backend/services/event_lock.py` through `/api/system/status` in `backend/main.py` only.

## Phase 4: Documentation, Verification

- [ ] 4.1 Review and document the stable snapshot contract after PR2 status wiring; PR1 already implements exporter-ready keys: `acquisitions_total`, `wait_ms`, `alert_state`, `thresholds_ms`, and `by_writer`.
- [ ] 4.2 Update `docs/polling-pipeline-runbook.md` with PostgreSQL identity, session lifetime, sorted locks, thresholds, and #334 CI-guard relationship.
- [ ] 4.3 Run `cd backend && python -m pytest` or document targeted/manual evidence if a relevant automated test cannot reasonably run.
