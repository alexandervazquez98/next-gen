# Design for CMDB Graph Level-of-Detail (Issue #230)

## Quick path
1. Preserve existing `/graph/full` behavior as a compatibility path.
2. Introduce a design for initial render using summary/overview data (location-cluster first)
3. Load detailed nodes and links only via explicit interactions (expand/click + search/filter).
4. Keep authorization and data-leak guards aligned between summary and detail fetch paths.
5. Publish follow-up implementation slices after design approval.

## Intent
Operators managing very large CMDB topologies need a faster, usable first paint and lower control-plane strain. The current implementation always pulls the entire topology for all clusters, which causes slow loads and UI stalls before the operator can even choose what to inspect. This proposal defines a design-only slice that reduces initial load by introducing level-of-detail architecture while preserving backward compatibility.

## Problem statement
- Current behavior: both `GraphCMDB` and `NetworkVisualizer` fetch full topology payloads (`/graph/full`) and rely on client-side filtering/aggregation for display.
- Resulting gap: payload size, polling overhead, and layout simulation cost grow with graph size, limiting operator productivity before interaction.
- Required business outcome: make first interaction fast and safe for large datasets by shifting detail retrieval to demand-driven calls.

## Target scope (First slice)
- **Scope is design-only**; no implementation code is planned in this change.
- Design first render in **location-based clustering** mode.
- Detail expansion is triggered by explicit operator actions only:
  - node/cluster click-to-expand,
  - search/filter refinement that targets a specific cluster/segment.
- Keep `/graph/full` endpoint behavior intact as a compatibility and fallback path.
- Preserve security and scoping guarantees for both summary and detail paths.

## Affected areas (design target)
- Backend routing and contract strategy around topology APIs.
- Backend service/repository query patterns for summary vs detail retrieval.
- Frontend data-fetching strategy for topology graph hooks/services/components.
- Polling cadence and cache invalidation behavior for summary/detail calls.

## Current-state gap
- The frontend has useful location-based clustering logic, but it is applied after full graph hydration.
- There is no explicit overview contract/API that can be safely consumed at scale.
- Multiple callers remain bound to full-graph fetch semantics.
- Existing endpoint tests are tied to `/graph/full` contract, creating migration risk if that contract changes.

## Product/business rules and assumptions
- Backward compatibility is required for `/graph/full` (no response-shape breaking change now).
- Level-of-detail starts with **Location** clustering for the first slice.
- Automatic zoom-threshold expansion is intentionally out of scope for this slice.
- No behavioral change to visualization baseline unless explicitly required by selected implementation slices.

## Recommended design direction (design decision)
1. **Backward compatibility layer first:** Keep `/graph/full` unchanged and continue supporting existing consumers.
2. **Overview-first loading:** Introduce (or reserve) a dedicated path for overview/summary responses used by GraphCMDB initial render (cluster aggregates, counts, top-level links).
3. **Demand-based detail fetching:** Add a detail endpoint contract that resolves a cluster identifier and returns only requested subgraph details with same auth/scoping semantics.
4. **Trigger matrix:** Detail load only on explicit user action (click/expand / search / filter), not automatic zoom.
5. **Security parity:** Reuse server-side scoping and filtering logic so summary and detail both enforce tenant/user visibility, collapse hidden and absent cluster responses into the same externally observable result, compute search ambiguity/match counts only over visible candidates and allowed public axes, and apply the confirmed existing authorized projection policy to detail sensitive fields. This design does not change `/graph/full` response shape or existing semantics.

## Risks and mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| Incomplete security parity between overview and detail | Medium | Reuse existing repository filter pipeline; require security test updates in follow-up implementation slice. Hidden and absent clusters must use the same externally observable response. |
| Sensitive metadata exposure through detail payloads | High | Overview never includes sensitive node metadata. Detail reuses the confirmed existing authorized projection helper/policy used by `/graph/full`. Any stronger `/graph/full` redaction is a separate security change, not part of this design slice. |
| Aggregate disclosure through low-cardinality summaries | High | Suppress or bucket aggregates below the minimum safe count and role-gate detailed breakdowns. |
| Over-scoping of design to implementation and large architectural drift | Medium | Explicitly scope this change to design decisions, data contracts, and migration sequencing only. |
| Stakeholder mismatch on interaction semantics | Medium | Document and align on trigger matrix and cluster expansion contract before implementation. |

## Rollback strategy
- If this design is rejected, revert to the current `/graph/full`-driven workflow without changes outside planning docs.
- If partially adopted, disable the new LOD path and fall back to existing full graph calls from both GraphCMDB and NetworkVisualizer until end-to-end parity is proven.

## Design acceptance criteria
- [x] A clear level-of-detail architecture is defined for: overview retrieval, detail retrieval, auth/scoping, and client state orchestration.
- [x] `/graph/full` contract remains backward-compatible and documented as unchanged for this slice.
- [x] Explicit interaction triggers are defined for detail loading, including exact search/filter behavior for one match, multiple matches, no matches, and ambiguous matches.
- [x] Location remains the only required first-slice clustering axis.
- [x] Security and authorization expectations for both payload types are explicitly documented, including hidden/absent cluster equivalence, visible-only search ambiguity/match counts, detail sensitive-field projection policy, and aggregate suppression.
- [x] A migration and verification plan is provided for follow-up implementation slices.
- [x] Design includes a scope boundary note that excludes realtime streaming, ML clustering, and visual redesign unless future slices justify it.

## Recommended follow-up implementation slices
1. **Slice A – Contract & data shape finalization**
   - Finalize overview/detail API contracts, pagination rules, and caching/invalidation expectations.
2. **Slice B – Backend rollout (safe compatibility)**
   - Add overview endpoint or parameterized mode, implement detail endpoint, keep `/graph/full` untouched.
3. **Slice C – Frontend topology orchestration**
   - Update query strategy for initial load + explicit-detail fetching paths; handle old and new paths in parallel during transition.

## Non-goals (explicit + conservative inferences)
- No complete visualizer rewrite in this change.
- No realtime streaming of graph changes.
- No ML-based clustering/auto-clustering.
- No primary visual polish objective unless explicitly justified in a later business-slice decision.

## Proposal question round
These questions are to tighten PRD alignment before locking this design for implementation.

1. What operator-level success metric should we use to stop loading more detail automatically (e.g., time-to-first-render target or max initial payload size)?
2. For explicit search/filter, should detail loading replace the current root view, or open as an additive detail panel/subgraph overlay while preserving current context?
3. In rollout, should GraphCMDB be the exclusive frontend owner of LOD behavior first, or should `NetworkVisualizer` share the same summary/detail contract in this change (even in design only) as a requirement?
4. If a cluster is expanded and then filters change, should expanded detail persist, reset, or be versioned by filter context?
5. What is the minimum “safe rollout” criterion for allowing removal of any remaining `/graph/full` callers in later slices (e.g., 30-day canary, error budget, or operator sign-off)?

## Assumptions after Round 1
- Scope excludes implementation and limits delivery to design decisions for this change.
- Location-based clustering is the default first-slice grouping.
- Automatic zoom-triggered expansion remains out of scope.
- Existing `/graph/full` contract is preserved in this iteration.
- Design will include explicit follow-up slices to execute changes safely after approval.