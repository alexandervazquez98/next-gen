# Spec delta: cmdb-correlation-propagation

## ADDED Requirements

### REQ-CORR-PROP-1: UNKNOWN status propagation policy

The system MUST treat `PhysicalLink.status = UNKNOWN` as propagation-eligible with severity degradation. When a PhysicalLink is in the `UNKNOWN` state and a propagation-eligible event would cross it, the propagated event MUST be emitted at `WARNING` severity instead of the parent's severity.

#### Scenario: UNKNOWN link propagates a CRITICAL parent event as WARNING
- GIVEN a `PhysicalLink` with `status = UNKNOWN`
- AND a parent CI on one side of the link has an active `CRITICAL` event
- WHEN a metric on a child CI on the other side of the link is evaluated
- THEN the system records the child CI as affected
- AND the propagated event is emitted at `WARNING` severity (not `CRITICAL`)

#### Scenario: UNKNOWN link does not change the parent's severity
- GIVEN a `PhysicalLink` with `status = UNKNOWN`
- WHEN the parent CI's CRITICAL event was created BEFORE the link's status was known
- THEN the parent's event severity is unchanged (the degradation only applies to the propagated event, not retroactively to the parent)

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

The system MUST generate a descendant event when a PhysicalLink transitions from `UP` to `DOWN`. The descendant event's `root_cause_ci_id` MUST be the link itself; the affected CIs MUST be the two endpoints of the link.

#### Scenario: UP to DOWN transition generates a descendant event
- GIVEN a `PhysicalLink` with `status = UP` and two endpoint CIs
- WHEN polling observes `status = DOWN` on the link
- THEN the system creates a new event with `root_cause_ci_id` = the link's id
- AND the event's affected set includes both endpoint CIs

#### Scenario: descendant event is distinguishable from CI events
- GIVEN the previous scenario
- WHEN the descendant event is queried
- THEN it has `event_type = "physical_link_down"` (or equivalent) and `root_cause_ci_id` = the link's id (not a CI's id)

### REQ-CORR-PROP-4: MANAGES / USES / PROVIDES default propagation

The traversal MUST include `:MANAGES`, `:USES`, and `:PROVIDES` relationships with default propagation. No per-CI flag, no per-metric flag, no env-var gate is required.

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

#### Scenario: PR2 imports the UNKNOWN policy
- GIVEN PR2 implements the severity degradation for UNKNOWN propagation
- WHEN the PR2 code is reviewed
- THEN the policy is referenced via `services.correlation_propagation_contract.PHYSICAL_LINK_UNKNOWN_PROPAGATION` (or the `should_propagate_unknown_severity_degrade` helper)
- AND no literal string `"degrade_severity_and_propagate"` appears in the PR2 code outside the contract module

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
- GIVEN PR1 is merged and PR2/3/4 are not yet merged
- WHEN the registry is queried
- THEN `CURRENT_TRAVERSAL_RELATIONSHIP_TYPES` = `{"DEPENDS_ON", "HOSTED_ON", "CONNECTS_TO"}`
- AND `SUPPORTED_TRAVERSAL_RELATIONSHIP_TYPES` = `{"DEPENDS_ON", "HOSTED_ON", "CONNECTS_TO", "CONNECTED_VIA", "MANAGES", "USES", "PROVIDES"}`

### REQ-CORR-PROP-8: Feature flag names

The contract module MUST define feature flag name constants for the three implementation PRs:

- `FEATURE_FLAG_PHYSICAL_LINK_CORRELATION` = `"FEATURE_CMDB_CORRELATION_PHYSICAL_LINK_PROPAGATION_ENABLED"` (PR2)
- `FEATURE_FLAG_MANAGES_USES_PROVIDES_CORRELATION` = `"FEATURE_CMDB_CORRELATION_MANAGES_USES_PROVIDES_ENABLED"` (PR3)
- `FEATURE_FLAG_CONNECTS_TO_MEDIUM_FILTER` = `"FEATURE_CMDB_CORRELATION_CONNECTS_TO_MEDIUM_FILTER_ENABLED"` (PR4)

All three flags default off; the implementation PRs flip them to `true` after CI is green.

#### Scenario: flag names follow the FEATURE_CMDB_CORRELATION_*_ENABLED convention
- GIVEN the three flag name constants
- WHEN each is read
- THEN it starts with `"FEATURE_CMDB_CORRELATION_"`
- AND it ends with `"_ENABLED"`

## MODIFIED Requirements

_None. PR1 does not modify any existing requirement._

## REMOVED Requirements

_None._

## Cross-references

- Source proposal: `openspec/changes/feat-correlation-propagation-semantics/proposal.md`
- Source tasks: `openspec/changes/feat-correlation-propagation-semantics/tasks.md`
- Design doc: `docs/correlation-topology-guide.md` (the "Locked propagation decisions" section)
- Contract module: `backend/services/correlation_propagation_contract.py`
- Contract tests: `backend/tests/test_correlation_propagation_contract.py`
- Sibling OpenSpec change: `openspec/changes/feat-cmdb-physical-links-runtime/` (provides `:CONNECTED_VIA`)
- Issue: #539
