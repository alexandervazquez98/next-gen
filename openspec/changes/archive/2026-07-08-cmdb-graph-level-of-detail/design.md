# CMDB Graph Level-of-Detail Design

This design keeps `/graph/full` unchanged and introduces an overview-first topology path for large CMDB graphs. The first implementation slices should render location-level clusters from a summary payload, then fetch detailed subgraphs only after explicit operator intent: cluster click/expand, or committed search/filter context. No application code is changed by this design slice.

## Design decisions

| Area | Decision |
|---|---|
| Compatibility | Keep `GET /graph/full` response shape and polling behavior unchanged for existing consumers. |
| First paint | Add a dedicated overview contract for location-cluster summaries instead of reusing full node/link arrays. |
| Detail loading | Add a dedicated detail/subgraph contract keyed by cluster/segment and current filters. |
| Initial cluster axis | Location is the only required first-slice axis. Use stable fallback bucket `Unassigned` for missing location metadata. |
| Triggers | Detail loads only on click/expand and committed search/filter targeting. Zoom threshold expansion is out of scope. |
| Security | Overview and detail MUST share the same principal, tenant/location scope, filtering, hidden/absent cluster response semantics, and aggregate suppression policy. Overview never includes raw sensitive fields; detail reuses the existing authorized projection helper/policy used by `/graph/full` once confirmed. |
| Rollout | Ship additive endpoints/services first, migrate `GraphCMDB` behind a fallback path, leave `NetworkVisualizer` on `/graph/full` until explicitly migrated. |

## Current architecture context

Current graph loading is full-payload first:

- `backend/routers/links.py` exposes `GET /graph/full` with optional `layer`, `location`, and `owner` filters.
- `backend/services/link_service.py#get_full_graph()` maps repository results into `{ nodes, links }` and includes `public_ip` in node metadata today.
- `backend/repositories/topology_repo.py#get_filtered_graph_data()` queries all matching CI nodes and links with location scoping for non-admin users.
- `frontend/services/queryResources.ts#fetchGraphTopology()` always calls `/graph/full`.
- `frontend/hooks/queries/useGraphTopologyQuery.ts` polls that full topology every 30 seconds.
- `frontend/components/GraphCMDB.tsx` already computes location clusters client-side after full hydration.
- `frontend/components/NetworkVisualizer.tsx` calls `/api/graph/full` directly and polls every 5 seconds.

The design moves the scalability boundary from client-side clustering after full hydration to server-provided overview and demand-driven detail.

## API contract strategy

### Existing compatibility endpoint

`GET /graph/full` remains unchanged.

```http
GET /graph/full?layer=router&location=DC-1&owner=NOC
```

Response stays the current shape and existing semantics. The sample below is compatibility documentation for the current full topology shape; this LOD design does not introduce new `/graph/full` redaction behavior.

```json
{
  "nodes": [
    {
      "id": "ci-1",
      "label": "edge-01",
      "type": "router",
      "status": "ACTIVE",
      "location": { "lat": -34.6, "long": -58.4 },
      "location_name": "DC-1",
      "ip": "10.0.0.1",
      "public_ip": "203.0.113.10",
      "metrics": [],
      "metadata": { "id": "ci-1", "location_name": "DC-1" }
    }
  ],
  "links": [
    { "source": "ci-1", "target": "ci-2", "relationship": "CONNECTS_TO" }
  ]
}
```

No follow-up implementation slice may change this response shape or existing semantics as part of LOD rollout. If a stronger redaction policy is required for `/graph/full`, that must be handled as a separate security change outside issue #230.

### New overview endpoint

Prefer an additive endpoint over a mode flag because it is easier to cache, monitor, and migrate without weakening `/graph/full` semantics.

```http
GET /graph/overview?axis=location&layer=<csv>&location=<csv>&owner=<csv>&cursor=<opaque>
```

Design-level response:

