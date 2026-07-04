# Apply Progress: Fix Poll Collector Cypher Parameter Root Cause

## Change

`fix-poll-collector-cypher-param-root-cause`

## Mode

Strict TDD

## Completed Tasks

- [x] 1.1 Add regression coverage for `_refresh_snmp_collection_failures` primary query shape.
- [x] 1.2 Add regression coverage for `_refresh_icmp_availability_events` primary query shape.
- [x] 1.3 Add regression coverage for `_refresh_icmp_latency_events` primary query shape.
- [x] 2.1 Property-qualify collection failure existing Event `poll_collector_id` assignment.
- [x] 2.2 Property-qualify ICMP availability existing Event `poll_collector_id` assignment.
- [x] 2.3 Property-qualify ICMP latency existing Event `poll_collector_id` assignment.
- [x] 3.1 Audit primary polling/Event writer Cypher for unqualified direct assignments.
- [x] 3.2 Confirm `backend/services/neo4j_write_guard.py` fallback behavior remains unchanged.
- [x] 4.1 Run focused backend pytest with the requested root-level Python 3.11 command.
- [x] 4.2 Record passing focused pytest evidence after the source fix, while preserving the RED-before limitation.

## Pending Tasks

None.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `backend/tests/test_snmp_worker_cypher_fallback.py` | Unit | ⚠️ Prior local runner was blocked until the orchestrator-provided Python 3.11 venv was used | ⚠️ Regression test exists for `UNWIND $failures`, but executable RED-before output was not captured/preserved before the GREEN edit | ✅ 9/9 focused tests passed with Python 3.11 after source fix | ➖ Single direct query-shape scenario for this helper | ➖ None needed |
| 1.2 | `backend/tests/test_snmp_worker_cypher_fallback.py` | Unit | ⚠️ Same historical runner blocker | ⚠️ Regression test exists for `UNWIND $availability_events`, but executable RED-before output was not captured/preserved before the GREEN edit | ✅ 9/9 focused tests passed with Python 3.11 after source fix | ➖ Single direct query-shape scenario for this helper | ➖ None needed |
| 1.3 | `backend/tests/test_snmp_worker_cypher_fallback.py` | Unit | ⚠️ Same historical runner blocker | ⚠️ Regression test exists for `UNWIND $breaches`, but executable RED-before output was not captured/preserved before the GREEN edit | ✅ 9/9 focused tests passed with Python 3.11 after source fix | ➖ Single direct query-shape scenario for this helper | ➖ None needed |
| 2.1 | `backend/tests/test_snmp_worker_cypher_fallback.py` | Unit | ⚠️ Same historical runner blocker | ⚠️ Covered by task 1.1 regression test; no preserved RED-before execution output | ✅ Implemented; 9/9 focused tests passed with Python 3.11 | ➖ Covered by primary/fallback contrast in existing tests | ➖ Minimal 1-line source fix |
| 2.2 | `backend/tests/test_snmp_worker_cypher_fallback.py` | Unit | ⚠️ Same historical runner blocker | ⚠️ Covered by task 1.2 regression test; no preserved RED-before execution output | ✅ Implemented; 9/9 focused tests passed with Python 3.11 | ➖ Covered by primary/fallback contrast in existing tests | ➖ Minimal 1-line source fix |
| 2.3 | `backend/tests/test_snmp_worker_cypher_fallback.py` | Unit | ⚠️ Same historical runner blocker | ⚠️ Covered by task 1.3 regression test; no preserved RED-before execution output | ✅ Implemented; 9/9 focused tests passed with Python 3.11 | ➖ Covered by primary/fallback contrast in existing tests | ➖ Minimal 1-line source fix |
| 3.1 | N/A | Static audit | N/A | N/A | ✅ Audited direct occurrences; only the three source defects were changed | N/A | N/A |
| 3.2 | N/A | Source review | N/A | N/A | ✅ `backend/services/neo4j_write_guard.py` read and left unchanged | N/A | N/A |
| 4.1 | `backend/tests/test_snmp_worker_cypher_fallback.py` | Unit verification | N/A (verification-only task) | N/A — verification task, no new test written | ✅ `PYTHONPATH="$PWD" /var/folders/z2/jfkx5rs11w9c7546250wxl5c0000gn/T/opencode/next-gen-issue-343-venv/bin/python -m pytest backend/tests/test_snmp_worker_cypher_fallback.py` passed: 9 passed, 1 warning in 0.74s | N/A | N/A |
| 4.2 | `backend/tests/test_snmp_worker_cypher_fallback.py` | Evidence recording | N/A (verification-only task) | ⚠️ RED-before output was not preserved before this continuation; evidence remains historical and cannot be fabricated | ✅ Passing post-fix focused pytest evidence recorded: 9 passed, 1 warning | N/A | N/A |

