# Tasks: feat(correlation) unified propagation semantics (#539, PR1 of 4)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~810 in this PR1 |
| 400-line budget risk | Medium (single PR, but cross-cutting; size exception justified) |
| Chained PRs recommended | Yes (PR1 itself is a chained PR, followed by PR2/3/4) |
| Suggested split | 1 PR (this PR1) + 3 follow-up PRs (PR2/3/4) |
| Delivery strategy | single-pr for PR1; chained for the implementation follow-ups |
| Files changed | 3 new + 2 modified in PR1 |

```text
Decision needed before apply: no (all four decisions are now locked)
Chained PRs recommended: yes (PR1 + PR2 + PR3 + PR4)
Chain strategy: PR1 design-only, then PR2/3/4 implementation
400-line budget risk: medium (size exception justified — PR1 is the contract that PR2/3/4 depend on; splitting the contract across PRs would force PR2/3/4 to import from a non-existent module)
```

## Work Units (this PR1)

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|----------------------|-----------------|-------------------|
| W1 | Contract module + contract tests + OpenSpec change + doc update | `cd backend && python3 -m pytest tests/test_correlation_propagation_contract.py -v` | read `docs/correlation-topology-guide.md` "Locked propagation decisions" section | revert `backend/services/correlation_propagation_contract.py`, `backend/tests/test_correlation_propagation_contract.py`, `docs/correlation-topology-guide.md`, `openspec/changes/feat-correlation-propagation-semantics/` |

## Phase 1: Pre-flight (PR1)