```json
{
  "axis": "location",
  "filters": {
    "layer": ["router"],
    "location": ["DC-1", "DC-2"],
    "owner": []
  },
  "generated_at": "2026-07-08T12:00:00Z",
  "revision": "topology:1720440000:42",
  "aggregate_policy": {
    "minimum_count": 5,
    "low_cardinality_mode": "suppress_or_bucket",
    "breakdowns_role_gated": true
  },
  "clusters": [
    {
      "id": "location:DC-1",
      "axis": "location",
      "key": "DC-1",
      "label": "DC-1",
      "node_count": 1240,
      "link_count": 3100,
      "status_counts": { "ACTIVE": 1180, "WARNING": 45, "CRITICAL": 15, "suppressed": false },
      "type_counts": { "router": 120, "switch": 360, "server": 760, "other": 0 },
      "geo": { "lat": -34.6, "long": -58.4, "quality": "derived_centroid", "precision": "city" },
      "has_more_detail": true,
      "detail_href": "/graph/detail/location%3ADC-1"
    },
    {
      "id": "location:__unassigned__",
      "axis": "location",
      "key": "__unassigned__",
      "label": "Unassigned",
      "node_count": 32,
      "link_count": 12,
      "status_counts": { "breakdown_suppressed": true },
      "type_counts": { "breakdown_suppressed": true },
      "geo": null,
      "has_more_detail": true,
      "detail_href": "/graph/detail/location%3A__unassigned__"
    }
  ],
  "inter_cluster_links": [
    {
      "source_cluster_id": "location:DC-1",
      "target_cluster_id": "location:DC-2",
      "relationship": "CONNECTS_TO",
      "count": 48,
      "weight": 48,
      "medium_counts": { "breakdown_suppressed": true }
    }
  ],
  "legend": {
    "statuses": ["ACTIVE", "WARNING", "CRITICAL"],
    "axis_label": "Location"
  },
  "page": {
    "has_more": false,
    "next_cursor": null
  }
}
```

Contract notes:

- `clusters[].id` MUST be stable for the same axis/key pair and safe to pass to the detail endpoint.
- `inter_cluster_links` MUST aggregate only links visible to the caller.
- Overview MUST NOT include per-node sensitive metadata, including `public_ip`, external DNS names, NAT addresses, MAC addresses, precise endpoint coordinates, serial numbers, provider account identifiers, or comparable infrastructure identifiers.
- `geo` is optional and must use safe aggregate/derived coordinates only. It must not disclose hidden node coordinates; low-cardinality locations must use coarse precision, suppression, or no geo value.
- Aggregate disclosure policy is mandatory: exact cluster `node_count`, cluster `link_count`, status/type/medium counts, edge weights, and geo breakdowns are returned only when each disclosed bucket/value has at least `minimum_count = 5` visible records or the principal has explicit aggregate-breakdown permission. Otherwise values are suppressed, rounded, ranged, or folded into non-count `other`/`suppressed` metadata.
- `revision` is an opaque cache/invalidation token. It should change when the visible topology subset changes.
- Pagination is optional for the first slice but the response reserves `page` for very high cluster counts.

### New detail/subgraph endpoint

`cluster_id` encodes the axis using the stable format `<axis>:<url-safe-key>`. For the first slice, only `location:*` cluster ids are accepted. The detail endpoint MUST derive `axis` from `cluster_id`; an `axis` query parameter is not part of the public contract. If a future compatibility layer accepts `axis`, contradictory values MUST fail validation with `400 invalid_request` before authorization-sensitive lookup.

```http
GET /graph/detail/{cluster_id}?layer=<csv>&location=<csv>&owner=<csv>&search=<term>&cursor=<opaque>&limit=500
```

Design-level authorized response:

