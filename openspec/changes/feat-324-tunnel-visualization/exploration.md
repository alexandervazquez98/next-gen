## Exploration: feat-324-tunnel-visualization

### Current State
Slice 1 primitives are present: frontend `GraphLink.medium` supports `vpn`, `sd_wan`, and `satellite`; category icon keys include `vpn_tunnel`, `sd_wan_tunnel`, `satellite_link`, and `vpn_hub`; backend link reads can expose `medium` for tunnel relationships; `vpn_hub` and `public_ip` exist backend-side. Slice 2 backend tunnel health is available through authenticated `GET /api/tunnels/{link_id}/health` and returns `status` as authority-only `UP`, `DOWN`, or `UNKNOWN` plus ICMP context. The frontend currently has no tunnel health types, query key, fetcher, hook, link-id encoder, bulk health aggregation, tooltip model, or tunnel-specific visual contract.

Current visualization surfaces use separate code paths. `NetworkVisualizer` fetches `/api/graph/full` directly every 5s and renders all links as generic white 3D lines. `MonitoringConsole` uses React Query through `useMonitoringConsoleData()`, renders Leaflet polylines from `/links`, and colors links by endpoint event severity only. `VisualRelationshipEditor` renders SVG lines using target node status and does not create or display link `medium`. `TopologyViewer` is the relationship topology currently reachable from `RelationshipManager`; `CIDetailModal` itself does not render a topology surface today. `GraphNode.public_ip` is not typed frontend-side and backend node reads appear to expose `public_ip` only inside `metadata`, not as a top-level field.

### Affected Areas
- `frontend/types.ts` — add tunnel health/ICMP/authority types, likely `GraphNode.public_ip`, and possibly a canonical tunnel visual state type.
- `frontend/services/queryResources.ts` — add `fetchTunnelHealth(linkId)` and response typing for `/tunnels/{link_id}/health`.
- `frontend/services/queryKeys.ts` — add a tunnel-health query key rooted per link id.
- `frontend/hooks/queries/` — add a tunnel health hook and/or shared tunnel-health map hook for visible tunnel links.
- `frontend/components/NetworkVisualizer.tsx` — replace generic tunnel link styling with tunnel icon/state styling and tooltip support; consider moving from direct `fetch` to query services if scope allows.
- `frontend/components/MonitoringConsole.tsx` — add VPN/SD-WAN/satellite-only topology toggle, filter nodes/links for map rendering, include tunnel-aware link rendering and map popup/tooltip content.
- `frontend/components/VisualRelationshipEditor.tsx` — display existing tunnel media and health styling in the SVG graph/existing links list; link creation currently cannot set `medium`.
- `frontend/components/TopologyViewer.tsx` and possibly `frontend/components/CIDetailModal.tsx` — apply the same tunnel visual contract where relationship topology is rendered; confirm whether CIDetailModal should embed/use TopologyViewer or remains unaffected.
- `frontend/components/RelationshipManager.tsx` — `LinkData` must carry optional `medium`; the topology launch path passes links into `TopologyViewer`.
- `frontend/utils/categoryIcons.ts` / `frontend/components/CategoryIcon.tsx` — existing icon catalog likely sufficient; may need a helper mapping `medium -> icon key` rather than new icons.
- `frontend/components/*.test.tsx`, `frontend/hooks/queries/*.test.tsx`, `frontend/services/queryResources.test.ts`, `frontend/types.test.ts` — add focused tests for mapping, filtering, tooltips, and query contract.
- `backend/services/node_service.py` and/or API contract docs — only if tooltip needs top-level `public_ip`; otherwise frontend must read `metadata.public_ip` safely.

### Approaches
1. **Shared frontend tunnel visual model** — create small pure helpers/types that map `GraphLink.medium` + `TunnelHealthResponse` + endpoint data into icon key, visual state, line style, and tooltip rows, then consume those helpers in each surface.
   - Pros: consistent contract across surfaces, easy unit testing, avoids duplicating the UNKNOWN/ICMP decision, keeps backend semantics intact.
   - Cons: needs careful integration because each surface renders differently (3D graph, Leaflet, D3 SVG, custom SVG topology).
   - Effort: Medium

2. **Surface-local tunnel rendering** — implement tunnel health fetch and styling independently inside each component.
   - Pros: fastest per component and fewer abstractions up front.
   - Cons: high drift risk, repeated UNKNOWN/ICMP semantics, harder to verify the “same visual contract” acceptance requirement.
   - Effort: Medium-High

3. **Backend-enriched graph payload** — extend graph/link reads to include latest tunnel health inline so all topology surfaces receive one payload.
   - Pros: fewer frontend requests and simpler rendering consumers.
   - Cons: expands Slice 3 into backend/API work, risks scoping/performance changes after Slice 2 intentionally exposed single-link reads, and may exceed the review budget.
   - Effort: High

### Recommendation
Use Approach 1. Keep Slice 3 frontend-first: add a shared tunnel visual/tooltip helper and React Query health hook(s) that call the existing single-link endpoint for visible tunnel links. Map backend `DOWN` to down styling, `UP` to active styling, and treat backend `UNKNOWN` plus ICMP context as a UI-only “attention/degraded-looking” state only if product explicitly approves wording that does not claim authority-down. Until that question is answered, specs should avoid saying ICMP makes the tunnel `DEGRADED` and instead define labels such as `UNKNOWN` or `UNKNOWN_WITH_CONTEXT`.

### Risks
- Product wording can accidentally contradict Slice 2 if the UI labels ICMP failure or missing public IP as backend `DEGRADED`/`DOWN`.
- Per-link health requests can become noisy on large topologies unless limited to visible tunnel links and cached/polled carefully.
- `public_ip` is not a frontend top-level field today; tooltip acceptance may require either reading `metadata.public_ip` or a small backend/frontend type contract update.
- `NetworkVisualizer` bypasses the shared API wrapper and React Query, so auth/cookie/error behavior may be inconsistent if not normalized.
- `VisualRelationshipEditor` cannot currently create/edit tunnel `medium`; displaying tunnel health may be possible without solving creation UX, but proposal must decide scope.
- CIDetailModal does not currently own a topology view; “where applicable” needs clarification before assigning implementation there.

### Ready for Proposal
Yes, with product clarification. The orchestrator should ask for a precise UI mapping for backend `UNKNOWN` and ICMP context before proposal/spec: whether the UI may show a separate warning/degraded visual for ICMP context while keeping the textual authority status as `UNKNOWN` or `UP`, and what label/copy should be used.
