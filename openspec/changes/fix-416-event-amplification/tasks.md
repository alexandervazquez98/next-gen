# Tasks: P0 Write-Time Event Correlation Suppression

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | 430–520 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1: roots → PR 2: attachment/orchestration |
| Delivery strategy | ask-always; single P0 PR selected |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: size-exception
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | PR | Focused test | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|
| A | Select roots | P0 | `cd backend && pytest -q tests/test_event_correlation.py -k cycle_root` | N/A—pure | candidate selector/tests |
| B | Topology candidates | P0 | `cd backend && pytest -q tests/test_topology_repo_open_parent.py` | N/A—pure | repo helper/tests |
| C | Materialize roots | P0 | `cd backend && pytest -q tests/test_event_correlation.py -k materialize` | N/A—mocked | materializer/tests |
| D | Attach dependents | P0 | `cd backend && pytest -q tests/test_event_correlation.py -k attach` | N/A—mocked | attachment/tests |
| E | Wire cycle | P0 | `cd backend && pytest -q tests/test_snmp_worker_correlation.py` | N/A—approved mocked cycle | `poll_snmp`/integration tests |

## Phase 1: Candidate Foundation

- [ ] 1. **RED** — Add permutation/non-propagation tests for `cycle_root_candidates` in `backend/tests/test_event_correlation.py` (REQ-001/002/005; SCN-001–003/007). Commit A after GREEN.
- [ ] 2. Create `backend/engines/correlation.py`; implement deterministic, stateless `cycle_root_candidates` (same coverage). Commit A: `feat(events): select same-cycle root candidates`.
- [ ] 3. **RED** — Test `current_cycle_parent_candidates` in `backend/tests/test_topology_repo_open_parent.py`, including missing-parent and `can_propagate=False` (REQ-002/005; SCN-006/007). Commit B after GREEN.
- [ ] 4. Add pure `current_cycle_parent_candidates(observations)` to `backend/repositories/topology_repo.py`; retain depth-three vocabulary and no Neo4j I/O (REQ-002/005). Commit B: `feat(events): derive current-cycle topology candidates`.

## Phase 2: Correlation Passes

- [ ] 5. **RED** — Test `materialize_current_cycle_roots` for all event families, no parent, and lookup error in `backend/tests/test_event_correlation.py` (REQ-001/005/007; SCN-006/009/011). Commit C after GREEN.
- [ ] 6. Implement materialization in `backend/engines/correlation.py`, dispatching existing refresh helpers with `cache={}` and shared lock DB (same coverage). Commit C: `feat(events): materialize current-cycle roots`.
- [ ] 7. **RED** — Test unique multi-metric attachment, retries, counts, and no child CREATE in `backend/tests/test_event_correlation.py` (REQ-003/004/007; SCN-004/005/010). Commit D after GREEN.
- [ ] 8. Implement `attach_dependents_to_roots` in `backend/engines/correlation.py` with rebuilt parent index and existing enrichment (same coverage). Commit D: `feat(events): attach dependents to root events`.

## Phase 3: Orchestration and Verification

- [ ] 9. **RED** — Add `poll_snmp` matrix tests using `MockNeo4jSession.set_sequence_response` in `backend/tests/test_snmp_worker_correlation.py` (REQ-001–007; SCN-001–011), including recovery-before-attach. Commit E after GREEN.
- [ ] 10. Refactor `backend/engines/snmp_worker.py:poll_snmp` to collect → materialize → recover/rebuild → attach with one DB/session and sorted locks (REQ-001–007). Commit E.
- [ ] 11. **GREEN/REFACTOR** — Run `cd backend && pytest -q -m "event or neo4j"`, then `cd backend && python -m pytest -q`; fix only P0 code without weakening tests. Commit E: `fix(events): suppress same-cycle event amplification`.
- [ ] 12. Run `pre-commit run --all-files`, `cd backend && ruff check .`, `cd backend && black --check .`; require zero warnings and review `git diff --stat` against 800 lines. Commit: none unless a work unit changes.