```json
{
  "cluster": {
    "id": "location:DC-1",
    "axis": "location",
    "key": "DC-1",
    "label": "DC-1"
  },
  "filters": {
    "layer": ["router"],
    "location": ["DC-1"],
    "owner": [],
    "search": "edge"
  },
  "generated_at": "2026-07-08T12:00:03Z",
  "revision": "topology:1720440003:43",
  "nodes": [
    {
      "id": "ci-1",
      "label": "edge-01",
      "type": "router",
      "status": "ACTIVE",
      "location": { "lat": -34.6, "long": -58.4 },
      "location_name": "DC-1",
      "ip": "10.0.0.1",
      "public_ip": "203.0.113.10",
      "metrics": [],
      "metadata": { "id": "ci-1", "location_name": "DC-1" },
      "parent_cluster_id": "location:DC-1",
      "projection": {
        "restricted_fields_redacted": false
      }
    }
  ],
  "links": [
    {
      "source": "ci-1",
      "target": "ci-2",
      "relationship": "CONNECTS_TO",
      "medium": "vpn",
      "parent_cluster_ids": ["location:DC-1"],
      "boundary": "internal"
    },
    {
      "source": "ci-1",
      "target": "ci-9",
      "relationship": "CONNECTS_TO",
      "parent_cluster_ids": ["location:DC-1", "location:DC-2"],
      "boundary": "external_stub"
    }
  ],
  "empty_reason": null,
  "page": {
    "has_more": true,
    "next_cursor": "opaque-next-detail-cursor",
    "limit": 500
  }
}
```

Empty result semantics for visible clusters with no filter/search matches:

```json
{
  "cluster": { "id": "location:DC-1", "axis": "location", "key": "DC-1", "label": "DC-1" },
  "nodes": [],
  "links": [],
  "empty_reason": "no_matches",
  "page": { "has_more": false, "next_cursor": null, "limit": 500 }
}
```

Hidden or absent cluster semantics use one indistinguishable response:

```json
{
  "cluster": null,
  "nodes": [],
  "links": [],
  "empty_reason": "unavailable",
  "page": { "has_more": false, "next_cursor": null, "limit": 500 }
}
```

Allowed `empty_reason` values:

- `no_matches`: the cluster is visible, but the committed filters/search hide all visible nodes.
- `unavailable`: the cluster id is outside the caller's visible topology or does not exist. The same status code, body shape, headers, timing budget, and absence of cluster metadata MUST be used for hidden and absent clusters.

Sensitive-field projection examples:

These examples define the intended detail projection behavior after a follow-up implementation confirms and reuses the existing authorized projection helper/policy used by `/graph/full`. They do not change `/graph/full` behavior in this design slice.

Authorized detail node for a principal with explicit sensitive-metadata permission under the confirmed existing projection policy:

```json
{
  "id": "ci-1",
  "ip": "10.0.0.1",
  "public_ip": "203.0.113.10",
  "metadata": { "external_dns": "edge-01.example.net", "nat_ip": "198.51.100.7" },
  "projection": { "restricted_fields_redacted": false }
}
```

Redacted detail node for a principal without that permission, if supported by the confirmed existing projection policy:

```json
{
  "id": "ci-1",
  "ip": "10.0.0.1",
  "public_ip": null,
  "metadata": { "external_dns": null, "nat_ip": null },
  "projection": {
    "restricted_fields_redacted": true,
    "redacted_fields": ["public_ip", "metadata.external_dns", "metadata.nat_ip"]
  }
}
```

Detail contract notes:

- Detail nodes SHOULD reuse existing node field semantics so the frontend can merge detail without introducing a second node renderer.
- `public_ip` and comparable sensitive metadata in detail MUST follow the confirmed existing authorized projection helper/policy used by `/graph/full`. If the current full-graph policy needs stronger redaction, that is a separate security change, not part of the LOD rollout.
- Overview responses MUST never include sensitive node metadata, even for authorized principals.
- Boundary links may be returned as `external_stub` when the other endpoint is outside the expanded cluster but visible enough for context. Hidden endpoints MUST NOT be leaked through stubs.
- Large clusters MUST support pagination or bounded limits before production rollout.

