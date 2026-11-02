# Proposal: feat(correlation) unified propagation semantics across all CI relationships (#539)

## Problem

The event correlation traversal in `backend/repositories/topology_repo.py` walks only 3 of 6 supported CI relationship types:

```cypher
MATCH (ci)-[r:DEPENDS_ON|HOSTED_ON|CONNECTS_TO*1..3]->(parent:CI)
```

`backend/services/relationship_types.py:7-13` declares **6** supported CI relationship types — `CONNECTS_TO`, `DEPENDS_ON`, `HOSTED_ON`, `MANAGES`, `USES`, `PROVIDES` — but the four traversal functions (`find_open_parent_event`, `build_open_parent_index`, `get_topology_relations`, `build_cycle_parent_index`) only traverse 3.

Four categories of gap:

1. **PhysicalLink (`:CONNECTED_VIA`)** — endpoint CI → PhysicalLink ← peer CI (two inbound edges), not traversed at all. A CI on one side of a fiber link does not pick up an event on the other side.
2. **MANAGES / USES / PROVIDES** — declared in `relationship_types.py` but never traversed. Labels exist in the graph, no event propagation.
3. **`:CONNECTS_TO` with `medium`** — `vpn | sd_wan | satellite` tunnels propagate the same as a direct Ethernet cable. The design doc (`docs/correlation-topology-guide.md:43-47`) already flags this as unsafe, but the implementation has no `medium` filter.
4. **Legacy `CONNECTED_TO`** — already normalized to `CONNECTS_TO` via `LEGACY_RELATIONSHIP_TYPE_MAP`. No change.

This change ships the design decisions that unblock the three implementation PRs (PR2 / PR3 / PR4) needed to close the gap. No behavior changes in this PR1.

### Gaps found while reconciling the shipped PR1 against the current runtime

The PR1 contract was written against the PR1 document. Reconciling it against the runtime that actually shipped exposed three implementation gaps that the contract did not cover:

1. **PhysicalLink had no edge writer and no backfill.** `PhysicalLinkRepo.create()` writes only a `:PhysicalLink` node with an `endpoints` list — it never writes a `CONNECTED_VIA` edge, and no migration exists to build one for links created before the reconciliation. `docker/neo4j/init.cypher` also seeds dormant CI→CI `CONNECTED_VIA` edges, so a traversal that matches `(:CI)-[:CONNECTED_VIA]->(:CI)` would read those seeds as PhysicalLink hops.
2. **The modern SNMP path and the legacy path disagreed.** `backend/engines/snmp_worker.py` resolves a correlation but only attaches the affected CI to the ROOT event — it creates no `PROPAGATED` child Event. `backend/services/snmp_service.py` does create a `PROPAGATED` child Event. The two engines therefore cannot agree on a degraded severity.
3. **The DOWN transition was detected but not atomic.** `backend/polling/physical_link_bridge.py` observes a status change and persists it with a non-atomic status update; nothing writes a descendant Event for the outage.

The reconciled contract below closes those three gaps and splits PR2 into six reviewable slices (PR2a1 / PR2a2 / PR2b1 / PR2b2 / PR2c1 / PR2c2).

## Scope

### Owns

- Four locked propagation decisions (UNKNOWN semantics, freshness, DOWN behavior, M/U/P default) recorded in `docs/correlation-topology-guide.md`.
- A new runtime contract module `backend/services/correlation_propagation_contract.py` that PR2/3/4 import from.
- A new parametrized test file `backend/tests/test_correlation_propagation_contract.py` that pins the contract.
- This OpenSpec change proposal that codifies the contract as spec deltas.

### Does not own (deferred to the reconciled chain)