- [x] 1.1 Confirm 4 decisions are approved by the maintainer (recorded in this file's "The 4 locked decisions" section above)
- [x] 1.2 Confirm `relationship_types.py:7-13` declares 6 supported CI relationship types (no change needed in PR1)
- [x] 1.3 Confirm `docs/correlation-topology-guide.md` has a "Decision record required before implementation" section to fill in (verified at line 144-151)

## Phase 2: PR1 implementation

- [x] 2.1 Create `backend/services/correlation_propagation_contract.py` with the four locked decisions as constants, helper functions, relationship set registry, and feature flag names (~250 LoC, no I/O)
- [x] 2.2 Create `backend/tests/test_correlation_propagation_contract.py` with parametrized contract tests (33 tests, GREEN by construction)
- [x] 2.3 Update `docs/correlation-topology-guide.md`:
  - Add a new "Locked propagation decisions (issue #539)" section that records the 4 decisions with rationale
  - Replace the "Decision record required before implementation" placeholder with a filled-in "Decision record (issue #539)" section
  - Update the "Next step" section to describe the 4-PR chain
- [x] 2.4 Create `openspec/changes/feat-correlation-propagation-semantics/proposal.md` (~200 LoC)
- [x] 2.5 Create `openspec/changes/feat-correlation-propagation-semantics/specs/cmdb-correlation-propagation/spec.md` with REQ-CORR-PROP-1 through REQ-CORR-PROP-8 (~250 LoC)
- [x] 2.6 Create `openspec/changes/feat-correlation-propagation-semantics/tasks.md` (this file)
- [x] 2.7 GREEN: `pytest backend/tests/test_correlation_propagation_contract.py` → 33 passed
- [x] 2.8 GREEN: full backend test suite stays green (the new module is a leaf; it imports only from `services.relationship_types`)

## Phase 3: PR2 (deferred — chained follow-up)

PR2 implements REQ-CORR-PROP-1, REQ-CORR-PROP-2, REQ-CORR-PROP-3 (the three PhysicalLink-related decisions). Out of scope for PR1.

- [ ] 3.1 RED test in `backend/tests/test_event_correlation.py`: `find_open_parent_event` walks `:CONNECTED_VIA` when the intermediate PhysicalLink has `status = UP` and finds the parent's event
- [ ] 3.2 RED test: same setup with `status = DOWN` returns None
- [ ] 3.3 RED test: same setup with `status = PLANNED` returns None
- [ ] 3.4 RED test: same setup with `status = UNKNOWN` returns the event AND records the propagated event at WARNING severity
- [ ] 3.5 RED test in `backend/tests/test_topology_repo_open_parent.py`: `build_open_parent_index` extends correctly with `:CONNECTED_VIA`
- [ ] 3.6 RED test in `backend/tests/test_snmp_worker_correlation.py`: end-to-end via `_resolve_correlation` — CI-A → PhysicalLink (UP) → CI-B → CI-C (event); CI-A's polled metric becomes PROPAGATED with `root_cause_ci_id` = CI-C
- [ ] 3.7 RED test: same chain with PhysicalLink UNKNOWN; CI-A's metric is recorded with `severity = WARNING`
- [ ] 3.8 RED test: same chain with PhysicalLink DOWN; CI-A stays ROOT
- [ ] 3.9 RED test: `re_query_per_correlation` sub-query — simulate a status change between two correlation queries, assert the second query sees the new value
- [ ] 3.10 RED test: cycle handling — `:CONNECTED_VIA` + cycle in CI graph does not infinite loop
- [ ] 3.11 Implement: extend the four Cypher traversal functions in `backend/repositories/topology_repo.py` to include `:CONNECTED_VIA` with the status gate
- [ ] 3.12 Implement: severity degradation mapping in the event creation path
- [ ] 3.13 Implement: re-query sub-query for status freshness
- [ ] 3.14 Implement: `generate_descendant_event` logic in the polling integration (depends on slice 4 / #443)
- [ ] 3.15 Wire `FEATURE_CMDB_CORRELATION_PHYSICAL_LINK_PROPAGATION_ENABLED` default off; flip to `true` after PR2 lands
- [ ] 3.16 GREEN tests; full backend suite green; PR1 contract tests still green (no contract change in PR2)

## Phase 4: PR3 (deferred — chained follow-up)

PR3 implements REQ-CORR-PROP-4 (the MANAGES / USES / PROVIDES default-propagate decision). Out of scope for PR1.

- [ ] 4.1 RED test in `backend/tests/test_event_correlation.py`: `find_open_parent_event` walks `:MANAGES` and finds the parent's event
- [ ] 4.2 RED test: same setup for `:USES`
- [ ] 4.3 RED test: same setup for `:PROVIDES`
- [ ] 4.4 RED test: `build_open_parent_index` and `build_cycle_parent_index` extend correctly with the 3 new types
- [ ] 4.5 RED test: depth-3 boundary still holds with the 3 new types in the traversal
- [ ] 4.6 Implement: extend the four Cypher traversal functions to include `MANAGES | USES | PROVIDES` (no flag, no gate — the locked decision is `all_propagate`)
- [ ] 4.7 Wire `FEATURE_CMDB_CORRELATION_MANAGES_USES_PROVIDES_ENABLED` default off; flip to `true` after PR3 lands
- [ ] 4.8 GREEN tests; full backend suite green; PR1 + PR2 contract tests still green

## Phase 5: PR4 (deferred — chained follow-up)

PR4 implements the `:CONNECTS_TO` `medium` predicate. Out of scope for PR1.

- [ ] 5.1 RED test in `backend/tests/test_event_correlation.py`: `:CONNECTS_TO` with `medium = "vpn"` does NOT propagate
- [ ] 5.2 RED test: same setup for `medium = "sd_wan"`
- [ ] 5.3 RED test: same setup for `medium = "satellite"`
- [ ] 5.4 RED test: `:CONNECTS_TO` with `medium = "ethernet"` DOES propagate
- [ ] 5.5 RED test: `:CONNECTS_TO` with `medium = null` DOES propagate (pre-#539 behavior preserved for unset values)
- [ ] 5.6 Implement: add `medium` predicate to the four Cypher traversal functions
- [ ] 5.7 Wire `FEATURE_CMDB_CORRELATION_CONNECTS_TO_MEDIUM_FILTER_ENABLED` default off; flip to `true` after PR4 lands
- [ ] 5.8 GREEN tests; full backend suite green; PR1 + PR2 + PR3 contract tests still green

## Critical sequencing

- PR2 depends on PR1 (PR2 imports the contract; without the contract, PR2 has no source of truth for the 3 PhysicalLink decisions)
- PR3 depends on PR1 (PR3 imports the contract; without the contract, PR3 has no source of truth for the M/U/P decision)
- PR4 depends on PR1 (PR4 imports the feature flag name; the `medium` predicate is a separate decision but the flag convention is set in PR1)
- PR3 can ship independently of PR2
- PR4 can ship independently of PR2 and PR3
- PR2's `generate_descendant_event` logic also depends on slice 4 / #443 (interface-to-link polling) landing. The PR2 scope can split into PR2a (traversal + severity + freshness) and PR2b (DOWN event generation) if the slice 4 dependency blocks PR2 merge.

## Cross-references

- Issue: #539
- Design doc: `docs/correlation-topology-guide.md`
- Contract: `backend/services/correlation_propagation_contract.py`
- Contract tests: `backend/tests/test_correlation_propagation_contract.py`
- Sibling OpenSpec change: `openspec/changes/feat-cmdb-physical-links-runtime/` (provides `:CONNECTED_VIA` and `PhysicalLink`)
- Source proposal: `openspec/changes/feat-correlation-propagation-semantics/proposal.md`
- Source spec: `openspec/changes/feat-correlation-propagation-semantics/specs/cmdb-correlation-propagation/spec.md`
