## Proposal: feat(cmdb) finalize LOD graph overview and detail contracts (#390)

### Problem

Issue #390 finalizes the contract slice for the CMDB LOD endpoints `GET /graph/overview` (location-cluster aggregates) and `GET /graph/detail/{cluster_id}` (selected-cluster subgraph). Parent epic #230 already pins the behavioral invariants (archived at `openspec/specs/cmdb-graph-level-of-detail/spec.md` and `openspec/changes/archive/2026-07-08-cmdb-graph-level-of-detail/`): Location is the first overview axis, aggregates are post-authorization, hidden and absent clusters are externally indistinguishable, and `/graph/full` is frozen. What #390 still owes is the wire-authoritative shape — DTO fields, codec rules, cursor/revision semantics, hidden/absent equivalence, visible-only search resolution, and aggregate disclosure policy — without which #391 (backend APIs), #392 (GraphCMDB migration), and #393 (remaining consumers) cannot ship without drift.

### Scope

**Owns**:
- Backend Pydantic DTOs for `/graph/overview` and `/graph/detail/{cluster_id}` responses
- Backend value objects: `cluster_id` codec, opaque cursor, revision token, aggregate/projection policy
- Mirrored TypeScript types and request/response fixtures on the frontend
- Schema + serialization tests on both layers (strict TDD)
- Documentation-only compatibility assertions that `/graph/full` is unchanged

**Does not own**:
- Neo4j aggregation or detail queries
- `/graph/overview` and `/graph/detail/{cluster_id}` route handlers (#391)
- `GraphCMDB` / `NetworkVisualizer` migration (#392 / #393)
- Any redaction change to `/graph/full`
- OpenAPI-to-TypeScript code-generation pipeline

### Approach

Schema-first additive contract slice in **2 work-units**, per the exploration recommendation:

1. **Backend contracts**: `backend/schemas/graph.py` (or `backend/models/graph_dto.py`) Pydantic DTOs; `backend/contracts/` value objects (`cluster_id`, cursor, revision, aggregate/projection policy); `backend/tests/test_graph_contracts.py` for authorized/redacted/empty/paginated/hidden-absent serialization.
2. **Frontend mirrors**: `frontend/types/graph.ts` (or extend `frontend/types.ts`) TypeScript mirrors; `frontend/services/graphContract.ts` request/response fixtures; `frontend/__tests__/graphContract.test.ts` serialization tests that lock field names and null/omission rules against the backend fixtures.

Both work-units land before #391 begins. No Neo4j query, route handler, consumer migration, or `/graph/full` change ships inside #390.

### Requirements (from #390)
1. DTO/schema contracts for `GET /graph/overview`
2. DTO/schema contracts for `GET /graph/detail/{cluster_id}`
3. Keep `GET /graph/full` unchanged
4. Stable `cluster_id` semantics (axis derived from identifier)
5. Pagination/cursor/limit rules
6. `revision` / cache invalidation semantics
7. Non-enumerating hidden/absent cluster behavior
8. Visible-candidate-only search/filter target resolution
9. Aggregate disclosure rules + sensitive-field policy

### Hard constraints
- `/graph/full` unchanged (hard)
- Hidden = absent (hard)
- Aggregate suppression post-authorization (hard)
- Aggregate-breakdown permission gap — `graph:aggregate_breakdown:read` does not yet exist in `UserPermission`; document as prereq for #391

### Non-goals
- Neo4j queries, route handlers, consumer migration, `/graph/full` redaction, OpenAPI codegen

### Affected files (rough)
- new: `backend/schemas/graph.py`
- new: `backend/contracts/` (cluster_id, cursor, revision, policies)
- new: `backend/tests/test_graph_contracts.py`
- new: `frontend/types/graph.ts` (or extend `frontend/types.ts`)
- new: `frontend/services/graphContract.ts`
- new: `frontend/__tests__/graphContract.test.ts`

### Estimated footprint
~250–350 LOC, 6–8 files, single-PR budget (<400).
