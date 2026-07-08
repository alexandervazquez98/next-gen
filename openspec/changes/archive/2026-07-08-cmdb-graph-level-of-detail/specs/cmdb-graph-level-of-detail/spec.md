# CMDB Graph Level-of-Detail Specification

## Purpose

Define the design-only behavior for introducing level-of-detail loading to CMDB topology views so that first render is overview-driven, detail data is loaded only by explicit operator action, security guarantees are unchanged, and `/graph/full` remains backward-compatible.

## Requirements

### Requirement: Overview payload contract for first paint

The system MUST define an overview payload contract used for the initial CMDB topology render, scoped to a first-slice **Location** clustering axis.

The overview payload MUST include:
- cluster identifiers and display labels for clusters visible to the caller,
- aggregate node and link counts per cluster after authorization filtering,
- high-level inter-cluster link counts/weights after authorization filtering,
- metadata required to render the current location-level topology legend and summary cards,
- suppression or bucketing metadata for low-cardinality aggregates,
- pagination / continuation signals only if needed by the design.

The overview payload MUST NOT include per-node sensitive metadata such as `public_ip`, external DNS names, NAT addresses, precise endpoint coordinates, serial numbers, provider account identifiers, or comparable infrastructure identifiers.

#### Scenario: First render uses overview contract
- GIVEN the topology view loads for the first time,
- WHEN initial data is requested,
- THEN the client MUST use the overview contract rather than a full node/link dump for first paint.

#### Scenario: Initial cluster axis is location
- GIVEN no additional user interaction has occurred,
- WHEN cluster grouping is computed,
- THEN grouping MUST default to Location and MAY include stable tie-breakers for nodes without location metadata.

#### Scenario: `/graph/full` remains compatible with overview introduction
- GIVEN existing consumers still call `/graph/full`,
- WHEN no changes are required by this slice,
- THEN the endpoint MUST continue returning the existing full topology shape.

#### Scenario: Low-cardinality overview aggregates are protected
- GIVEN a visible cluster, link group, status/type/medium bucket, weight, or geo bucket has fewer than the configured safe minimum count,
- WHEN the overview payload is built,
- THEN the design MUST suppress the exact value or bucket it into an `other`/`suppressed` aggregate unless the principal has explicit aggregate-breakdown permission.

### Requirement: Detail subgraph payload contract

The system MUST define a detail retrieval contract for a selected cluster/segment that returns only the nodes and links relevant to that selection.

Search/filter resolution MUST be computed only after authorization filtering and only over visible candidates plus allowed public axes/labels. Hidden candidates MUST NOT affect match counts, ambiguity decisions, status codes, response body shape, timing, pagination, or whether detail hydration occurs.

The detail payload MUST include:
- the requested cluster/segment identifier only when the cluster is visible to the caller,
- selected node/link records with existing field semantics,
- parent summary reference fields enabling incremental merge back into overview context,
- auth-related projection flags (for parity with overview security),
- clear empty-result semantics when filters hide all visible details.

The detail endpoint MUST derive the cluster axis from `cluster_id` and MUST reject contradictory query parameters instead of accepting conflicting `axis` values.

#### Scenario: Detail payload is demand-driven
- GIVEN a user explicitly selects a cluster for expansion,
- WHEN a detail fetch is triggered,
- THEN only subgraph detail for that cluster/segment MUST be returned.

#### Scenario: Search/filter-driven detail fetch
- GIVEN a user applies search or filter narrowing to a cluster/segment,
- WHEN the new view context is established,
- THEN the client MUST request detail only for the relevant target context, and not for the entire topology.

#### Scenario: Search resolves exactly one visible cluster
- GIVEN a committed search/filter resolves to exactly one visible cluster after authorization filtering,
- AND hidden candidates may or may not exist outside the caller's scope,
- WHEN detail is requested,
- THEN the client MUST fetch detail for that visible cluster only, with behavior based solely on the visible match.

#### Scenario: Search resolves multiple visible clusters
- GIVEN a committed search/filter resolves to multiple visible clusters after authorization filtering,
- WHEN results are shown,
- THEN the client MUST keep the overview result set and require explicit operator selection before fetching detail.

#### Scenario: Search resolves no visible clusters
- GIVEN a committed search/filter resolves to no visible clusters after authorization filtering,
- AND hidden candidates may or may not exist outside the caller's scope,
- WHEN results are shown,
- THEN the client MUST show the same empty overview/search state and MUST NOT fetch full topology detail regardless of hidden candidates.

#### Scenario: Search is ambiguous
- GIVEN a committed search/filter is ambiguous among multiple visible candidates or allowed public axes/labels after authorization filtering,
- WHEN results are shown,
- THEN the client MUST avoid detail hydration and ask for refinement or explicit visible-cluster selection.

#### Scenario: No unsolicited detail expansion
- GIVEN zoom level changes but no explicit expand/search/filter action,
- WHEN render updates,
- THEN no additional detail call MAY be triggered by zoom threshold logic.