## Backend design

### Router responsibilities

Add two read-only routes in the topology router layer:

- `GET /graph/overview`
  - validates `axis=location` for first slice,
  - accepts the same filter vocabulary as `/graph/full`,
  - passes the authenticated principal to the service layer,
  - returns overview DTOs only.
- `GET /graph/detail/{cluster_id}`
  - validates cluster id format and derives axis from the id,
  - rejects contradictory or unsupported axis information before lookup,
  - accepts same filters plus optional committed `search`, `cursor`, and `limit`,
  - passes authenticated principal to the service layer,
  - returns a bounded subgraph DTO.

`GET /graph/full` remains routed to the current full-graph service.

### Service responsibilities

Introduce service-level operations conceptually equivalent to:

- `get_graph_overview(current_user, axis="location", layer=None, location=None, owner=None, cursor=None)`
- `get_graph_detail(current_user, cluster_id, layer=None, location=None, owner=None, search=None, cursor=None, limit=500)`

The service layer owns:

- computing `is_admin` and `allowed_locations` exactly as the current full graph path does,
- returning empty payloads for non-admin users with no allowed locations,
- resolving search/filter match counts only after authorization filtering and only over visible candidates plus allowed public axes/labels,
- ensuring hidden candidates never affect ambiguity decisions, no-match behavior, detail hydration, pagination, timing, status codes, or response body shape,
- mapping repository rows to DTOs,
- deriving stable cluster ids (`location:<url-safe-key>`) and deriving the axis from those ids for detail requests,
- building `revision` tokens,
- applying the confirmed existing authorized projection helper/policy to detail payloads,
- returning the same externally observable response for hidden and absent clusters,
- avoiding any mutation side effects.

### Repository responsibilities

Add repository queries that do not materialize the entire graph unless explicitly requested:

- overview cluster aggregation by `n.location_name`, including node counts, status counts, type counts, and optional derived geo summaries;
- aggregate inter-cluster links by source/target cluster and relationship/medium;
- detail node query for a selected location cluster with current filters/search/limit;
- detail link query for visible internal links and bounded external stubs.

Security filtering must be composed before aggregation and search/filter resolution. For non-admin users, location scope must constrain overview, detail, and search matching in a way that cannot expose hidden cluster existence through counts, labels, edge weights, match counts, ambiguity states, no-match states, pagination metadata, timing, or detail-hydration decisions.

### Security parity approach

Use one shared graph visibility policy for all graph read paths:

```text
principal + allowed_locations + user filters + field projection
  -> visible graph subset
  -> overview aggregation OR detail materialization OR full graph mapping
```

Parity requirements for implementation slices:

- A non-admin with `allowed_locations == []` receives empty overview and empty detail results, matching current full graph behavior.
- Overview counts and inter-cluster weights are computed only after tenant/location filtering.
- Restricted fields such as `public_ip` are never derivable from overview aggregates, and detail uses the same confirmed authorized projection helper/policy as `/graph/full`.
- Search/filter parameters cannot bypass location scope.
- Search/filter ambiguity and match counts are computed only over visible candidates and allowed public axes/labels after authorization filtering.
- If exactly one visible candidate matches, detail behavior is based on that visible match even when hidden candidates also exist.
- If zero visible candidates match, the no-match behavior is identical whether hidden candidates exist or not.
- Unknown and hidden `cluster_id` values MUST NOT reveal whether the cluster exists globally; both cases use the same status code, response body shape, absence of cluster metadata, headers, and timing budget.

### Sensitive-field and aggregate disclosure policy

