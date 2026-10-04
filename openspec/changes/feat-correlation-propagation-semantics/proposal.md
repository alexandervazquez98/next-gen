# Proposal: feat(correlation) unified propagation semantics across all CI relationships (#539)

## Problem

The event correlation traversal in `backend/repositories/topology_repo.py` walks only 3 of 6 supported CI relationship types:

```cypher
MATCH (ci)-[r:DEPENDS_ON|HOSTED_ON|CONNECTS_TO*1..3]->(parent:CI)
```

`backend/services/relationship_types.py:7-13` declares **6** supported CI relationship types — `CONNECTS_TO`, `DEPENDS_ON`, `HOSTED_ON`, `MANAGES`, `USES`, `PROVIDES` — but the four traversal functions (`find_open_parent_event`, `build_open_parent_index`, `get_topology_relations`, `build_cycle_parent_index`) only traverse 3.

Four categories of gap:

1. **PhysicalLink (`:CONNECTED_VIA`)** — CI → PhysicalLink → CI, not traversed at all. A CI on one side of a fiber link does not pick up an event on the other side.
2. **MANAGES / USES / PROVIDES** — declared in `relationship_types.py` but never traversed. Labels exist in the graph, no event propagation.
3. **`:CONNECTS_TO` with `medium`** — `vpn | sd_wan | satellite` tunnels propagate the same as a direct Ethernet cable. The design doc (`docs/correlation-topology-guide.md:43-47`) already flags this as unsafe, but the implementation has no `medium` filter.
4. **Legacy `CONNECTED_TO`** — already normalized to `CONNECTS_TO` via `LEGACY_RELATIONSHIP_TYPE_MAP`. No change.

This change ships the design decisions that unblock the three implementation PRs (PR2 / PR3 / PR4) needed to close the gap. No behavior changes in this PR1.

## Scope

### Owns

- Four locked propagation decisions (UNKNOWN semantics, freshness, DOWN behavior, M/U/P default) recorded in `docs/correlation-topology-guide.md`.
- A new runtime contract module `backend/services/correlation_propagation_contract.py` that PR2/3/4 import from.
- A new parametrized test file `backend/tests/test_correlation_propagation_contract.py` that pins the contract.
- This OpenSpec change proposal that codifies the contract as spec deltas.

### Does not own (deferred to PR2 / PR3 / PR4)

- Modifying the four Cypher traversal functions in `backend/repositories/topology_repo.py` (PR2 / PR3 / PR4).
- Modifying `_resolve_correlation` in `backend/engines/snmp_worker.py:285-316` (PR2 / PR3).
- Modifying the older correlation path in `backend/services/snmp_service.py:595-665` (PR2 / PR3).
- Implementing the `medium` predicate on `:CONNECTS_TO` (PR4).
- Implementing the severity-degradation mapping for UNKNOWN propagation (PR2).
- Implementing the sub-query for `re_query_per_correlation` (PR2).
- Implementing the `generate_descendant_event` logic on UP → DOWN transitions (PR2, depends on slice 4 / #443 polling).
- Changes to `MetricDef` (no new `relationship_propagates` flag — locked decision #4 is `all_propagate`).

## Approach

Four chained PRs:

```
PR1 (this PR) — design doc + contract + OpenSpec + contract tests, no behavior change
PR2 — :CONNECTED_VIA traversal with status gate (locked decisions #1, #2, #3)
PR3 — :MANAGES / :USES / :PROVIDES traversal (locked decision #4)
PR4 — :CONNECTS_TO medium predicate (separate decision, follows PR3)
```

Each implementation PR imports `services.correlation_propagation_contract` and adds tests that verify the runtime behavior matches the contract.

## Requirements

### From #539

1. The four locked decisions are recorded in `docs/correlation-topology-guide.md` (the "Locked propagation decisions" section).
2. The four decisions are encoded as constants in `services/correlation_propagation_contract`.
3. A parametrized test file pins the contract values.
4. The four chained PRs can implement the contract without further design decisions.
5. `services/relationship_types.py` is NOT modified in PR1 (the 6 supported CI relationship types stay unchanged).
6. No behavior change in PR1.

## The four locked decisions (cross-referenced from `docs/correlation-topology-guide.md`)

| # | Decision | Locked value | Affects |
|---|---|---|---|
| 1 | `PhysicalLink.status = UNKNOWN` propagation | `degrade_severity_and_propagate` | PR2 (severity mapping) |
| 2 | Status freshness model | `re_query_per_correlation` | PR2 (Cypher sub-query) |
| 3 | Behavior when PhysicalLink flips UP → DOWN | `generate_descendant_event` | PR2 (event creation on transition) + slice 4 / #443 (polling integration) |
| 4 | `MANAGES` / `USES` / `PROVIDES` default propagation | `all_propagate` | PR3 (traversal extension) |

## Hard constraints

- `services/relationship_types.py:7-13` is NOT modified in PR1.
- Default traversal depth stays at 3 (max 3); no change.
- No new `UserPermission` enum values.
- ROOT vs PROPAGATED semantics unchanged.
- No behavior change in PR1.
- The contract module has no I/O, no Neo4j session, no FastAPI dependency (importable from anywhere).
- The contract module is a single source of truth: PR2 / PR3 / PR4 must NOT hardcode the decision values.

## Non-goals

- Backporting the contract to pre-#539 traversals.
- Adding a `relationship_propagates` flag to `MetricDef` (locked decision #4 is `all_propagate`; revisit only if a real deployment surfaces a problem).
- Modifying the cycle-detection behavior.
- Modifying the depth-3 default.
- Adding a per-CI propagation field (locked decision #4 is `all_propagate`).
- Modifying `docs/correlation-topology-guide.md` beyond the new "Locked propagation decisions" section and the filled-in "Decision record" section.

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

- **PR2** — `:CONNECTED_VIA` traversal + status gate + severity degradation + re-query sub-query + DOWN event generation. ~600-800 LoC.
- **PR3** — `:MANAGES | :USES | :PROVIDES` added to the four traversals. ~200-400 LoC.
- **PR4** — `:CONNECTS_TO medium` predicate (excludes `vpn | sd_wan | satellite`). ~200-300 LoC.

## Open decisions for the maintainer

_All four decisions are now locked. No open items remain for PR1._

## Cross-references

- Issue: #539
- Design doc: `docs/correlation-topology-guide.md`
- Contract: `backend/services/correlation_propagation_contract.py`
- Contract tests: `backend/tests/test_correlation_propagation_contract.py`
- Sibling OpenSpec changes:
  - `openspec/changes/feat-cmdb-physical-links-runtime/` (slice 1-3 of PhysicalLink, ships the `:CONNECTED_VIA` relationship that PR2 walks)
  - `openspec/changes/cmdb-graph-lod-runtime/` (unrelated, but touches the same traversal layer)
