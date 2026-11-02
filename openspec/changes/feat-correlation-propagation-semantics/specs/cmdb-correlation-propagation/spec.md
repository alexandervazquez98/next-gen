# Spec delta: cmdb-correlation-propagation

## ADDED Requirements

### REQ-CORR-PROP-1: UNKNOWN status propagation policy

The system MUST treat `PhysicalLink.status = UNKNOWN` as propagation-eligible with severity degradation. When a PhysicalLink is in the `UNKNOWN` state and a propagation-eligible event would cross it, the system MUST create a **separate** `PROPAGATED` Event emitted at `WARNING` severity instead of the parent's severity. The **ROOT Event MUST keep its original severity**. The propagated Event MUST keep `root_cause_ci_id` pointing at the ROOT CI (never at the link), MUST remain linked to the affected CI, and the modern SNMP path and the legacy path MUST apply the same semantics so that neither engine erases the `WARNING` severity nor double-propagates the same failure.

#### Scenario: UNKNOWN link propagates a CRITICAL parent event as WARNING
- GIVEN a `PhysicalLink` with `status = UNKNOWN`
- AND a parent CI on one side of the link has an active `CRITICAL` event
- WHEN a metric on a child CI on the other side of the link is evaluated
- THEN the system records the child CI as affected
- AND a separate `PROPAGATED` Event is emitted at `WARNING` severity (not `CRITICAL`)

#### Scenario: UNKNOWN link does not change the parent's severity
- GIVEN a `PhysicalLink` with `status = UNKNOWN`
- WHEN the parent CI's CRITICAL event was created BEFORE the link's status was known
- THEN the parent's event severity is unchanged (the degradation only applies to the propagated event, not retroactively to the parent)

#### Scenario: propagated event keeps the ROOT CI as its root cause
- GIVEN a `PhysicalLink` with `status = UNKNOWN`
- AND a parent CI with an active root event
- WHEN the propagated event is written for the child CI
- THEN its `root_cause_ci_id` is the parent CI's id (not the PhysicalLink's id)
- AND the propagated event is linked to the child CI

#### Scenario: modern and legacy paths agree on the degraded severity
- GIVEN a `PhysicalLink` with `status = UNKNOWN`
- WHEN the same failure is evaluated by the modern SNMP path and by the legacy path
- THEN both paths emit a `PROPAGATED` Event at `WARNING` severity
- AND neither path erases the `WARNING` severity
- AND neither path emits a second propagated event for the same failure

### REQ-CORR-PROP-2: Status freshness model

The correlation traversal MUST re-read each `:CONNECTED_VIA` PhysicalLink's `status` at query time within the same Cypher statement. No cache, no TTL.

#### Scenario: status is read fresh in a correlation query
- GIVEN a `PhysicalLink` with `status = DOWN` in Neo4j
- WHEN a correlation query traverses through this link
- THEN the query reads `status` as part of the same Cypher statement
- AND no cached value is used

#### Scenario: status change between two correlation queries is reflected
- GIVEN a `PhysicalLink` with `status = UP` at time T1
- AND the same `PhysicalLink` with `status = DOWN` at time T2 (between two correlation queries)
- WHEN a correlation query runs at T2
- THEN the query sees `status = DOWN` (the change is reflected without restart or cache invalidation)

### REQ-CORR-PROP-3: DOWN behavior

The system MUST generate a descendant event when a PhysicalLink transitions from `UP` to `DOWN`. The descendant event MUST use `event_type = "physical_link_down"`, `severity = CRITICAL`, and `status = OPEN`. Its `root_cause_ci_id` MUST be the PhysicalLink's own id (not a CI id), and its `affected_ci_ids` MUST contain both endpoints of the link. The event MUST be attached to exactly one CI, and concurrent bridge runs MUST create at most one event for the same transition.

#### Scenario: UP to DOWN transition generates a descendant event
- GIVEN a `PhysicalLink` with `status = UP` and two endpoint CIs
- WHEN polling observes `status = DOWN` on the link
- THEN the system creates a new event with `root_cause_ci_id` = the link's id
- AND the event's affected set includes both endpoint CIs

#### Scenario: descendant event is distinguishable from CI events
- GIVEN the previous scenario
- WHEN the descendant event is queried
- THEN it has `event_type = "physical_link_down"` (or equivalent) and `root_cause_ci_id` = the link's id (not a CI's id)

