# Tasks: Fix Poll Collector Cypher Parameter Root Cause

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 40-90 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR: regression tests + 3-line source fix + focused verification |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Fix malformed primary Event writer Cypher with regression coverage | PR 1 | Single work unit; keep RED, GREEN, audit, and pytest evidence together. |

## Phase 1: RED Regression Coverage

- [x] 1.1 Add failing coverage in `backend/tests/test_snmp_worker_cypher_fallback.py` for `_refresh_snmp_collection_failures`, capturing the primary `UNWIND $failures` query and rejecting bare `poll_collector_id = $poll_collector_id`.
- [x] 1.2 Add failing coverage in `backend/tests/test_snmp_worker_cypher_fallback.py` for `_refresh_icmp_availability_events`, capturing the primary `UNWIND $availability_events` query and requiring `existing.poll_collector_id = $poll_collector_id`.
- [x] 1.3 Add failing coverage in `backend/tests/test_snmp_worker_cypher_fallback.py` for `_refresh_icmp_latency_events`, capturing the primary `UNWIND $breaches` query and requiring `existing.poll_collector_id = $poll_collector_id`.

## Phase 2: GREEN Source Fix

- [x] 2.1 Modify `backend/engines/snmp_worker.py` collection failure primary query so the existing Event update sets `existing.poll_collector_id = $poll_collector_id`.
- [x] 2.2 Modify `backend/engines/snmp_worker.py` ICMP availability primary query so the existing Event update sets `existing.poll_collector_id = $poll_collector_id`.
- [x] 2.3 Modify `backend/engines/snmp_worker.py` ICMP latency primary query so the existing Event update sets `existing.poll_collector_id = $poll_collector_id`.

## Phase 3: Audit Boundary

- [x] 3.1 Audit primary polling/Event writer Cypher for unqualified `poll_collector_id = $poll_collector_id`; report-and-stop before changing suspicious adjacent findings outside the three direct assignments.
- [x] 3.2 Confirm `backend/services/neo4j_write_guard.py` fallback behavior remains unchanged and is not treated as the steady-state fix.

## Phase 4: Verification

- [x] 4.1 Run focused backend pytest from the worktree root: `PYTHONPATH="$PWD" /var/folders/z2/jfkx5rs11w9c7546250wxl5c0000gn/T/opencode/next-gen-issue-343-venv/bin/python -m pytest backend/tests/test_snmp_worker_cypher_fallback.py`.
- [x] 4.2 Record passing focused pytest evidence and explicitly document that executable RED-before output was not preserved before the GREEN edit.
