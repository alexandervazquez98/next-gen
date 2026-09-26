# Proposal: cmdb(graph) runtime slice for LOD overview and detail APIs (#391, #392, #393)

## Problem

The CMDB graph Level-of-Detail (LOD) feature is split into two halves:

1. **Contract slice (#390, shipped in v1.17.6 / PR #468)** — backend value objects (`backend/contracts/`), Pydantic v2 DTOs (`backend/schemas/graph.py`), frozen JSON fixtures (`fixtures/graph-contracts/`), frontend TypeScript mirrors, and a spec coverage gate (9 REQs / 43 scenarios). This is the wire-authoritative shape.
2. **Runtime slice (#391, #392, #393, this proposal)** — the actual runtime behavior that consumes those contracts.

Without the runtime slice, the contracts are inert: there is no `GET /graph/overview` endpoint, no `GET /graph/detail/{cluster_id}` endpoint, `GraphCMDB` still fetches `/graph/full` for first paint, and consumers like `NetworkVisualizer` keep pressuring the full-graph payload path. The contracts also cannot be used to defend behavior without a reference implementation.

This proposal owns the runtime slice. It is split across three issues per the existing decomposition:

- **#391** — backend: implement the two endpoints, with auth/scoping pre-aggregation and disclosure policy enforcement
- **#392** — frontend: migrate `GraphCMDB` to overview-first loading
- **#393** — perf: migrate remaining `/graph/full` consumers away from the default large-topology path

## Scope

### Owns

- **#391** — `backend/routers/graph.py` (or new module) with `GET /graph/overview` and `GET /graph/detail/{cluster_id}` route handlers; aggregation Cypher/Postgres queries with authorization pre-aggregation; aggregate policy enforcement (tiered geographic precision); `/graph/full` byte-equality regression test stays green
- **#392** — `frontend/components/GraphCMDB.tsx` overview-first orchestration; overview query on mount (no initial `/graph/full`); detail hydration on click/expand or committed search/filter target; merge detail payloads as delimited subgraphs; fallback to `/graph/full` if LOD path is unavailable
- **#393** — audit of all `/graph/full` and `/api/graph/full` callers (`docs/refactoring/cmdb-graph-consumer-inventory.md`); migrate `NetworkVisualizer` and any other feasible consumers; preserve `/graph/full` as a compatibility endpoint

### Does not own

- Changing `/graph/full` shape or redaction semantics (hard rule, owned by #390 freeze)
- `cluster_id` codec, cursor codec, revision token, aggregate policy implementations (already in `backend/contracts/`, owned by #390)
- Pydantic DTO field changes (owned by #390 unless a runtime requirement forces a delta)
- Frontend TypeScript type changes (owned by #390 / PR #472 mirrors; runtime consumes them as-is)
- The Visual Relationship Editor's collapsed-cluster visualization (#214, deferred until #393 lands)
- Tunnel link visualization (`medium` field, `vpn` / `sd_wan` / `satellite`) — untouched

## Approach

Three sequential slices, each as a Feature Branch Chain (mirror of PR #468 pattern):

```
#391 — backend runtime
  ├── PR1: GET /graph/overview endpoint + tests
  ├── PR2: GET /graph/detail/{cluster_id} endpoint + tests
  └── PR3: disclosure + hidden/absent parity + tests

#392 — frontend GraphCMDB migration
  ├── PR1: overview-on-mount (no initial /graph/full)
  ├── PR2: detail hydration on click/expand + search/filter target
  └── PR3: fallback to /graph/full + remove zoom-triggered fetch

#393 — migrate remaining consumers
  ├── PR1: caller inventory (audit only, no code changes)
  └── PR2: migrate consumers based on audit (NetworkVisualizer first)
```

Each tracker PR closes the corresponding issue by supersession. Child PRs land < 400 LOC each (the repo's review budget).

## Requirements

### From #391

1. `GET /graph/overview` returns clusters with aggregates, post-authorization, with disclosure policy applied
2. `GET /graph/detail/{cluster_id}` returns bounded subgraph with cursor pagination
3. `/graph/full` shape and redaction semantics unchanged (byte-equality regression test stays green)
4. Authorization/scoping applied **before** aggregation
5. Hidden clusters and absent clusters are externally indistinguishable
6. Aggregate disclosure: low-cardinality values suppressed or bucketed per policy
7. Search/filter target resolution considers only visible authorized candidates
8. Bounded/paginated detail responses for large clusters

### From #392

1. Initial render uses the overview endpoint only — no hidden `/graph/full` queries
2. Detail subgraphs fetch on explicit click/expand or committed search/filter target
3. Detail payloads merge into the scene as **delimited** subgraphs (not silently with overview)
4. Zoom threshold does **not** trigger detail hydration in this slice
5. Fallback to `/graph/full` when LOD path is unavailable
6. No regression in `GraphCMDB.test.tsx`

### From #393

1. Caller inventory documents every consumer of `/graph/full` and `/api/graph/full`
2. Per-consumer decision: migrate (use overview/detail) or except (keep full graph with documented limits)
3. `NetworkVisualizer` migration if feasible
4. Polling/cache behavior normalized across consumers to avoid duplicate full-graph pressure
5. `/graph/full` remains a compatibility endpoint — no removal or deprecation

## Hard constraints

- `/graph/full` unchanged (hard — covered by `test_graph_full_snapshot.py`)
- Hidden ≡ absent externally (status code, body shape, timing, pagination, empty reasons)
- Auth/scoping happens before aggregation, not after
- `cluster_id` parse is case-insensitive with axis-derived display
- Cursor encodes principal hash so a privilege change invalidates pagination state
- Detail projection policy: sensitive metadata only with explicit permission
- Frontend initial paint does not call `/graph/full` (verifiable test)
- Aggregate-breakdown capability (`graph:aggregate_breakdown:read`) is the global gate; per-user scope via `User.aggregate_breakdown_regions: list[str]` selects which regions qualify for city-level geo precision (empty list = global breakdown; absent from list = silent downgrade to region tier)

## Non-goals

- OpenAPI-to-TypeScript code-generation pipeline
- Real-time topology updates via WebSocket (out of scope)
- Cross-cluster relationship reasoning (separate epic)
- Dynamic utilization overlay on physical links (separate #439 slice)

## Affected files (rough)

### #391 backend
- new: `backend/routers/graph_lod.py`
- new: `backend/repositories/graph_lod_repo.py`
- new: `backend/services/graph_lod_service.py`
- new: `backend/tests/test_graph_overview_aggregation.py`
- new: `backend/tests/test_graph_detail_retrieval.py`
- new: `backend/tests/test_graph_hidden_absent_parity.py`
- new: `backend/tests/test_graph_consumer_authorization.py`
- new: `backend/tests/test_graph_aggregate_disclosure.py`
- modify: `backend/main.py` (router registration)
- modify: `backend/tests/test_spec_coverage_graph.py` (extend scenarios if runtime behavior requires)

### #392 frontend
- modify: `frontend/components/GraphCMDB.tsx`
- new: `frontend/services/graphLod.ts` (overview + detail request builders, complement existing `graphContract.ts`)
- new: `frontend/__tests__/GraphCMDB.test.tsx`
- new: `frontend/__tests__/graphLod.test.ts`
- modify: `frontend/hooks/useGraphTopology.ts` (or equivalent query hook)

### #393 migration
- new: `docs/refactoring/cmdb-graph-consumer-inventory.md`
- modify: `frontend/components/NetworkVisualizer.tsx` (if migrated)
- new: `frontend/__tests__/NetworkVisualizer.test.tsx` (if migrated)
- modify: `docs/USER_GUIDE.md` (note on `/graph/full` deprecation path — informational, not removal)

## Estimated footprint

| Slice | LOC estimate | Files | Review budget risk |
|---|---|---|---|
| #391 backend | ~2000 (3 sub-PRs) | 9 new + 2 modified | Low per child PR |
| #392 frontend | ~1500 (3 sub-PRs) | 3 new + 2 modified | Low per child PR |
| #393 migration | ~500 audit + ~800 migration | 2 new + 2 modified | Low per child PR |
| **Total** | **~4800** | **~20** | Low (Feature Branch Chain) |

## Activation of dependent issues

- **#214** (visual editor scaling) — moves from `status:needs-review` to `status:approved` after #393 closes. The maintainer's downgrade comment explicitly says: *"We will re-activate when #393 is merged."*

## Open decisions for the maintainer

1. ~~Aggregate-breakdown permission~~ — **resolved**: `graph:aggregate_breakdown:read` permission is the global capability gate; per-user scope via `User.aggregate_breakdown_regions: list[str]`. Default: permission NOT seeded for any role (no user gets city-level breakdown by default); region list defaults to `[]` for all users. Operators/admins assign both explicitly. New column `aggregate_breakdown_regions TEXT[]` on `users` (Postgres) + `:User.aggregate_breakdown_regions` (Neo4j) with migration `007_user_aggregate_breakdown_regions.cypher`. Audit trail on changes (mirror `User.permissions` pattern in `backend/services/audit_service.py`).
2. **`NetworkVisualizer` migration** — feasible or does it have constraints that force except? Will be answered by #393 PR1 audit.
3. **Overview default cluster axis** — `location` is the first axis per epic #230. Confirm or extend (e.g., `tenant`) for first slice.