#### Scenario: descendant event severity and status
- GIVEN a `PhysicalLink` with `status = UP` and two endpoint CIs
- WHEN polling observes `status = DOWN` on the link
- THEN the descendant event is created with `severity = CRITICAL`
- AND the descendant event is created with `status = OPEN`

#### Scenario: concurrent bridge runs create at most one event
- GIVEN a `PhysicalLink` with `status = UP` and two endpoint CIs
- WHEN two bridge runs observe the same `UP → DOWN` transition concurrently
- THEN at most one `physical_link_down` event exists for that link

### REQ-CORR-PROP-4: MANAGES / USES / PROVIDES default propagation

The traversal MUST include `:MANAGES`, `:USES`, and `:PROVIDES` relationships with default propagation when the rollout slice that carries them is enabled. No per-CI flag and no per-metric flag is required.

#### Scenario: MANAGES relationship propagates events
- GIVEN a CI `A` with a `:MANAGES` relationship to CI `B`
- AND CI `B` has an active root event
- WHEN a metric on CI `A` is evaluated
- THEN CI `A` is recorded as affected (PROPAGATED) with `root_cause_ci_id` = CI `B`

#### Scenario: USES relationship propagates events
- GIVEN a CI `A` with a `:USES` relationship to CI `B`
- AND CI `B` has an active root event
- WHEN a metric on CI `A` is evaluated
- THEN CI `A` is recorded as affected (PROPAGATED) with `root_cause_ci_id` = CI `B`

#### Scenario: PROVIDES relationship propagates events
- GIVEN a CI `A` with a `:PROVIDES` relationship to CI `B`
- AND CI `B` has an active root event
- WHEN a metric on CI `A` is evaluated
- THEN CI `A` is recorded as affected (PROPAGATED) with `root_cause_ci_id` = CI `B`

### REQ-CORR-PROP-5: Contract module as single source of truth

The four locked decisions MUST be encoded as constants in `backend/services/correlation_propagation_contract.py`. The chained implementation PRs MUST import the constants from this module; the constants MUST NOT be hardcoded in the traversal functions.

#### Scenario: PR2a2 imports the UNKNOWN policy
- GIVEN PR2a2 / PR2b1 implement the severity degradation for UNKNOWN propagation
- WHEN the implementation code is reviewed
- THEN the policy is referenced via `services.correlation_propagation_contract.PHYSICAL_LINK_UNKNOWN_PROPAGATION` (or the `should_propagate_unknown_severity_degrade` helper)
- AND no literal string `"degrade_severity_and_propagate"` appears in the implementation code outside the contract module

#### Scenario: contract tests pin the four values
- GIVEN the contract module
- WHEN `pytest tests/test_correlation_propagation_contract.py` runs
- THEN 33 tests pass and pin the four decision values

### REQ-CORR-PROP-6: Helper functions

The contract module MUST expose boolean helper functions for each of the four decisions, so that callers do not have to compare string constants. The helpers MUST be:

- `should_propagate_unknown_severity_degrade() -> bool`
- `should_re_query_status_per_correlation() -> bool`
- `should_generate_descendant_event_on_down() -> bool`
- `should_default_propagate_manages_uses_provides() -> bool`

#### Scenario: helpers return True for the locked values
- GIVEN the four locked decisions
- WHEN each helper is called
- THEN all four return `True`

### REQ-CORR-PROP-7: Relationship set registry

The contract module MUST expose two frozensets:

