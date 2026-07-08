# Tasks: CMDB Graph Level-of-Detail (Issue #230, Design-only)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1609 inserted lines after sync/archive |
| 400-line budget risk | High after sync/archive |
| Chained PRs recommended | No |
| Suggested split | single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: stacked-to-main
400-line budget risk: High after sync/archive

## Phase 1 — Scope and artifact preconditions

- [x] 1.1 Confirm required artifacts exist and match this change scope: `openspec/changes/cmdb-graph-level-of-detail/proposal.md`, `openspec/changes/cmdb-graph-level-of-detail/specs/cmdb-graph-level-of-detail/spec.md`, `openspec/changes/cmdb-graph-level-of-detail/design.md`.
- [x] 1.2 Confirm optional context was considered: `openspec/changes/cmdb-graph-level-of-detail/exploration.md`.
- [x] 1.3 Validate and document (in `openspec/changes/cmdb-graph-level-of-detail/tasks.md` notes) that this slice is **design-only** and must not include backend/frontend implementation changes.

## Phase 2 — Design/spec alignment verification

- [x] 2.1 Add or validate a spec-to-design mapping section in `openspec/changes/cmdb-graph-level-of-detail/design.md` that maps each `spec.md` requirement family to the concrete design section (overview payload, detail payload, security parity, frontend orchestration, rollout/non-goals).
- [x] 2.2 Verify spec Scenario coverage for this slice in `design.md` and call out any missing scenario with concrete follow-up task entries rather than in-scope edits.
- [x] 2.3 Verify `design.md` clearly documents all out-of-scope constraints from `spec.md` (no auto zoom-triggered expansion, no streaming/ML clustering, no real-time/full-graph redesign in this slice).

## Phase 3 — Security and compatibility consistency checks

- [x] 3.1 Verify `design.md` explicitly enforces hidden-versus-absent cluster indistinguishability and that hidden candidates never alter match/ambiguity/empty behavior (`empty_reason` parity, timing/shape/status equivalence).
- [x] 3.2 Verify `design.md` and `spec.md` both state visible-only search/ambiguity resolution (`only visible candidates + allowed public axes/labels`) for both overview and detail requests.
- [x] 3.3 Verify `design.md` documents **no `/graph/full` semantic or redaction change** for this LOD slice and references that stronger redaction belongs to a separate security change.
- [x] 3.4 Verify sensitive-field policy is explicit: overview omits raw sensitive metadata; detail reuses existing confirmed projection policy from `/graph/full` for visible nodes only.

## Phase 4 — OpenSpec consistency and review artifact

- [x] 4.1 Produce a consistency check pass in `openspec/changes/cmdb-graph-level-of-detail/tasks.md` (or companion design appendix) confirming:
  - location-only first-slice axis,
  - cluster click/expand + committed search/filter are the only demand-driven detail triggers,
  - `/graph/full` compatibility guarantee is preserved,
  - explicit follow-up implementation slices are separated from this change.
- [x] 4.2 Prepare final design-signoff evidence by reviewing all acceptance criteria in `openspec/changes/cmdb-graph-level-of-detail/specs/cmdb-graph-level-of-detail/spec.md` against the design and recording pass/fail for each requirement before apply.

## Explicit follow-up implementation slice recommendations (OUT OF SCOPE of this change)

- **Slice A (Contract Finalization)**: finalize Pydantic/TypeScript DTO contracts, pagination limits, and route-level validation for `/graph/overview` and `/graph/detail/{cluster_id}`.
- **Slice B (Backend Rollout)**: implement additive backend services/routes/repositories for overview + detail with shared visibility policy and security parity.
- **Slice C (Frontend Orchestration)**: migrate `GraphCMDB` to overview-first + explicit detail fetch flow, including query/cache lifecycle and fallback behavior.
- **Slice D (Consumer Hardening)**: migrate remaining callers (e.g., `NetworkVisualizer`) once dedicated design/operational criteria are approved.
- **Slice E (Security hardening follow-up)**: implement any `/graph/full` redaction strengthening if required as separate issue workstream (NOT in #230).

## Verification tasks for OpenSpec/design consistency only

- [x] 5.1 Re-run a three-way consistency pass across:
  - `proposal.md`
  - `specs/cmdb-graph-level-of-detail/spec.md`
  - `design.md`
  and confirm no requirement in spec is unaddressed and no design statement expands scope beyond proposal.
- [x] 5.2 Confirm every hard requirement in `design.md` can be traced back to one of: explicit user direction, design scope, or technical necessity from `exploration.md`.
- [x] 5.3 Confirm no backend/frontend file paths are included in this PR scope list for this change.

## Apply-phase evidence (design-only consistency sign-off)

- [x] 4A.1 **Artifact scope and mode confirmed**: The work is design-only and all edits are confined to OpenSpec docs under `openspec/changes/cmdb-graph-level-of-detail/`.
- [x] 4A.2 **Scope invariants preserved**: Design retains location-first overview, explicit demand-driven detail via click/expand + search/filter, and no zoom-threshold expansion trigger.
- [x] 4A.3 **Backward compatibility preserved**: `/graph/full` response shape and semantics are explicitly protected; compatibility rollback path is documented.
- [x] 4A.4 **Security parity preserved**: hidden/absent indistinguishable behavior, visible-only search resolution, aggregate suppression policy, and projection policy constraints are documented and not broadened in this slice.
- [x] 4A.5 **Spec-to-design requirement matrix validated**:
  - Requirement families in `spec.md` map to: **overview payload**, **detail payload**, **security parity**, **frontend orchestration**, **rollout/non-goals** in `design.md` (sections explicitly present).
  - No requirement expands scope beyond proposal; all expansion paths are marked follow-up slices.
  - No `/graph/full` redaction/shape change is introduced in this design slice.
