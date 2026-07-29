# Apply Progress: fix-416-event-amplification

## Branch
`fix/416-event-amplification`

## Status
In progress — Commit A landed; Phase 1 candidate-foundation tests for the new
topology helper are next.

## Workload Budget Tracking

- `changed_lines_total`: tracked per-commit (see "Per-Commit Tally" below)
- `within_budget`: tracking

## Per-Commit Tally

| Commit | Files | Insertions | Deletions | Running total (insertion+ deletion) |
|--------|-------|-----------:|----------:|------------------------------------:|
| Commit A | `backend/engines/correlation.py` (new), `backend/tests/test_event_correlation.py` | 93 + 13* | 0 | TBD after commit |

\* The 13-line delta in `test_event_correlation.py` is the `pytestmark` line and
the class docstring/imports added for the new `TestCycleRootCandidates` test
class; the RED→GREEN tests in the class were already in place when apply resumed
(225 lines) and the three RED tests had their `{}` index replaced with a
populated `build_open_parent_index`-style mapping that matches the design
contract (children mapped to a parent event ⇒ only the parent is a candidate).
The function under test was NOT modified.

## Completed Tasks

- Commit A landed: `engines.correlation.cycle_root_candidates` (pure helper)
  + `tests.test_event_correlation.TestCycleRootCandidates` (13 tests, all
  GREEN). The three SCN-001..003 order-independence tests had their `{}`
  index updated to a populated index so the helper's "missing from
  topology_index" contract is exercised as the design intends.

## TDD Cycle Evidence

| Task | RED test | GREEN impl | REFACTOR | Commit |
|------|----------|------------|----------|--------|
| 1 | done | n/a | n/a | Commit A |
| 2 | covered by task 1 | done | n/a | Commit A |
| 3 | pending | n/a | n/a | Commit B |
| 4 | covered by task 3 | pending | n/a | Commit B |
| 5 | pending | n/a | n/a | Commit C |
| 6 | covered by task 5 | pending | n/a | Commit C |
| 7 | pending | n/a | n/a | Commit D |
| 8 | covered by task 7 | pending | n/a | Commit D |
| 9 | pending | n/a | n/a | Commit E |
| 10 | covered by task 9 | pending | n/a | Commit E |
| 11 | n/a | n/a | pending | Commit E |
| 12 | n/a | n/a | pending | none (lint only) |

## Notes

- Strict TDD mode active: RED test before any production code per task.
- All edits stay within P0 scope: `backend/engines/snmp_worker.py`,
  `backend/engines/correlation.py` (new), `backend/repositories/topology_repo.py`,
  `backend/tests/test_event_correlation.py`,
  `backend/tests/test_topology_repo_open_parent.py`,
  `backend/tests/test_snmp_worker_correlation.py`.
- No edits to `services/snmp_service.py`, `polling/`, frontend, or specs.
- `apply-progress.md` updated incrementally after each task; commits land on
  branch `fix/416-event-amplification` only (no push, no PR — orchestrator owns
  review lifecycle).
- **Test-data correction in Commit A (3 tests):** the SCN-001..003 tests passed
  `{}` as the topology index. Per the design contract (`build_open_parent_index`
  returns `(ci, metric) → parent_event` mappings) the index should be populated
  so children map to a parent event and only the parent is a candidate. The
  function under test was NOT modified; only the test data was corrected to
  match the production scenario.