- `CURRENT_TRAVERSAL_RELATIONSHIP_TYPES` — the 3 types the pre-#539 traversal walks.
- `SUPPORTED_TRAVERSAL_RELATIONSHIP_TYPES` — the 7 types the chained PRs will walk once all three land (3 pre-#539 + 1 `:CONNECTED_VIA` + 3 `MANAGES/USES/PROVIDES`).

`CURRENT_TRAVERSAL_RELATIONSHIP_TYPES` MUST be a strict subset of `SUPPORTED_TRAVERSAL_RELATIONSHIP_TYPES`.

#### Scenario: registry reflects pre-#539 behavior in PR1
- GIVEN PR1 is merged and PR2a1–PR2c2 / PR3 / PR4 are not yet merged
- WHEN the registry is queried
- THEN `CURRENT_TRAVERSAL_RELATIONSHIP_TYPES` = `{"DEPENDS_ON", "HOSTED_ON", "CONNECTS_TO"}`
- AND `SUPPORTED_TRAVERSAL_RELATIONSHIP_TYPES` = `{"DEPENDS_ON", "HOSTED_ON", "CONNECTS_TO", "CONNECTED_VIA", "MANAGES", "USES", "PROVIDES"}`

### REQ-CORR-PROP-8: Feature flag names

The contract module MUST define feature flag name constants for the three implementation slices:

- `FEATURE_FLAG_PHYSICAL_LINK_CORRELATION` = `"FEATURE_CMDB_CORRELATION_PHYSICAL_LINK_PROPAGATION_ENABLED"` (the PR2a1–PR2c2 PhysicalLink chain)
- `FEATURE_FLAG_MANAGES_USES_PROVIDES_CORRELATION` = `"FEATURE_CMDB_CORRELATION_MANAGES_USES_PROVIDES_ENABLED"` (PR3)
- `FEATURE_FLAG_CONNECTS_TO_MEDIUM_FILTER` = `"FEATURE_CMDB_CORRELATION_CONNECTS_TO_MEDIUM_FILTER_ENABLED"` (PR4)

All three flags default off; the implementation PRs flip them to `true` after CI is green.

#### Scenario: flag names follow the FEATURE_CMDB_CORRELATION_*_ENABLED convention
- GIVEN the three flag name constants
- WHEN each is read
- THEN it starts with `"FEATURE_CMDB_CORRELATION_"`
- AND it ends with `"_ENABLED"`

### REQ-CORR-PROP-9: Canonical PhysicalLink connectivity and lifecycle repair

A PhysicalLink MUST be represented in the graph only as **two inbound `CONNECTED_VIA` edges** from its endpoint CIs: `(endpoint_a:CI)-[:CONNECTED_VIA]->(pl:PhysicalLink)` and `(endpoint_b:CI)-[:CONNECTED_VIA]->(pl)`. There MUST be no `PhysicalLink → CI` edge — the link is the target of both endpoint edges, never the source. `PhysicalLinkRepo.create()` MUST create the `:PhysicalLink` node and both inbound `CONNECTED_VIA` edges in the same write. `backend/migrations/011_*.cypher` MUST backfill the two inbound `CONNECTED_VIA` edges for every existing `:PhysicalLink` from its stored `endpoints`, and MUST be idempotent — re-running it MUST NOT create duplicate edges or duplicate nodes. Deleting an endpoint CI MUST remove the affected `:PhysicalLink` and its `CONNECTED_VIA` edges atomically, leaving no orphan link and no dangling endpoint reference. The public node-usage count MUST preserve its pre-#539 semantics: every relationship incident to the CI keeps its prior contribution — all pre-existing relationship types and all pre-existing targets — and only the newly introduced `CONNECTED_VIA` edges whose other endpoint is a `:PhysicalLink` are excluded from `GET /api/nodes/{id}/usage`. The usage count MUST NOT be narrowed to CI↔CI relationships.

#### Scenario: new PhysicalLink creates canonical edges
- GIVEN two endpoint CIs exist
- WHEN a PhysicalLink is created for those endpoints
- THEN the graph contains `(endpoint_a:CI)-[:CONNECTED_VIA]->(pl:PhysicalLink)`
- AND the graph contains `(endpoint_b:CI)-[:CONNECTED_VIA]->(pl)`
- AND no `(:PhysicalLink)-[:CONNECTED_VIA]->(:CI)` edge exists

#### Scenario: backfill is idempotent
- GIVEN a `:PhysicalLink` node with two endpoint ids and no `CONNECTED_VIA` edges
- WHEN `backend/migrations/011_*.cypher` is applied
- THEN both inbound `CONNECTED_VIA` edges exist
- AND applying the migration again creates no additional edges and no additional `:PhysicalLink` nodes

#### Scenario: deleting an endpoint CI repairs the link
- GIVEN a PhysicalLink connects CI-A and CI-B
- WHEN CI-A is deleted
- THEN the PhysicalLink is removed together with its `CONNECTED_VIA` edges
- AND no `PhysicalLink` node keeps CI-A in its `endpoints`
- AND CI-B keeps no dangling relationship to the removed link

#### Scenario: node usage excludes only the new CI-to-PhysicalLink edges
- GIVEN a CI with pre-existing incident relationships (CI↔CI and non-CI targets such as `HAS_METRIC`, `OWNED_BY`, `CATEGORIZED_AS`, or `HAS_EVENT`)
- AND the CI also has newly introduced `CONNECTED_VIA` edges to `:PhysicalLink` nodes
- WHEN `GET /api/nodes/{id}/usage` is called
- THEN the returned count equals the CI's pre-#539 count
- AND the `CONNECTED_VIA` edges whose other endpoint is a `:PhysicalLink` are not counted
- AND the pre-existing relationships keep their prior contribution
- AND the count is not restricted to CI↔CI relationships

### REQ-CORR-PROP-10: Correlation traversal requires a `:PhysicalLink` intermediate

Every correlation traversal MUST match `(ci)-[:CONNECTED_VIA]->(pl:PhysicalLink)<-[:CONNECTED_VIA]-(peer:CI)`; the intermediate `:PhysicalLink` node is mandatory. The traversal reads the two inbound edges as one hop — endpoint → link ← endpoint. A traversal MUST NOT match a direct `(:CI)-[:CONNECTED_VIA]->(:CI)` edge. Dormant CI→CI `CONNECTED_VIA` seed edges (for example the bootstrap data in `docker/neo4j/init.cypher`) MUST NOT be interpreted as PhysicalLink hops.

#### Scenario: CI-to-CI CONNECTED_VIA seed edge is not a PhysicalLink hop
- GIVEN a CI→CI `CONNECTED_VIA` edge exists with no `:PhysicalLink` node between the two CIs
- WHEN the correlation traversal runs for the source CI
- THEN the edge is not traversed
- AND the edge is not treated as a status-gated PhysicalLink

#### Scenario: traversal requires the intermediate PhysicalLink node
- GIVEN a CI connected to a `:PhysicalLink` that is connected to another CI
- WHEN the correlation traversal runs for the source CI
- THEN the path crosses the `:PhysicalLink` node
- AND the path is matched as `(ci)-[:CONNECTED_VIA]->(pl)<-[:CONNECTED_VIA]-(peer)`
- AND the link's `status` is evaluated as the gate for that hop

### REQ-CORR-PROP-11: PhysicalLink DOWN event host and pruner-limited recovery

The `physical_link_down` event MUST be hosted by endpoint A: its `ci_id` MUST be endpoint A's id, and its `HAS_EVENT` relationship MUST target endpoint A only. Endpoint B MUST remain present in `affected_ci_ids`. A later link recovery to `UP` MUST NOT auto-recover or pre-emptively close the event. The existing event-pruner MUST be **extended** so that it closes an **OPEN, unacknowledged** `physical_link_down` event once the event's age exceeds `EVENT_PRUNE_STALE_AFTER_SECONDS` (existing default 3600 seconds), recording `status = CLOSED`, `closed_at`, and `closed_by = system-prune` (or the configured pruner actor). The unmodified pruner closes `RECOVERED` events only, so closing an OPEN `physical_link_down` event is an explicit RED→GREEN implementation item of PR2c2. No path other than the pruner's stale-event policy or an explicit operator action may close the event.

#### Scenario: event is hosted by endpoint A
- GIVEN a PhysicalLink with endpoint A and endpoint B
- WHEN the `physical_link_down` event is created
- THEN the event's `ci_id` is endpoint A's id
- AND the only `HAS_EVENT` relationship for the event targets endpoint A
- AND endpoint B is still listed in `affected_ci_ids`

#### Scenario: operator feed shows a single row
- GIVEN a `physical_link_down` event hosted by endpoint A that affects endpoint A and endpoint B
- WHEN the operator event feed is rendered
- THEN the event appears once
- AND endpoint B is still shown as affected

#### Scenario: later recovery does not close the event
- GIVEN an OPEN `physical_link_down` event for a PhysicalLink
- WHEN the PhysicalLink status returns to `UP`
- THEN the event is not automatically recovered or closed by the link recovery
- AND the event is not pre-emptively closed by the link recovery
- AND the event remains subject to the pruner's stale-event policy

#### Scenario: pruner closes a stale OPEN physical_link_down event
- GIVEN an OPEN, unacknowledged `physical_link_down` event whose age exceeds `EVENT_PRUNE_STALE_AFTER_SECONDS` (existing default 3600 seconds)
- WHEN the extended event-pruner runs
- THEN the event's `status` becomes `CLOSED`
- AND the event's `closed_at` is recorded
- AND the event's `closed_by` is `system-prune` (or the configured pruner actor)

#### Scenario: pruner leaves acknowledged and fresh events open
- GIVEN an acknowledged OPEN `physical_link_down` event older than the threshold
- OR an OPEN, unacknowledged `physical_link_down` event younger than the threshold
- WHEN the extended event-pruner runs
- THEN the event remains `OPEN`
- AND the event is not closed

### REQ-CORR-PROP-12: Unchanged cross-chain constraints

The chained implementation slices MUST NOT change the supported CI relationship whitelist, the traversal depth, or the permission model. `backend/services/relationship_types.py:7-13` (`SUPPORTED_CI_RELATIONSHIP_TYPES`) MUST stay at its 6 CI relationship types — only the traversal changes. The default and maximum traversal depth MUST stay 3. No new `UserPermission` enum value MUST be introduced. The ROOT vs PROPAGATED semantics MUST remain unchanged; only the set of traversed relationships and the gates change.

#### Scenario: relationship whitelist is unchanged
- GIVEN the chained implementation slices have landed
- WHEN `SUPPORTED_CI_RELATIONSHIP_TYPES` is read
- THEN it contains exactly `CONNECTS_TO`, `DEPENDS_ON`, `HOSTED_ON`, `MANAGES`, `USES`, `PROVIDES`

#### Scenario: depth default is unchanged
- GIVEN the chained implementation slices have landed
- WHEN the correlation traversal runs
- THEN the default and maximum traversal depth is 3

#### Scenario: no new permission values
- GIVEN the chained implementation slices have landed
- WHEN the `UserPermission` enum is read
- THEN it contains no value added for correlation propagation

#### Scenario: ROOT and PROPAGATED semantics are unchanged
- GIVEN the chained implementation slices have landed
- WHEN a failure is correlated
- THEN a root cause is still classified as `ROOT` and a correlated symptom as `PROPAGATED`
- AND only the traversed relationship set and the status gates differ from the pre-#539 behavior

### REQ-CORR-PROP-13: Rollout flag for the reconciled PhysicalLink chain

The whole reconciled PhysicalLink chain MUST ship behind `FEATURE_CMDB_CORRELATION_PHYSICAL_LINK_PROPAGATION_ENABLED`, which defaults to off. The flag MUST be flipped to `true` only after every slice of the chain has landed and the CI is green.

#### Scenario: flag defaults to off
- GIVEN a fresh deployment with no explicit flag configuration
- WHEN the correlation runtime resolves its configuration
- THEN `FEATURE_CMDB_CORRELATION_PHYSICAL_LINK_PROPAGATION_ENABLED` is `false`
- AND no PhysicalLink propagation behavior is enabled

#### Scenario: flag gates the chain
- GIVEN `FEATURE_CMDB_CORRELATION_PHYSICAL_LINK_PROPAGATION_ENABLED` is `false`
- WHEN a correlation traverses a `:PhysicalLink`
- THEN the traversal does not use the PhysicalLink hop

## MODIFIED Requirements

_None. PR1 does not modify any existing requirement._

## REMOVED Requirements

_None._

## Cross-references

- Source proposal: `openspec/changes/feat-correlation-propagation-semantics/proposal.md`
- Source tasks: `openspec/changes/feat-correlation-propagation-semantics/tasks.md`
- Design doc: `docs/correlation-topology-guide.md` (the "Locked propagation decisions" and "Reconciled connectivity contract" sections)
- Contract module: `backend/services/correlation_propagation_contract.py`
- Contract tests: `backend/tests/test_correlation_propagation_contract.py`
- Sibling OpenSpec change: `openspec/changes/feat-cmdb-physical-links-runtime/` (provides `:PhysicalLink` and `:CONNECTED_VIA`)
- Issue: #539