## Test Summary

- **Total tests written**: 3
- **Total tests passing**: 9 focused tests passing.
- **Layers used**: Unit (3 new regression tests)
- **Approval tests**: None — no refactoring tasks.
- **Pure functions created**: 0

## Verification Attempts

- `python -m pytest tests/test_snmp_worker_cypher_fallback.py` from `backend`: blocked with `zsh:1: command not found: python`.
- `python3 -m pytest tests/test_snmp_worker_cypher_fallback.py` from `backend`: initially blocked with `No module named pytest`.
- Temporary dependency attempt using `PYTHONPATH=/var/folders/.../pytest-next-gen-issue-343 python3 -m pytest ...`: collected 9 tests but failed during import because the local interpreter is Python 3.9.6 and project models use Python 3.10+ union syntax (`str | None`).
- `PYTHONPATH="$PWD" python -m pytest backend/tests/test_snmp_worker_cypher_fallback.py` from the isolated worktree root: blocked in this execution environment with `zsh:1: command not found: python` after confirming the worktree root and branch (`fix/issue-343-cypher-param-root-cause`). The user reported manually preparing Python and that this root-level command works in their environment, but this agent runtime does not expose that `python` executable. `python3` resolves to `/usr/bin/python3` version 3.9.6; no isolated `.venv/bin/python`, Homebrew Python, `uv`, or `pyenv` shim was discoverable from this environment.
- `PYTHONPATH="$PWD" /var/folders/z2/jfkx5rs11w9c7546250wxl5c0000gn/T/opencode/next-gen-issue-343-venv/bin/python -m pytest backend/tests/test_snmp_worker_cypher_fallback.py` from the isolated worktree root: passed with Python 3.11.15 / pytest 8.0.0; collected 9 items; 9 passed, 1 SQLAlchemy deprecation warning in 0.74s.

## RED-Before Limitation

- The regression tests are present and aligned with the spec, but this continuation cannot honestly claim executable RED-before evidence because no preserved failing pytest output from before the GREEN source edit is available in the artifacts.
- Passing focused pytest evidence has now been captured with the root-level command. The RED-before limitation remains historical process debt and is intentionally preserved rather than fabricated.

## Audit Notes

- Direct malformed source assignments in `backend/engines/snmp_worker.py` were changed to `existing.poll_collector_id = $poll_collector_id` at the three designed sites.
- Adjacent source paths matched the design notes: `backend/polling/event_writer.py` uses row-property assignment, and `backend/services/snmp_service.py` already uses `existing.poll_collector_id = $poll_collector_id`.
- `backend/services/neo4j_write_guard.py` was not modified; fallback remains defense-in-depth, not the steady-state fix.

## Workload / PR Boundary

- Mode: single PR
- Current work unit: Fix malformed primary Event writer Cypher with regression coverage
- Boundary: test coverage + three-line source fix + OpenSpec progress artifacts + focused pytest verification evidence
- Estimated review budget impact: low; within 40-90 changed-line forecast.