| Data category | Authorized principal | Principal without permission | Overview behavior |
|---|---|---|---|
| `public_ip` | Detail MAY return it for visible nodes only according to the confirmed existing authorized projection helper/policy used by `/graph/full`. | Detail MUST follow that same confirmed policy. Any stronger `/graph/full` redaction is separate security work. | Never returned. |
| Comparable sensitive metadata (`external_dns`, NAT/public addresses, MAC addresses, serial numbers, provider account identifiers, precise endpoint coordinates) | Detail MAY return it for visible nodes only according to the confirmed existing authorized projection helper/policy used by `/graph/full`. | Detail MUST follow that same confirmed policy. Any stronger `/graph/full` redaction is separate security work. | Never returned. |
| Cluster `node_count` / `link_count` | Exact counts MAY be returned when the count is at least 5 visible records or the principal has `graph:aggregate_breakdown:read`. | Counts below 5 MUST be suppressed, rounded, or represented as safe ranges/non-count metadata. | Same rule. |
| Status/type/medium counts and link weights | Exact buckets MAY be returned when each bucket has at least 5 visible records or the principal has `graph:aggregate_breakdown:read`. | Buckets below 5 MUST be suppressed, rounded, or folded into non-count `other`/`suppressed` metadata. | Same rule. |
| Geo summaries | MAY use coarse derived aggregate coordinates when backed by at least 5 visible nodes or aggregate-breakdown permission. | MUST be omitted or coarsened for low-cardinality clusters/links. | Same rule; never precise endpoint coordinates. |

The implementation must apply suppression after authorization filtering. Suppressed buckets MUST NOT expose hidden values through totals, labels, inter-cluster weights, tooltips, legends, or pagination metadata.

## Frontend orchestration design

### Query model

Add separate frontend resource/query concepts in follow-up implementation slices:

- `fetchGraphOverview(filters, { axis: "location" })`
- `fetchGraphDetail(clusterId, filters, { search, cursor, limit })`
- `useGraphOverviewQuery(filters)`
- `useGraphDetailQuery(clusterId, filters, searchContext)`

Keep `fetchGraphTopology()` and `useGraphTopologyQuery()` on `/graph/full` for compatibility until consumers migrate.

### State model

`GraphCMDB` should move to an overview-first state shape:

```ts
type GraphLodState = {
  mode: "overview" | "mixed" | "fallbackFull";
  axis: "location";
  filters: {
    layer: string[];
    location: string[];
    owner: string[];
  };
  overviewRevision?: string;
  clustersById: Record<string, OverviewCluster>;
  interClusterLinks: OverviewClusterLink[];
  expandedClusterIds: string[];
  detailByClusterId: Record<string, {
    status: "idle" | "loading" | "ready" | "error" | "empty";
    revision?: string;
    nodes: GraphNode[];
    links: GraphLink[];
    page?: { has_more: boolean; next_cursor?: string | null };
    error?: string;
  }>;
  committedSearch?: {
    term: string;
    targetClusterId?: string;
  };
};
```

Render flow:

1. Initial page load requests `/graph/overview?axis=location`.
2. The scene renders cluster nodes and aggregate inter-cluster links.
3. Click/expand on a cluster sets `expandedClusterIds` and fetches detail for that cluster only.
4. Detail nodes/links mount inside or around the selected cluster while overview clusters remain as navigation context.
5. Search/filter commits update overview context first. Resolution is computed only over visible candidates and allowed public axes/labels after authorization filtering.
6. Detail fetches only when the authorized visible result set resolves to exactly one visible cluster or the operator explicitly selects one visible cluster from multiple visible results. Hidden candidates must not change this behavior.
7. Multiple visible, no-visible-match, or ambiguous-visible search/filter results stay in overview/search-results mode and MUST NOT hydrate the full topology.
8. If overview fails or the feature flag is disabled, the component falls back to existing `/graph/full` behavior.

### Trigger matrix