- Modifying the four Cypher traversal functions in `backend/repositories/topology_repo.py` (PR2a2).
- Writing the canonical `CONNECTED_VIA` edges in `backend/repositories/physical_link_repo.py` (PR2a1).
- Adding `backend/migrations/011_*.cypher` (the idempotent PhysicalLink backfill) (PR2a1).
- Repairing CI deletion so the affected PhysicalLink and its edges disappear atomically (PR2a1).
- Changing the public usage semantics of `GET /api/nodes/{id}/usage` — the slice preserves the pre-#539 count (PR2a1).
- Extending the existing event-pruner so it closes an OPEN, unacknowledged `physical_link_down` Event once its age exceeds `EVENT_PRUNE_STALE_AFTER_SECONDS` (existing default 3600 seconds) (PR2c2).
- Modifying `_resolve_correlation` in `backend/engines/snmp_worker.py:285-316` (PR2b1).
- Modifying the older correlation path in `backend/services/snmp_service.py:595-665` (PR2b2).
- Implementing the `medium` predicate on `:CONNECTS_TO` (PR4).
- Implementing the severity-degradation mapping for UNKNOWN propagation (PR2a2 / PR2b1).
- Implementing the sub-query for `re_query_per_correlation` (PR2a2).
- Implementing the `physical_link_down` descendant-event write on UP → DOWN transitions (PR2c1) and wiring it into the polling bridge (PR2c2).
- Changes to `MetricDef` (no new `relationship_propagates` flag — locked decision #4 is `all_propagate`).

## Approach

The reconciled chain:

```
PR1 (this PR) — design doc + contract + OpenSpec + contract tests, no behavior change
PR2a1 — canonical inbound CI→PhysicalLink CONNECTED_VIA edges, idempotent 011 backfill,
        deletion repair, preserved pre-#539 /api/nodes/{id}/usage count
PR2a2 — :CONNECTED_VIA traversal with the :PhysicalLink intermediate and status gate,
        link/severity metadata carried through the correlation caches
PR2b1 — modern SNMP path: separate WARNING PROPAGATED Events for UNKNOWN links,
        with idempotency guards
PR2b2 — legacy path and leased writer aligned to the modern propagation semantics
PR2c1 — atomic PhysicalLink UP→DOWN transition and physical_link_down Event write
PR2c2 — DOWN Event wired into the polling bridge, the event-pruner extension for stale
        OPEN physical_link_down Events, and the rollout flag
PR3 — :MANAGES / :USES / :PROVIDES traversal (locked decision #4)
PR4 — :CONNECTS_TO medium predicate (separate decision, follows PR3)
```

Each implementation PR imports `services.correlation_propagation_contract` and adds tests that verify the runtime behavior matches the contract.

## Reconciled runtime contract (issue #539)

The four locked decisions below cover propagation policy. The reconciled contract also fixes the connectivity the propagation walks and the exact shape of the events it writes.

### Canonical PhysicalLink connectivity

- A PhysicalLink is expressed only as **two inbound edges** from its endpoint CIs: `(endpoint_a:CI)-[:CONNECTED_VIA]->(pl:PhysicalLink)` and `(endpoint_b:CI)-[:CONNECTED_VIA]->(pl)`. There is no `PhysicalLink → CI` edge — the link is the target of both endpoint edges, never the source.
- `PhysicalLinkRepo.create()` creates the node and both inbound `CONNECTED_VIA` edges in the same write (PR2a1).
- `backend/migrations/011_*.cypher` backfills the two inbound edges for every existing `:PhysicalLink` from its `endpoints` list and is idempotent on re-run (PR2a1).
- Deleting an endpoint CI removes the affected PhysicalLink and its `CONNECTED_VIA` edges atomically — no orphan link, no dangling endpoint reference, no half-connected link (PR2a1).
- `GET /api/nodes/{id}/usage` preserves its **pre-#539 count**: every relationship incident to the CI keeps its prior contribution (all pre-existing relationship types and targets, including non-CI targets), and only the newly introduced `CONNECTED_VIA` edges whose other endpoint is a `:PhysicalLink` are excluded. The count is not narrowed to CI↔CI relationships (PR2a1).

### Correlation traversal requires a `:PhysicalLink` intermediate

- Correlation traversals match `(ci)-[:CONNECTED_VIA]->(pl:PhysicalLink)<-[:CONNECTED_VIA]-(peer:CI)`; the intermediate `:PhysicalLink` node is mandatory (PR2a2). The traversal reads the two inbound edges as one hop, endpoint → link ← endpoint.
- A traversal that matches `(:CI)-[:CONNECTED_VIA]->(:CI)` directly is forbidden, so the dormant CI→CI `CONNECTED_VIA` seed edges in `docker/neo4j/init.cypher` are never misread as PhysicalLink hops (PR2a2).

### UNKNOWN severity degradation

- Propagation across an `UNKNOWN` PhysicalLink creates a **separate `PROPAGATED` Event at `WARNING` severity**; the **ROOT Event keeps its original severity** (PR2b1).
- The propagated Event keeps `root_cause_ci_id` pointing at the ROOT CI, and stays linked to the affected CI (PR2b1).
- The modern SNMP path and the legacy path apply the same semantics, so neither engine can erase the `WARNING` severity nor double-propagate the same failure (PR2b1 / PR2b2).

### `physical_link_down` descendant Event

- One `physical_link_down` Event per observed `UP → DOWN` transition, with `severity = CRITICAL` and `status = OPEN` (PR2c1).
- `root_cause_ci_id` is the **PhysicalLink id**; `affected_ci_ids` contains **both endpoints** (PR2c1).
- The Event is hosted by **endpoint A** (`ci_id = endpoint_a`; the `HAS_EVENT` relationship targets endpoint A only), so the operator feed shows one row while endpoint B remains affected (PR2c1).
- Concurrent bridge runs create at most one Event for the same transition (PR2c1).
- The Event is **pruner-limited**: a later `UP` does not automatically recover, close, or pre-emptively close it (PR2c2).
- The existing event-pruner closes `RECOVERED` events only, so it does not close an OPEN `physical_link_down` Event as it stands today. **PR2c2 extends the existing pruner** so it closes an OPEN, unacknowledged `physical_link_down` Event once its age exceeds `EVENT_PRUNE_STALE_AFTER_SECONDS` (existing default 3600 seconds), recording `status = CLOSED`, `closed_at`, and `closed_by = system-prune` (or the configured pruner actor) (PR2c2).

### Rollout and unchanged constraints

- The PhysicalLink chain ships behind `FEATURE_CMDB_CORRELATION_PHYSICAL_LINK_PROPAGATION_ENABLED`, **default off**; it is flipped on only after the whole reconciled chain lands and CI is green (PR2c2).
- `backend/services/relationship_types.py:7-13` (`SUPPORTED_CI_RELATIONSHIP_TYPES`) stays at its 6 CI relationship types — only the traversal changes.
- Default and maximum traversal depth stays 3.
- No new `UserPermission` enum values.
- ROOT vs PROPAGATED semantics are unchanged; only the set of traversed relationships and the gates change.

## Requirements

### From #539

1. The four locked decisions are recorded in `docs/correlation-topology-guide.md` (the "Locked propagation decisions" section).
2. The four decisions are encoded as constants in `services/correlation_propagation_contract`.
3. A parametrized test file pins the contract values.
4. The chained implementation PRs can implement the contract without further design decisions.
5. `services/relationship_types.py` is NOT modified in PR1 (the 6 supported CI relationship types stay unchanged).
6. No behavior change in PR1.

### From the #539 reconciliation

7. The canonical two-inbound-edge CI→PhysicalLink `CONNECTED_VIA` connectivity, the idempotent `011` backfill, the deletion repair, and the preserved pre-#539 `/api/nodes/{id}/usage` count are recorded in `docs/correlation-topology-guide.md` (the "Reconciled connectivity contract" section).
8. Correlation traversals require an intermediate `:PhysicalLink` node so dormant CI→CI `CONNECTED_VIA` seed edges are never read as PhysicalLink hops.
9. An `UNKNOWN` PhysicalLink creates a separate `PROPAGATED` Event at `WARNING` severity while the ROOT Event keeps its severity, and the modern and legacy paths apply the same semantics.
10. A `physical_link_down` Event is `CRITICAL` / `OPEN`, is hosted by endpoint A, affects both endpoints, carries `root_cause_ci_id = PhysicalLink.id`, is never auto-recovered or pre-emptively closed by a later link `UP`, and is closed by the PR2c2 extension of the existing event-pruner once its age exceeds `EVENT_PRUNE_STALE_AFTER_SECONDS` (existing default 3600 seconds).
11. The PhysicalLink chain ships behind a default-off rollout flag, and the relationship whitelist, the depth-3 default, and the permission model stay unchanged.

## The four locked decisions (cross-referenced from `docs/correlation-topology-guide.md`)

| # | Decision | Locked value | Affects |
|---|---|---|---|
| 1 | `PhysicalLink.status = UNKNOWN` propagation | `degrade_severity_and_propagate` | PR2a2 (severity mapping) + PR2b1 / PR2b2 (separate `WARNING` `PROPAGATED` Event) |
| 2 | Status freshness model | `re_query_per_correlation` | PR2a2 (Cypher sub-query) |
| 3 | Behavior when PhysicalLink flips UP → DOWN | `generate_descendant_event` | PR2c1 (event creation on transition) + PR2c2 (polling integration) |
| 4 | `MANAGES` / `USES` / `PROVIDES` default propagation | `all_propagate` | PR3 (traversal extension) |

## Hard constraints

- `services/relationship_types.py:7-13` is NOT modified in PR1, and stays at its 6 CI relationship types across the whole chain — only the traversal changes.
- Default traversal depth stays at 3 (max 3); no change.
- No new `UserPermission` enum values.
- ROOT vs PROPAGATED semantics unchanged.
- No behavior change in PR1.
- The PhysicalLink chain ships behind `FEATURE_CMDB_CORRELATION_PHYSICAL_LINK_PROPAGATION_ENABLED`, default off.
- The contract module has no I/O, no Neo4j session, no FastAPI dependency (importable from anywhere).
- The contract module is a single source of truth: PR2 / PR3 / PR4 must NOT hardcode the decision values.

## Non-goals

- Backporting the contract to pre-#539 traversals.
- Adding a `relationship_propagates` flag to `MetricDef` (locked decision #4 is `all_propagate`; revisit only if a real deployment surfaces a problem).
- Modifying the cycle-detection behavior.
- Modifying the depth-3 default.
- Adding a per-CI propagation field (locked decision #4 is `all_propagate`).
- Modifying `docs/correlation-topology-guide.md` beyond the "Locked propagation decisions" section, the "Reconciled connectivity contract" section, and the filled-in "Decision record" section.

## Affected files (this PR1)

### Created

- `backend/services/correlation_propagation_contract.py` — runtime contract (~250 LoC).
- `backend/tests/test_correlation_propagation_contract.py` — parametrized contract tests (~270 LoC, 33 tests).
- `openspec/changes/feat-correlation-propagation-semantics/{proposal.md, tasks.md, specs/cmdb-correlation-propagation/spec.md}` — this OpenSpec change.

### Modified

- `docs/correlation-topology-guide.md` — adds the "Locked propagation decisions" section; replaces the "Decision record required before implementation" placeholder with a filled-in "Decision record (issue #539)" section.
- `CHANGELOG.md` — `[Unreleased]` entry.

## Estimated footprint (this PR1)

| Area | LOC estimate |
|---|---|
| Contract module | ~250 |
| Contract tests | ~270 (33 tests) |
| OpenSpec change | ~200 |
| Doc updates | ~80 |
| CHANGELOG entry | ~10 |
| **Total** | **~810** |

Single PR, within the 400-line review budget with size exception justified by the cross-cutting nature (4 decisions, 3 chained PRs need this contract as a dependency).

## Future PRs (out of scope for PR1)

- **PR2a1** — canonical inbound CI→PhysicalLink `CONNECTED_VIA` edges + idempotent `011` backfill + deletion repair + preserved pre-#539 `/api/nodes/{id}/usage` count. ~400-600 LoC.
- **PR2a2** — `:CONNECTED_VIA` traversal with the `:PhysicalLink` intermediate and status gate + re-query sub-query + severity/link metadata through the correlation caches. ~400-600 LoC.
- **PR2b1** — modern SNMP path: separate `WARNING` `PROPAGATED` Events for `UNKNOWN` links + idempotency guards. ~300-500 LoC.
- **PR2b2** — legacy path and leased writer aligned to the modern propagation semantics. ~200-400 LoC.
- **PR2c1** — atomic `UP → DOWN` transition + `physical_link_down` Event write. ~300-500 LoC.
- **PR2c2** — DOWN Event wired into the polling bridge + event-pruner extension for stale OPEN `physical_link_down` Events + rollout flag. ~150-250 LoC.
- **PR3** — `:MANAGES | :USES | :PROVIDES` added to the four traversals. ~200-400 LoC.
- **PR4** — `:CONNECTS_TO medium` predicate (excludes `vpn | sd_wan | satellite`). ~200-300 LoC.

## Open decisions for the maintainer

_All four propagation decisions are locked and the reconciled connectivity contract is recorded. No open items remain._

## Cross-references

- Issue: #539
- Design doc: `docs/correlation-topology-guide.md`
- Contract: `backend/services/correlation_propagation_contract.py`
- Contract tests: `backend/tests/test_correlation_propagation_contract.py`
- Sibling OpenSpec changes:
  - `openspec/changes/feat-cmdb-physical-links-runtime/` (slice 1-3 of PhysicalLink, ships the `:PhysicalLink` node and the `:CONNECTED_VIA` relationship that PR2a1 writes and PR2a2 walks)
  - `openspec/changes/cmdb-graph-lod-runtime/` (unrelated, but touches the same traversal layer)
