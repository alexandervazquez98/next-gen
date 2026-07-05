# Proposal: Tunnel Visualization

## Intent

Expose Slice 2 tunnel health in frontend topology/monitoring surfaces without changing authority semantics: ICMP/public-IP context informs badges and tooltips only, never authoritative `DEGRADED` or `DOWN`.

## Scope

### In Scope
- Shared frontend tunnel visual model/helper for `medium`, health, icon, state, styling, and tooltip rows.
- Health query/fetch/hook strategy for visible tunnel links using `GET /api/tunnels/{link_id}/health` with bounded polling/cache guardrails.
- Tunnel-aware rendering in NetworkVisualizer, MonitoringConsole filter/topology, VisualRelationshipEditor, TopologyViewer/RelationshipManager, and CIDetailModal topology context.
- VisualRelationshipEditor create/edit support for tunnel `medium` (`vpn`, `sd_wan`, `satellite`) plus existing-link display.
- Minimal API/frontend contract promotion for top-level `public_ip` only on already-authorized node/graph/topology payloads, with server-side scoping tests for admin, non-admin empty scope, and non-admin limited scope.

### Out of Scope
- Backend tunnel-health normalization changes or ICMP authority changes.
- Bulk backend health endpoint or graph payload enrichment.
- New icon assets beyond existing controlled tunnel/vpn hub icons.

## Capabilities

### New Capabilities
None

### Modified Capabilities
- `vpn-tunnel-relations`: expose `public_ip` consistently enough for frontend tunnel tooltip contract and allow UI create/edit of tunnel `medium`.
- `tunnel-monitoring`: add frontend consumption/visualization rules while preserving authority-only status semantics.
- `category-technology-icons`: clarify tunnel icons remain technology identifiers; health uses separate styling/badges.

## Approach

Use the exploration-recommended shared frontend model. Fetch health only for visible eligible tunnel links, keyed per encoded link id, with hard production bounds: max visible-link cap, concurrency limit, retry disabled for polling, jitter/backoff, failing-link cooldown, request-rate budget, aggregated operations signal, and a runtime kill switch. Because this project has no centralized frontend telemetry sink, add a minimal authenticated backend-visible telemetry path for bounded page/session/window aggregates only. It MUST NOT include per-link details, `link_id`, endpoint identifiers, or public IPs. Map `UNKNOWN` + ICMP issue/missing public IP to neutral unknown with tooltip context. Map `UP` + ICMP failure/poor RTT to `UP` with warning badge/tooltip while textual authority remains `UP`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `frontend/types.ts` | Modified | Tunnel health/model types, `GraphNode.public_ip`. |
| `frontend/services/queryResources.ts`, `queryKeys.ts` | Modified | Tunnel health fetcher/key. |
| `frontend/hooks/queries/` | New | Visible tunnel health map hook. |
| `backend/routers/tunnels.py`, `frontend/utils/tunnelHealthTelemetry.ts` | Modified/New | Authenticated aggregated polling telemetry ingest and frontend batching/redaction helper. |
| `frontend/components/NetworkVisualizer.tsx` | Modified | Tunnel line/icon/state tooltip. |
| `frontend/components/MonitoringConsole.tsx` | Modified | Tunnel filter/topology rendering. |
| `frontend/components/VisualRelationshipEditor.tsx` | Modified | Medium create/edit/display. |
| `frontend/components/TopologyViewer.tsx`, `RelationshipManager.tsx`, `CIDetailModal.tsx` | Modified | Shared tunnel topology contract. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Scope exceeds visualization-only slice/review budget | High | Keep helpers small; consider chained PRs before apply. |
| UI contradicts Slice 2 authority semantics | Medium | Centralize labels/state mapping in helper tests. |
| Per-link polling is noisy or opaque in production | Medium | Enforce cap/concurrency/rate budget, jitter/backoff, retry override, failing-link suppression, aggregated backend-visible telemetry, and kill switch. |
| `public_ip` exposure bypasses data scope | Medium | Promote only after existing scoped repository calls; require route/service tests for `/nodes`, `/graph/full`, and CIDetailModal topology query consumers with empty/limited non-admin scopes. |

## Rollback Plan

Revert frontend tunnel visualization/query changes and any minimal `public_ip` contract promotion; existing Slice 1/2 backend specs and endpoints remain intact.

## Dependencies

- Slice 2 `GET /api/tunnels/{link_id}/health` and canonical link-id encoding.
- Existing tunnel icon catalog keys.

## Success Criteria

- [ ] All listed surfaces render tunnel medium/health consistently through one helper.
- [ ] ICMP issues never change authoritative text status to `DEGRADED` or `DOWN`.
- [ ] Visible-link health fetching has bounded polling/caching behavior, deterministic error fallback, aggregated production-visible operations telemetry, and operational kill switch.
- [ ] Public IP is never emitted for nodes outside the caller's server-side scope.