| Operator action | Overview refetch | Detail fetch | Notes |
|---|---:|---:|---|
| Initial topology page load | Yes | No | First paint is summary only. |
| Cluster click/expand | No, unless stale | Yes | Fetch selected cluster detail only. |
| Search commit matching exactly one visible cluster | Maybe | Yes | Compute matches after authorization filtering only; fetch detail for that visible target even if hidden candidates also exist. |
| Search/filter matching multiple visible clusters | Yes | No | Keep overview/search result set; require explicit visible-cluster selection before detail fetch. |
| Search/filter matching no visible clusters | Yes | No | Show the same empty state and do not fetch detail or `/graph/full`, regardless of whether hidden matches exist. |
| Ambiguous search/filter term | Yes | No | Ambiguity is based only on visible candidates and allowed public axes/labels; ask for refinement or explicit visible-cluster selection. |
| Filter commit changing layer/location/owner | Yes | Yes, only after exactly one visible target is resolved or explicitly selected | Reset stale details that no longer match filters. |
| Manual refresh / polling tick | Yes | Conditional | Refresh expanded detail only when revision changes or detail is visible. |
| Zoom/pan | No | No | Automatic zoom-threshold expansion is out of scope. |
| `NetworkVisualizer` route | No change | No change | Continue `/api/graph/full` until a separate migration slice. |

### Merge behavior

- Overview clusters remain canonical for cluster counts and layout.
- Detail nodes use existing graph node ids and are merged by node id.
- Detail links are merged by deterministic edge identity: `source + target + relationship + medium?`.
- When filters change, detail caches whose request context no longer matches MUST be invalidated or marked stale.
- Expanded detail should persist only while the active filter/search context is compatible with the detail request that produced it.

## Polling, cache, and invalidation rules

### Overview polling

- Replace `GraphCMDB`'s initial full topology polling with overview polling.
- Start with the current 30-second interval as a compatibility baseline unless performance tests prove a different cadence.
- Use React Query keys that include `axis`, `layer`, `location`, and `owner`.
- Treat `revision` changes as the signal to reconcile cluster counts and invalidate incompatible detail caches.

### Detail cache

- Detail query keys include `cluster_id` (which encodes axis), filters, committed search, cursor, and limit.
- Detail should be fetched only when the cluster is expanded or search/filter context requires it.
- Do not poll all known clusters. Poll only visible expanded detail, and only while mounted.
- On overview revision change:
  - keep compatible expanded cluster ids,
  - mark their detail stale,
  - refetch visible detail lazily or on next focus/poll tick,
  - drop detail for clusters no longer present in overview.

### Fallback cache behavior

If overview/detail endpoints are unavailable, disabled, or return a contract error:

- `GraphCMDB` may fall back to `useGraphTopologyQuery()` and the existing client-side cluster behavior.
- Existing `NetworkVisualizer` behavior remains untouched.
- Fallback should be observable through logs/telemetry so rollout issues are visible.

## Migration and rollout sequence

1. **Contract finalization**
   - Confirm endpoint names, DTO field names, pagination bounds, hidden/absent cluster equivalence, visible-only search resolution, aggregate suppression, and detail sensitive-field projection policy.
   - Add OpenAPI/Pydantic/TypeScript DTO definitions in implementation planning.
2. **Backend additive rollout**
   - Add overview/detail routes and services without changing `/graph/full`.
   - Add repository aggregation/detail queries with shared visibility policy.
   - Add security parity tests before frontend migration.
3. **Frontend dual-path rollout**
   - Add overview/detail fetchers and query hooks.
   - Gate `GraphCMDB` LOD mode behind a feature flag or safe capability detection.
   - Preserve full-graph fallback in the component.
4. **Consumer migration**
   - Migrate `GraphCMDB` first because it already has location-cluster rendering.
   - Leave `NetworkVisualizer` on `/graph/full` until a dedicated route-specific design or migration slice.
5. **Stabilization**
   - Compare full vs overview/detail visibility under representative roles and filters.
   - Monitor endpoint latency, payload size, UI first paint, detail fetch errors, and fallback rate.

Rollback is simple because all contracts are additive: disable the LOD feature flag and continue using `/graph/full`.

## Verification strategy for future implementation slices

### Backend verification

