# Tasks: feat(correlation) unified propagation semantics (#539, PR1 + reconciled chain)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~810 in PR1; ~250-450 per slice in the reconciled chain |
| 400-line budget risk | Medium (PR1 is cross-cutting; each chained slice is sized to stay inside the budget) |
| Chained PRs recommended | Yes (PR1 plus the reconciled chain) |
| Suggested split | PR1 + PR2a1 + PR2a2 + PR2b1 + PR2b2 + PR2c1 + PR2c2 + PR3 + PR4 |
| Delivery strategy | single-pr for PR1; chained for the implementation follow-ups |
| Files changed | 3 new + 2 modified in PR1; 4 documentation/spec files in the T1 reconciliation |

```text
Decision needed before apply: no (all four decisions are locked and the reconciled connectivity contract is recorded)
Chained PRs recommended: yes (PR1 + PR2a1 + PR2a2 + PR2b1 + PR2b2 + PR2c1 + PR2c2 + PR3 + PR4)
Chain strategy: PR1 design-only, then PR2a1 (connectivity) -> PR2a2 (traversal) -> PR2b1 (modern severity) -> PR2b2 (legacy alignment) -> PR2c1 (DOWN event) -> PR2c2 (bridge + rollout flag), then PR3 and PR4
400-line budget risk: medium (size exception justified for PR1 — it is the contract the chained slices depend on; splitting the contract across PRs would force later PRs to import from a non-existent module)
```

## Work Units

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|----------------------|-----------------|-------------------|
| W1 | Contract module + contract tests + OpenSpec change + doc update | `cd backend && python3 -m pytest tests/test_correlation_propagation_contract.py -v` | read `docs/correlation-topology-guide.md` "Locked propagation decisions" section | revert `backend/services/correlation_propagation_contract.py`, `backend/tests/test_correlation_propagation_contract.py`, `docs/correlation-topology-guide.md`, `openspec/changes/feat-correlation-propagation-semantics/` |
| W2 | Documentation reconciliation for the #539 contract (T1) | docs-only — no runtime test | read `docs/correlation-topology-guide.md` "Reconciled connectivity contract" section | revert `docs/correlation-topology-guide.md` and `openspec/changes/feat-correlation-propagation-semantics/` |

## Phase 1: Pre-flight (PR1)

