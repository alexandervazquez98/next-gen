# Exploration: CMDB Graph Level of Detail

## Issue

GitHub issue #230: `perf(cmdb): plan large-scale graph level-of-detail mode`.

## Summary

The current CMDB topology visualization path can render clusters on the frontend, but it still fetches and prepares the full topology payload first. That means the first scalability bottleneck is not only visual rendering; it is also backend payload size, polling behavior, and frontend simulation over full node/link arrays.

## Current Flow

- `backend/routers/links.py`
  - Exposes `GET /graph/full` with optional `layer`, `location`, and `owner` filters.
  - No paging, level-of-detail, summary, or subgraph mode exists today.
- `backend/services/link_service.py`
  - `get_full_graph()` enforces user scoping and maps repository data into `{ nodes, links }`.
- `backend/repositories/topology_repo.py`
  - `get_filtered_graph_data()` returns full node/link Cypher results with security filters.
- `frontend/services/queryResources.ts`
  - `fetchGraphTopology()` always calls `/graph/full`.
- `frontend/hooks/queries/useGraphTopologyQuery.ts`
  - React Query polls topology every 30 seconds.
- `frontend/components/GraphCMDB.tsx`
  - Uses filtered topology plus a parallel unfiltered query for location options.
  - Already has location-based cluster rendering and aggregated cluster links.
- `frontend/components/NetworkVisualizer.tsx`
  - Calls `/api/graph/full` directly with short polling.

## Relevant Tests

- `backend/tests/test_routers_links.py`
  - Covers full graph endpoint behavior, scoping, node typing, medium field, and no-leak behavior.
- `backend/tests/test_topology_repo_nodes.py`
  - Covers repository-level query shape and filtering/scoping behavior.
- `frontend/components/__tests__/GraphCMDB.query.test.tsx`
  - Covers query usage and filter-driven topology calls.
- `frontend/hooks/queries/resourceQueries.test.tsx`
  - Covers `/graph/full` polling and shared query behavior.

## Key Discovery

`GraphCMDB.tsx` already contains a useful frontend-side cluster abstraction, but it is built after retrieving the full graph. A proper Level of Detail design should move the first view toward server-provided summaries and on-demand expansion.

## Recommended First Slice

Keep `/graph/full` backward-compatible. Add either:

1. a new overview endpoint, for example `/graph/overview`, or
2. a `view=overview` mode on a dedicated graph endpoint,

that returns cluster summaries and aggregate links for initial rendering. Then fetch detailed subgraphs only when the user explicitly expands a cluster or commits a search/filter target. Zoom-triggered detail loading is out of scope for this design slice.

## Risks

- High: if the backend still returns the full topology, frontend-only LOD will not solve large graph payload or compute cost.
- High: multiple frontend callers still fetch full topology, including `GraphCMDB` and `NetworkVisualizer`.
- Medium: `/graph/full` is an existing behavior contract for tests and possibly tooling; changing its response shape would cause regressions.
- Medium: any new endpoint must preserve existing authorization and public IP leakage guards.

## CodeGraph Note

The parent session detected `.codegraph/` exists. The exploration subagent reported CodeGraph was unavailable because `.codegraph/manifest.json` was missing and fell back to direct file reads.