- `/graph/full` regression tests prove the existing response shape remains unchanged.
- Overview endpoint tests cover location clusters, counts, aggregate inter-cluster weights, filters, empty scope, low-cardinality suppression, and unknown/missing locations.
- Detail endpoint tests cover explicit cluster detail, search/filter narrowing, pagination, `no_matches`, hidden/absent `unavailable` equivalence, axis-derived cluster id validation, and boundary links.
- Security parity tests compare the visible node/link universe across full, overview, and detail for admin, scoped non-admin, and empty-scope users.
- Restricted-field tests verify detail projection reuses the confirmed existing authorized projection helper/policy used by `/graph/full`; any stronger `/graph/full` redaction tests belong to a separate security change.
- Aggregate disclosure tests verify status/type/medium counts, link weights, and geo summaries are suppressed or bucketed below the minimum safe count.

### Frontend verification

- Query tests prove initial `GraphCMDB` LOD render calls overview, not `/graph/full`.
- Interaction tests prove cluster click/expand triggers exactly one cluster detail request.
- Search/filter tests prove match counts and ambiguity are computed only over authorized visible candidates and allowed public axes/labels: exactly one visible match triggers targeted detail fetch even if hidden candidates exist; zero visible matches produce identical no-match behavior with or without hidden candidates; multiple visible or ambiguous visible matches do not hydrate detail or full topology.
- Zoom/pan tests prove no detail request fires from zoom threshold behavior.
- Fallback tests prove the existing full topology path still renders when overview/detail is disabled or fails.

### Performance verification

- Measure first-paint payload size and render time for large fixture graphs.
- Assert overview payload is bounded by cluster cardinality, not CI cardinality.
- Assert detail requests are bounded by the selected cluster/filter and configured limit.

## Non-goals

- No application code implementation in this change.
- No change to `/graph/full` response shape or semantics.
- No automatic zoom-threshold detail expansion.
- No realtime streaming topology updates.
- No ML-based or dynamic clustering beyond the first-slice location axis.
- No visual redesign of `GraphCMDB` or `NetworkVisualizer`.
- No migration of `NetworkVisualizer` unless a later slice explicitly scopes it.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Overview/search behavior leaks hidden topology | High | Apply visibility filters before aggregation and search resolution, suppress/bucket low-cardinality aggregates, compute ambiguity only over visible candidates, and add scoped parity tests. |
| Detail endpoint becomes another full graph path | High | Require cluster id, search/filter bounds, pagination, and limit enforcement. |
| Hidden cluster enumeration through detail lookup | High | Return identical externally observable `unavailable` responses for hidden and absent clusters, with no cluster metadata. |
| Sensitive metadata leaks through projection-policy drift | High | Confirm and reuse the existing authorized projection helper/policy from `/graph/full` for detail; overview never returns raw sensitive fields. Treat stronger `/graph/full` redaction as separate security work. |
| Frontend keeps parallel full topology query for filter options | Medium | Replace location options with overview/metadata-compatible source during `GraphCMDB` migration. |
| `NetworkVisualizer` continues high-frequency full polling | Medium | Leave compatible for now; plan a separate migration because route behavior differs. |
| Cache invalidation causes stale expanded details | Medium | Use overview `revision`, request-context keys, and stale marking on filter/revision changes. |
| Contract overfits location axis | Low | Encode axis in `cluster_id` and only accept `location:*` in the first slice. |

## Next implementation slices

1. **Backend contracts and DTOs**: define Pydantic response models, endpoint validation, and shared visibility helpers.
2. **Backend queries and tests**: implement aggregation/detail repository paths with security parity coverage.
3. **Frontend query layer**: add overview/detail fetchers, query keys, and fallback-aware hooks.
4. **GraphCMDB migration**: switch initial render to overview, add explicit expansion/search detail orchestration, preserve fallback.
5. **Operational hardening**: add telemetry, performance fixtures, and rollout/canary controls.
