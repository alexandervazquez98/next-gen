# Design: cmdb(graph) runtime slice for LOD overview and detail APIs

## Architecture overview

The runtime slice sits between the existing `/graph/full` endpoint and the consumers that currently use it. Three layers:

1. **Router layer** — `backend/routers/graph_lod.py` exposes `GET /graph/overview` and `GET /graph/detail/{cluster_id}`. The existing `GET /graph/full` stays in its own router (likely `backend/routers/graph.py` already, or extracted). Both routers register through `backend/main.py`.

2. **Service layer** — `backend/services/graph_lod_service.py` orchestrates authorization/scoping, calls the repository, applies the aggregate policy, and shapes the response through the DTOs.

3. **Repository layer** — `backend/repositories/graph_lod_repo.py` runs the aggregation Cypher (Neo4j) for `/graph/overview` and the bounded subgraph query for `/graph/detail/{cluster_id}`.

The aggregate policy (`backend/contracts/aggregate_policy.py` shipped in v1.17.6) and the cursor codec (`backend/contracts/cursor.py`) are reused as-is. The `cluster_id` codec and `revision` token are inputs to the detail endpoint.

## Authorization/scoping pre-aggregation

**Hard rule**: authorization filters the candidate set **before** any aggregation runs. This prevents the following failure mode: aggregating over the full graph, then filtering out unauthorized CIs in the response, which leaks the existence of hidden clusters via aggregate counts.

Flow for `/graph/overview`:

```
1. Read principal from request (session/JWT).
2. Resolve visible CI set for principal (uses existing authorization layer).
3. Run aggregation Cypher restricted to visible CI set.
4. Apply aggregate_policy: derive SafeGeoPrecision from visible count.
5. Shape response through Pydantic DTOs (omit sensitive fields).
```

Flow for `/graph/detail/{cluster_id}`:

```
1. Parse cluster_id (case-insensitive, axis-derived).
2. Resolve visible CI set.
3. If cluster's root CIs are not visible to principal → respond as hidden ≡ absent.
4. Run bounded subgraph query (limit + cursor).
5. Apply DetailProjectionPolicy to each node (sensitive metadata only with permission).
6. Shape response through Pydantic DTOs.
```

## Hidden ≡ absent parity

The response for a cluster that exists but is hidden must be **externally indistinguishable** from a cluster that does not exist. Specifically:

- Status code: `200` with `cluster: null` + `empty_reason: "hidden_absent"` (not `404` for absent — that would leak existence via timing)
- Body shape: identical field set
- Pagination: identical cursor format and behavior
- Empty reasons: same enum values (`none`, `no_visible_members`, `hidden_absent`, `unavailable`)

The body must never carry an "absent vs hidden" discriminator that an attacker could probe with timing or content differences. A regression test in `test_graph_hidden_absent_parity.py` enforces this.

## Aggregate policy tiers

The policy (`backend/contracts/aggregate_policy.py`) selects one of three precision tiers per cluster:

| Tier | When | What is returned |
|---|---|---|
| `none` | visible count < `minimum_count` (default 5) | aggregate suppressed, only count + empty reason |
| `region` | visible count < `minimum_count * 4` | aggregates bucketed to region level |
| `city` | visible count >= `minimum_count * 4` AND principal has `graph:aggregate_breakdown:read` AND (region is in `principal.aggregate_breakdown_regions` OR `principal.aggregate_breakdown_regions == []`) | full city-level aggregates |
| `city_without_breakdown` | visible count >= `minimum_count * 4` but principal lacks permission | bucketed, same body shape as `region` |

The tiers are externally indistinguishable beyond what the principal is authorized to see — a non-privileged user cannot detect whether they would see city-level data if they had the permission.

## Cursor pagination

The cursor codec (`backend/contracts/cursor.py`) encodes:

- `v: 1` (version)
- `cluster_id`
- `filters_hash` (sha256 of canonical JSON of filters, first 16 hex chars)
- `revision` (server-side revision token at time of issuance)
- `principal_hash` (sha256 of principal identity at time of issuance)
- `nonce` (random)