### Requirement: Security and authorization parity between summary and detail

The system MUST apply equivalent authorization and tenant scoping to overview and detail responses. This design slice does not change `/graph/full` response shape or existing semantics.

Sensitive-field policy for future LOD endpoints:
- overview responses MUST NOT include raw sensitive fields,
- detail responses MUST use the same existing authorized projection helper/policy as `/graph/full` once the implementation slice confirms that helper/policy,
- any stronger redaction policy for `/graph/full` is a separate security change and is not part of this design slice.

#### Scenario: Scoped callers receive equivalent visibility
- GIVEN the same authenticated principal and tenant scope,
- WHEN summary and detail endpoints are called with identical filters,
- THEN the visible node/link set MUST be a subset-equivalent constrained by the same policy.

#### Scenario: Restricted fields follow LOD-sensitive-field policy
- GIVEN a principal without permission to receive restricted attributes,
- WHEN overview and detail payloads are fetched,
- THEN overview MUST omit raw restricted fields entirely,
- AND detail MUST apply the existing authorized projection helper/policy used by `/graph/full` once confirmed in implementation planning.

#### Scenario: Authorized sensitive metadata is scoped
- GIVEN a principal has explicit sensitive-metadata permission for the requested tenant/location scope,
- WHEN detail payloads are fetched for visible nodes,
- THEN sensitive fields MAY be returned only according to the confirmed existing `/graph/full` projection policy and MUST still be excluded from overview aggregates.

#### Scenario: Hidden and absent clusters are indistinguishable
- GIVEN a principal requests a cluster id that is outside their scope or does not exist,
- WHEN the detail endpoint responds,
- THEN the externally observable status code, response body shape, and absence of cluster metadata MUST be identical for both cases.

#### Scenario: Security regressions are detectable across payload types
- GIVEN a limited or empty scope principal,
- WHEN both payload types are requested,
- THEN responses MUST NOT expose data outside that principal's tenant boundaries in either payload type.

### Requirement: Frontend orchestration for initial render and explicit detail loading

The frontend topology orchestration MUST separate overview orchestration from explicit detail orchestration and define state transitions for both.

#### Scenario: Initial orchestration is overview-first
- GIVEN a topology page opens,
- WHEN orchestration begins,
- THEN initial polling/state MUST prioritize overview payload retrieval and rendering before any detail hydration.

#### Scenario: Explicit expansion path
- GIVEN a cluster is clicked or expanded,
- WHEN expansion completes,
- THEN the orchestration layer MUST load and mount detail payload for only that cluster and merge it into the rendered scene as a delimited subgraph.

#### Scenario: Explicit search/filter refresh path
- GIVEN a search or filter action changes target cluster context,
- WHEN action commits,
- THEN orchestration MUST resolve target candidates only after authorization filtering,
- AND MUST trigger detail retrieval only when exactly one visible target is resolved or the operator explicitly selects one visible target from multiple visible results.

#### Scenario: Backward compatibility for polling consumers
- GIVEN a consumer that still relies on `/graph/full`,
- WHEN no equivalent compatibility strategy exists in a given frontend slice,
- THEN that consumer MUST continue to function using existing polling behavior without hard dependency on new payload contracts.

### Requirement: Non-goals and out-of-scope constraints

The design-only slice MUST NOT include automatic demand-generation of detail through zoom-threshold expansion, and MUST NOT include real-time streaming, ML-based clustering, or a visual redesign.

#### Scenario: Automatic zoom-triggered expansion is out of scope
- GIVEN the user zooms to any level,
- WHEN no explicit action is made,
- THEN detail loading MUST NOT occur based on zoom threshold alone.

#### Scenario: No streaming or ML clustering in this slice
- GIVEN implementation planning begins,
- WHEN work items are enumerated,
- THEN no task under this change MAY target streaming pipelines or ML-driven cluster generation.

### Requirement: Design-only acceptance criteria

The change MUST be completed as a design artifact only and MUST include explicit follow-up implementation slices.

The design MUST include approval-ready artifacts for: overview contract, detail contract, trigger matrix, auth parity checks, migration path, and follow-up slices.

#### Scenario: Design artifacts define all required contracts
- GIVEN the design review is conducted,
- WHEN reviewers inspect the approved spec,
- THEN each contract (overview, detail, auth parity, trigger matrix, backward compatibility) MUST be explicitly documented and testable by review.

#### Scenario: Follow-up implementation plan is explicit
- GIVEN the scope is reviewed for this change,
- WHEN design sign-off is requested,
- THEN the spec MUST list ordered follow-up implementation slices for contract finalization, backend rollout, and frontend orchestration migration.

#### Scenario: No code implementation is introduced in this change
- GIVEN the change is executed,
- WHEN artifact diff is produced,
- THEN no application code under `backend/` or `frontend/` MUST be changed.
