# Spec delta: cmdb-graph-consumer-migration

## ADDED Requirements

### REQ-MIGRATION-1: Caller inventory

The system MUST have a documented inventory of every consumer of `/graph/full` and `/api/graph/full` in `docs/refactoring/cmdb-graph-consumer-inventory.md`.

#### Scenario: inventory complete
- GIVEN the audit PR (#393 PR7) has landed
- WHEN the inventory is reviewed
- THEN every consumer of `/graph/full` (backend) and `/api/graph/full` (frontend) is listed
- AND each entry includes path, current behavior, decision (migrate / except), and reason

### REQ-MIGRATION-2: NetworkVisualizer migration

If the audit (#393 PR7) determines `NetworkVisualizer` is migratable, the system MUST migrate it to use `/graph/overview` and `/graph/detail/{cluster_id}`.

#### Scenario: NetworkVisualizer uses overview on mount
- GIVEN the migration PR (#393 PR8) has landed
- WHEN the operator opens `NetworkVisualizer`
- THEN the initial render uses `/graph/overview` (not `/api/graph/full`)
- AND a regression test asserts no initial `/api/graph/full` call

#### Scenario: NetworkVisualizer detail on click
- GIVEN the migration PR has landed
- WHEN the operator clicks a cluster in `NetworkVisualizer`
- THEN the detail fetch goes through `/graph/detail/{cluster_id}`
- AND the merge renders as a delimited subgraph (mirror of GraphCMDB UX)

### REQ-MIGRATION-3: Excepted consumers preserved

If the audit determines a consumer cannot be migrated, the system MUST preserve `/graph/full` behavior for that consumer with documented limits.

#### Scenario: excepted consumer still works
- GIVEN an excepted consumer (audit decision: keep `/graph/full`)
- WHEN the operator uses that consumer
- THEN the consumer still receives `/graph/full` responses unchanged
- AND `backend/tests/test_graph_full_snapshot.py` continues to enforce byte-equality

### REQ-MIGRATION-4: Polling/cache normalization

Migrated consumers MUST NOT duplicate full-graph pressure through parallel polling.

#### Scenario: deduplicated polling
- GIVEN two consumers that previously polled `/api/graph/full` independently
- WHEN both are migrated to LOD paths
- THEN no consumer reintroduces the same polling pattern via overview polling
- AND a regression test verifies no N>1 parallel `/graph/full` requests within a polling cycle

## MODIFIED Requirements

_None._

## REMOVED Requirements

_None — `/graph/full` is not removed; only consumers are migrated selectively._

## Cross-references

- Source proposal: `openspec/changes/cmdb-graph-lod-runtime/proposal.md`
- Dependent activation: issue #214 (visual editor scaling) — moves to `status:approved` after #393 tracker merges
- Hard preservation: `backend/tests/test_graph_full_snapshot.py` must remain green throughout the migration