- [x] 1.1 Confirm 4 decisions are approved by the maintainer (recorded in the proposal's "The four locked decisions" table)
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

## Phase 3: Documentation reconciliation (T1)

Documentation and spec only — no runtime file, relationship whitelist, permission enum, or unrelated OpenSpec change is touched.

- [x] 3.1 Update `docs/correlation-topology-guide.md` locked decisions: decision #1 records the separate `WARNING` `PROPAGATED` Event with the ROOT severity unchanged and modern/legacy alignment; decision #3 records `CRITICAL`/`OPEN`, the endpoint-A host, both endpoints affected, `root_cause_ci_id = PhysicalLink.id`, and the pruner-limited recovery (PR2c2 extends the existing pruner so it closes an OPEN, unacknowledged `physical_link_down` Event once its age exceeds `EVENT_PRUNE_STALE_AFTER_SECONDS`, existing default 3600 seconds); decision #4 records that the `all_propagate` default applies when the rollout slice is enabled
- [x] 3.2 Add the "Reconciled connectivity contract (issue #539)" section to `docs/correlation-topology-guide.md`: the canonical two inbound edges `(endpoint_a:CI)-[:CONNECTED_VIA]->(pl:PhysicalLink)` and `(endpoint_b:CI)-[:CONNECTED_VIA]->(pl)` (no `PhysicalLink → CI` edge), the idempotent `backend/migrations/011_*.cypher` backfill, the atomic deletion repair, the preserved pre-#539 `/api/nodes/{id}/usage` count (every relationship incident to the CI keeps its prior contribution; only the newly introduced CI→PhysicalLink `CONNECTED_VIA` edges are excluded), and the mandatory `:PhysicalLink` intermediate in every correlation traversal
- [x] 3.3 Update the "Decision record (issue #539)" section: connectivity ownership, the reconciled default-off rollout flag, and the unchanged whitelist / depth-3 / permission constraints
- [x] 3.4 Update `openspec/changes/feat-correlation-propagation-semantics/proposal.md` with the reconciled runtime contract and the PR2a1 → PR2c2 chain
- [x] 3.5 Update `openspec/changes/feat-correlation-propagation-semantics/specs/cmdb-correlation-propagation/spec.md`: amend REQ-CORR-PROP-1 and REQ-CORR-PROP-3, add REQ-CORR-PROP-9 (canonical two-inbound-edge connectivity and the preserved pre-#539 usage count), REQ-CORR-PROP-10 (`:PhysicalLink` intermediate, matched as endpoint → link ← endpoint), REQ-CORR-PROP-11 (DOWN event host and the PR2c2 pruner extension), REQ-CORR-PROP-12 (unchanged constraints), REQ-CORR-PROP-13 (default-off rollout flag)
- [x] 3.6 Update this task checklist to the reconciled slice plan (PR2a1 / PR2a2 / PR2b1 / PR2b2 / PR2c1 / PR2c2 / PR3 / PR4)
- [x] 3.7 VERIFY: no runtime file, relationship whitelist, permission enum, or unrelated OpenSpec change was modified
- [x] 3.8 Correct the T1 documentation against the maintainer's latest decisions: the canonical shape is two inbound CI→PhysicalLink edges (the traversal reads endpoint → link ← endpoint), the usage endpoint preserves the pre-#539 count of every incident relationship and excludes only the new CI→PhysicalLink `CONNECTED_VIA` edges, and the Event-pruner extension (PR2c2 closes an OPEN, unacknowledged `physical_link_down` Event after `EVENT_PRUNE_STALE_AFTER_SECONDS`, existing default 3600 seconds) replaces the claim that the unmodified pruner already closes OPEN `physical_link_down` Events
- [x] 3.9 VERIFY: no remaining "CI↔CI-only" usage claim, no `PhysicalLink → CI` canonical edge, and no claim that the unmodified pruner closes OPEN `physical_link_down` Events in the guide, proposal, tasks, or spec

## Phase 4: PR2a1 — canonical PhysicalLink connectivity (S1, S8)

Implements REQ-CORR-PROP-9. Out of scope for PR1 and for the T1 documentation reconciliation.

- [x] 4.1 RED test in `backend/tests/test_physical_link_repo.py`: `PhysicalLinkRepo.create()` writes the two inbound edges `(endpoint_a:CI)-[:CONNECTED_VIA]->(pl)` and `(endpoint_b:CI)-[:CONNECTED_VIA]->(pl)`, and writes no `(:PhysicalLink)-[:CONNECTED_VIA]->(:CI)` edge
- [x] 4.2 RED test: `backend/migrations/011_*.cypher` backfills both inbound `CONNECTED_VIA` edges from the stored `pl.endpoints`
- [x] 4.3 RED test: applying the backfill twice creates no duplicate edges and no duplicate `:PhysicalLink` nodes (idempotent)
- [x] 4.4 RED test in `backend/tests/test_topology_repo_*`: deleting an endpoint CI removes the affected PhysicalLink and its edges atomically, with no dangling endpoint reference
- [x] 4.5 RED test in `backend/tests/test_node_service.py` and `backend/tests/test_routers_nodes.py`: `GET /api/nodes/{id}/usage` preserves the pre-#539 count when `CONNECTED_VIA` edges to PhysicalLinks exist — every relationship incident to the CI keeps its prior contribution and only the new CI→PhysicalLink `CONNECTED_VIA` edges are excluded
- [x] 4.6 Implement: `PhysicalLinkRepo.create()` writes the node and both inbound `CONNECTED_VIA` edges in the same write
- [x] 4.7 Implement: `backend/migrations/011_*.cypher` idempotent backfill
- [x] 4.8 Implement: CI deletion removes the affected PhysicalLink and its edges
- [x] 4.9 Implement: node usage keeps every pre-existing incident-relationship contribution and excludes only the newly introduced CI→PhysicalLink `CONNECTED_VIA` edges
- [x] 4.10 GREEN: focused tests; full backend suite green; PR1 contract tests still green

## Phase 5: PR2a2 — status-gated traversal with the `:PhysicalLink` intermediate (S1, S2, S8)

Implements REQ-CORR-PROP-2 and REQ-CORR-PROP-10. Out of scope for PR1 and for the T1 documentation reconciliation.

- [ ] 5.1 RED test in `backend/tests/test_event_correlation.py`: `find_open_parent_event` walks endpoint CI → PhysicalLink ← peer CI when the intermediate PhysicalLink has `status = UP` and finds the parent's event
- [ ] 5.2 RED test: same setup with `status = DOWN` returns None
- [ ] 5.3 RED test: same setup with `status = PLANNED` returns None
- [ ] 5.4 RED test: a dormant CI→CI `CONNECTED_VIA` seed edge (no `:PhysicalLink` intermediate) is not traversed
- [ ] 5.5 RED test in `backend/tests/test_topology_repo_open_parent.py`: `build_open_parent_index` extends correctly with the `:PhysicalLink` intermediate
- [ ] 5.6 RED test: `re_query_per_correlation` — simulate a status change between two correlation queries, assert the second query sees the new value
- [ ] 5.7 RED test: cycle handling — `:CONNECTED_VIA` + cycle in the CI graph does not infinite loop
- [ ] 5.8 Implement: extend the four Cypher traversal functions in `backend/repositories/topology_repo.py` with the `:PhysicalLink` intermediate matched as `(ci)-[:CONNECTED_VIA]->(pl)<-[:CONNECTED_VIA]-(peer)` and the status gate
- [ ] 5.9 Implement: carry link id, link status, and degraded severity through the correlation caches
- [ ] 5.10 GREEN: focused tests; full backend suite green; PR1 contract tests still green

## Phase 6: PR2b1 — modern SNMP separate WARNING PROPAGATED Events (S2, S8)

Implements REQ-CORR-PROP-1 for the modern path. Out of scope for PR1 and for the T1 documentation reconciliation.

- [ ] 6.1 RED test in `backend/tests/test_snmp_worker_correlation.py`: end-to-end via `_resolve_correlation` — CI-A → PhysicalLink ← CI-B → CI-C (event); CI-A's polled metric becomes PROPAGATED with `root_cause_ci_id` = CI-C
- [ ] 6.2 RED test: same chain with the PhysicalLink UNKNOWN — a **separate** `PROPAGATED` Event is created at `WARNING` severity
- [ ] 6.3 RED test: same chain with the PhysicalLink UNKNOWN — the ROOT Event keeps its original severity
- [ ] 6.4 RED test: the propagated Event keeps `root_cause_ci_id` = the ROOT CI and stays linked to the affected CI
- [ ] 6.5 RED test: idempotency — repeated cycles do not create a second `PROPAGATED` Event for the same failure
- [ ] 6.6 RED test: the same chain with the PhysicalLink DOWN — CI-A stays ROOT
- [ ] 6.7 Implement: write the separate `PROPAGATED` Event at `WARNING` for the UNKNOWN path
- [ ] 6.8 Implement: idempotency guards on the propagated-event write
- [ ] 6.9 GREEN: focused tests; full backend suite green; PR1 contract tests still green

## Phase 7: PR2b2 — legacy path and leased writer alignment (S2, S8)

Completes REQ-CORR-PROP-1 across both engines. Out of scope for PR1 and for the T1 documentation reconciliation.

- [ ] 7.1 RED test in `backend/tests/test_snmp_service_*`: the legacy path emits a `PROPAGATED` Event at `WARNING` severity for an UNKNOWN link
- [ ] 7.2 RED test: the legacy path does not erase the `WARNING` severity of the propagated Event
- [ ] 7.3 RED test: the legacy path does not double-propagate a failure the modern path already propagated
- [ ] 7.4 RED test: the leased writer applies the same propagation semantics as the modern path
- [ ] 7.5 Implement: align `backend/services/snmp_service.py` with the modern propagation semantics
- [ ] 7.6 Implement: align the leased writer
- [ ] 7.7 GREEN: focused tests; full backend suite green; PR1 contract tests still green

## Phase 8: PR2c1 — atomic DOWN transition and descendant Event write (S3, S4, S8)

Implements REQ-CORR-PROP-3 and the host half of REQ-CORR-PROP-11. Out of scope for PR1 and for the T1 documentation reconciliation.

- [ ] 8.1 RED test: an observed UP→DOWN transition creates exactly one `physical_link_down` Event with `severity = CRITICAL` and `status = OPEN`
- [ ] 8.2 RED test: the Event's `root_cause_ci_id` = `PhysicalLink.id` (not a CI id)
- [ ] 8.3 RED test: the Event's `affected_ci_ids` contains both endpoints
- [ ] 8.4 RED test: the Event is hosted by endpoint A only — `ci_id = endpoint_a` and a single `HAS_EVENT` relationship targeting endpoint A
- [ ] 8.5 RED test: concurrent bridge runs create at most one Event for the same transition
- [ ] 8.6 Implement: atomic UP→DOWN transition plus the descendant Event write
- [ ] 8.7 GREEN: focused tests; full backend suite green; PR1 contract tests still green

## Phase 9: PR2c2 — bridge wiring, event-pruner extension, rollout flag (S3, S4, S5, S8)

Completes REQ-CORR-PROP-11 and REQ-CORR-PROP-13. Out of scope for PR1 and for the T1 documentation reconciliation.

- [ ] 9.1 RED test in `backend/tests/test_physical_link_bridge.py`: the bridge creates the `physical_link_down` Event on the observed UP→DOWN transition
- [ ] 9.2 RED test: a later `UP` does not automatically recover, close, or pre-emptively close the `physical_link_down` Event
- [ ] 9.3 RED test in `backend/tests/test_event_service_smoke.py` (or the matching pruner test module): the **unmodified** event-pruner does not close an OPEN `physical_link_down` Event — it closes `RECOVERED` events only — so this RED drives the pruner extension
- [ ] 9.4 RED test: the extended pruner closes an OPEN, unacknowledged `physical_link_down` Event whose age exceeds `EVENT_PRUNE_STALE_AFTER_SECONDS` (existing default 3600 seconds), recording `status = CLOSED`, `closed_at`, and `closed_by = system-prune` (or the configured pruner actor)
- [ ] 9.5 RED test: the extended pruner leaves an acknowledged `physical_link_down` Event OPEN, and leaves an OPEN, unacknowledged Event younger than the threshold OPEN
- [ ] 9.6 RED test: the operator event feed shows the `physical_link_down` Event once, with both endpoints listed as affected
- [ ] 9.7 Implement: wire the DOWN Event into `backend/polling/physical_link_bridge.py`
- [ ] 9.8 Implement: extend the existing event-pruner so it closes an OPEN, unacknowledged `physical_link_down` Event older than `EVENT_PRUNE_STALE_AFTER_SECONDS` (existing default 3600 seconds), recording `status = CLOSED`, `closed_at`, and `closed_by`
- [ ] 9.9 Implement: wire `FEATURE_CMDB_CORRELATION_PHYSICAL_LINK_PROPAGATION_ENABLED` default off; flip to `true` only after the whole chain lands and CI is green
- [ ] 9.10 GREEN: focused tests; full backend suite green; PR1 contract tests still green

## Phase 10: PR3 (deferred — chained follow-up)

PR3 implements REQ-CORR-PROP-4 (the MANAGES / USES / PROVIDES default-propagate decision). Out of scope for PR1.

- [ ] 10.1 RED test in `backend/tests/test_event_correlation.py`: `find_open_parent_event` walks `:MANAGES` and finds the parent's event
- [ ] 10.2 RED test: same setup for `:USES`
- [ ] 10.3 RED test: same setup for `:PROVIDES`
- [ ] 10.4 RED test: `build_open_parent_index` and `build_cycle_parent_index` extend correctly with the 3 new types
- [ ] 10.5 RED test: depth-3 boundary still holds with the 3 new types in the traversal
- [ ] 10.6 Implement: extend the four Cypher traversal functions to include `MANAGES | USES | PROVIDES` (no per-CI gate, no per-metric gate — the locked decision is `all_propagate`; the slice's own rollout flag still applies)
- [ ] 10.7 Wire `FEATURE_CMDB_CORRELATION_MANAGES_USES_PROVIDES_ENABLED` default off; flip to `true` after PR3 lands
- [ ] 10.8 GREEN tests; full backend suite green; PR1 + PR2 contract tests still green

## Phase 11: PR4 (deferred — chained follow-up)

PR4 implements the `:CONNECTS_TO` `medium` predicate. Out of scope for PR1.

- [ ] 11.1 RED test in `backend/tests/test_event_correlation.py`: `:CONNECTS_TO` with `medium = "vpn"` does NOT propagate
- [ ] 11.2 RED test: same setup for `medium = "sd_wan"`
- [ ] 11.3 RED test: same setup for `medium = "satellite"`
- [ ] 11.4 RED test: `:CONNECTS_TO` with `medium = "ethernet"` DOES propagate
- [ ] 11.5 RED test: `:CONNECTS_TO` with `medium = null` DOES propagate (pre-#539 behavior preserved for unset values)
- [ ] 11.6 Implement: add `medium` predicate to the four Cypher traversal functions
- [ ] 11.7 Wire `FEATURE_CMDB_CORRELATION_CONNECTS_TO_MEDIUM_FILTER_ENABLED` default off; flip to `true` after PR4 lands
- [ ] 11.8 GREEN tests; full backend suite green; PR1 + PR2 + PR3 contract tests still green

## Critical sequencing

- PR2a1 depends on PR1 (the contract) and on the PhysicalLink node shipped by `openspec/changes/feat-cmdb-physical-links-runtime/`; PR2a2 depends on PR2a1 because the traversal walks the edges PR2a1 writes
- PR2b1 depends on PR2a2 (the cache must carry the degraded severity and the link metadata); PR2b2 depends on PR2b1 (the legacy path mirrors the modern semantics)
- PR2c1 depends on the slice 4 / #443 polling bridge that observes the status change; PR2c2 depends on PR2c1 (it wires the Event the transition writes) and extends the existing event-pruner so it closes a stale OPEN, unacknowledged `physical_link_down` Event after `EVENT_PRUNE_STALE_AFTER_SECONDS` (existing default 3600 seconds)
- PR3 depends on PR1 (PR3 imports the contract; without the contract, PR3 has no source of truth for the M/U/P decision)
- PR4 depends on PR1 (PR4 imports the feature flag name; the `medium` predicate is a separate decision but the flag convention is set in PR1)
- PR3 and PR4 can ship independently of the PR2 chain
- The whole PR2 chain ships behind `FEATURE_CMDB_CORRELATION_PHYSICAL_LINK_PROPAGATION_ENABLED`, default off; the flag is flipped only after PR2c2 lands and CI is green
- Every slice honors the unchanged cross-chain constraints: `backend/services/relationship_types.py:7-13` stays at its 6 CI relationship types, the traversal depth stays 3, no new `UserPermission` enum value is introduced, and ROOT vs PROPAGATED semantics are unchanged

## Cross-references

- Issue: #539
- Design doc: `docs/correlation-topology-guide.md`
- Contract: `backend/services/correlation_propagation_contract.py`
- Contract tests: `backend/tests/test_correlation_propagation_contract.py`
- Sibling OpenSpec change: `openspec/changes/feat-cmdb-physical-links-runtime/` (provides `:PhysicalLink` and `:CONNECTED_VIA`)
- Source proposal: `openspec/changes/feat-correlation-propagation-semantics/proposal.md`
- Source spec: `openspec/changes/feat-correlation-propagation-semantics/specs/cmdb-correlation-propagation/spec.md`
