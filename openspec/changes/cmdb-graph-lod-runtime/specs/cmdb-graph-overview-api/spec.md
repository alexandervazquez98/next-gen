# Spec delta: cmdb-graph-overview-api

## ADDED Requirements

### REQ-OVERVIEW-1: Overview endpoint

The system MUST expose `GET /graph/overview` returning a list of `OverviewCluster` records (per `backend/schemas/graph.py::GraphOverviewCluster` shipped in v1.17.6). The endpoint MUST apply authorization/scoping before aggregation.

#### Scenario: overview returns authorized clusters with aggregates
- GIVEN a principal with `CMDB_READ` and a visible CI set of 100 nodes across 4 locations
- WHEN the principal calls `GET /graph/overview`
- THEN the response is `200 OK`
- AND the body contains one `OverviewCluster` per visible location
- AND each cluster carries aggregates derived only from the visible set

#### Scenario: overview aggregates are post-authorization
- GIVEN a principal whose visible set excludes `location:datacenter-east`
- WHEN the principal calls `GET /graph/overview`
- THEN the response does NOT include `location:datacenter-east`
- AND the aggregate counts in other clusters do not include the hidden datacenter's CIs

### REQ-OVERVIEW-2: Aggregate disclosure policy

The system MUST apply the aggregate policy (`backend/contracts/aggregate_policy.py`) to determine `SafeGeoPrecision` per cluster based on the visible count and principal permissions.

#### Scenario: low-cardinality clusters suppress aggregates
- GIVEN a cluster with visible count < `minimum_count` (default 5)
- WHEN the principal calls `GET /graph/overview`
- THEN the cluster's aggregate fields are suppressed (omitted or set to null per DTO contract)
- AND the response carries `empty_reason: "low_cardinality"` or equivalent

#### Scenario: mid-cardinality clusters bucket to region
- GIVEN a cluster with `minimum_count <= visible count < minimum_count * 4`
- WHEN the principal calls `GET /graph/overview`
- THEN the cluster's geographic precision is `region`
- AND city-level fields are suppressed

#### Scenario: high-cardinality clusters show city with global permission and region in scope
- GIVEN a cluster with `visible count >= minimum_count * 4` and region `datacenter-east`
- AND the principal has `graph:aggregate_breakdown:read`
- AND the principal's `aggregate_breakdown_regions` contains `datacenter-east` (or is empty, meaning global)
- WHEN the principal calls `GET /graph/overview`
- THEN the cluster's geographic precision is `city`
- AND full aggregates are returned

#### Scenario: high-cardinality clusters with global permission but region out of scope
- GIVEN a cluster with `visible count >= minimum_count * 4` and region `datacenter-east`
- AND the principal has `graph:aggregate_breakdown:read`
- AND the principal's `aggregate_breakdown_regions` is `["datacenter-west"]` (does not contain `datacenter-east`)
- WHEN the principal calls `GET /graph/overview`
- THEN the cluster's geographic precision is `region` (silently downgraded)
- AND the response shape is externally indistinguishable from the global-with-permission case except for the precision field

#### Scenario: high-cardinality clusters without permission
- GIVEN a cluster with `visible count >= minimum_count * 4`
- AND the principal lacks `graph:aggregate_breakdown:read`
- WHEN the principal calls `GET /graph/overview`
- THEN the cluster's geographic precision is `region` (downgraded)
- AND the response shape is externally indistinguishable from the with-permission case except for the precision field

#### Scenario: aggregate breakdown scope is mutable and audited
- GIVEN the principal is ADMIN
- WHEN the admin assigns `aggregate_breakdown_regions = ["datacenter-east"]` to another user
- THEN an audit row is emitted with actor, target user, before/after value, timestamp
- AND subsequent `/graph/overview` calls by that user reflect the new scope

### REQ-OVERVIEW-3: Hidden ≡ absent parity

The system MUST respond identically for hidden clusters and absent clusters.

#### Scenario: hidden cluster response
- GIVEN a cluster `location:datacenter-east` that exists in the graph
- AND the principal's visible set excludes it
- WHEN the principal queries for `location:datacenter-east` (e.g., via detail endpoint or filter)
- THEN the response is `200 OK` with `cluster: null`
- AND `empty_reason: "hidden_absent"`
- AND no field indicates the cluster exists

#### Scenario: absent cluster response
- GIVEN a cluster `location:nonexistent` that does NOT exist in the graph
- WHEN the principal queries for it
- THEN the response is `200 OK` with `cluster: null`
- AND `empty_reason: "hidden_absent"`
- AND the response is byte-equivalent to the hidden cluster response

### REQ-OVERVIEW-4: Visible-candidate-only search/filter

The system MUST resolve search/filter targets only against the principal's visible set.

#### Scenario: search returns visible-only matches
- GIVEN a principal whose visible set excludes certain CIs
- WHEN the principal calls `GET /graph/overview?filter=<term>`
- THEN the response only includes CIs in the principal's visible set
- AND no field indicates the existence of additional matching CIs outside the visible set

## MODIFIED Requirements

_None — this slice is purely additive._

## REMOVED Requirements

_None — `/graph/full` is preserved as a compatibility endpoint._

## Cross-references

- DTOs: `backend/schemas/graph.py` (shipped v1.17.6)
- Value objects: `backend/contracts/aggregate_policy.py`, `backend/contracts/cluster_id.py`, `backend/contracts/revision.py` (shipped v1.17.6)
- Frozen fixtures: `fixtures/graph-contracts/overview_*.json` (shipped v1.17.6)
- Spec coverage gate: `backend/tests/test_spec_coverage_graph.py` (extend for runtime scenarios)
- Source proposal: `openspec/changes/cmdb-graph-lod-runtime/proposal.md`