The cursor is base64url-encoded JSON. Decode failures raise `InvalidCursorError` (400). Stale cursors (revision changed) raise `StaleCursorError` (409 with current revision in body). Privilege changes (principal hash mismatch) raise `PermissionChangedError` (400, instructing client to refresh).

This means a long-paginated session cannot leak data across a permission boundary — the principal hash in the cursor invalidates the cursor if the user's permissions change.

## Frontend GraphCMDB orchestration

State machine for `GraphCMDB`:

```
INITIAL
  ↓ (mount)
OVERVIEW_LOADING → OVERVIEW_READY
                          ↓ (click cluster | expand | search/filter target committed)
                          DETAIL_LOADING → DETAIL_READY (merge as delimited subgraph)
                                            ↓ (clear selection)
                                            OVERVIEW_READY
                          ↑ (LOD path fails)
                          FALLBACK_TO_FULL
```

Hard rule: from `INITIAL`, the only network call is `/graph/overview`. `/graph/full` is called **only** as a fallback when the overview endpoint fails (network error or 5xx). A regression test asserts no `/graph/full` call appears in the initial-load network log.

Search/filter target resolution goes through `/graph/detail/{cluster_id}` (or `/graph/overview?filter=...`) — never `/graph/full`. The backend's visible-candidate-only search contract (from #390 DTOs) is consumed as-is.

Delimited subgraph merge: the detail payload renders as a separate sub-scene adjacent to the overview, not merged silently. Operators can see which CIs came from the detail fetch (visual cue: dashed boundary or labeled origin).

Zoom threshold is **not** a trigger for detail hydration. Operators explicitly click a cluster or commit a search/filter to expand detail.

## Consumer migration strategy (#393)

Audit-first pattern: the first sub-PR is a caller inventory only, no code changes. Output: `docs/refactoring/cmdb-graph-consumer-inventory.md` with a table:

| Consumer | Path | Current behavior | Decision | Reason |
|---|---|---|---|---|
| `GraphCMDB` | `frontend/components/GraphCMDB.tsx` | `/graph/full` on mount | migrate | covered by #392 |
| `NetworkVisualizer` | `frontend/components/NetworkVisualizer.tsx` | `/api/graph/full` | TBD by audit | depends on usage pattern |
| ... | ... | ... | ... | ... |

After audit, the second sub-PR implements migrations. `NetworkVisualizer` is the highest-priority candidate; if it has constraints that prevent migration (e.g., it needs the full topology for some downstream calculation), the audit explicitly excepts it with documented limits.

`/graph/full` remains a compatibility endpoint — no removal, no deprecation. Future deprecation decisions happen in a separate proposal.

## Trade-offs and rejected alternatives

- **Single big PR for #391** — rejected: 2000+ LOC would exceed the 400-line review budget and mix orthogonal concerns (overview vs detail vs parity).
- **Stream-based aggregation instead of pagination** — rejected: would require per-cluster streaming connections, complex client state, no benefit over cursor pagination for bounded clusters.
- **GraphQL gateway for the two endpoints** — rejected: introduces a new layer with no current adoption in the repo; the simple REST endpoints match the existing `/graph/*` API surface.
- **Real-time updates via WebSocket** — rejected for this slice: not in scope. Topology updates continue to use existing polling/cache behavior.
- **Auto-zoom-triggered detail hydration** — rejected: violates the hard rule from #392. Zoom is a UI affordance, not an intent signal.

## Risks

1. **Authorization layer performance** — running the visible-set resolution per request may add latency. Mitigation: cache the principal → visible-set mapping with TTL matching session lifetime.
2. **Cursor invalidation rate** — if `revision` changes frequently (e.g., topology edits), clients see `StaleCursorError` often. Mitigation: emit revisions only on schema-affecting changes (not on every node mutation).
3. **`NetworkVisualizer` constraints** — if audit reveals hard constraints, #393 PR2 may need to be split further or scoped down.
4. **Frontend bundle size** — adding overview-first orchestration and delimited subgraph merge may inflate `GraphCMDB` and dependent bundles. Mitigation: code-split detail hydration into a separate chunk.