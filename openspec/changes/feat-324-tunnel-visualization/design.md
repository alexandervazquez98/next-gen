# Design: Tunnel Visualization

## Technical Approach

Implement Slice 3 as a frontend-first visual contract over the existing Slice 2 single-link endpoint. Add helpers for encoding, visual state, tooltips, visible-link filtering, polling budgets, fallback, and aggregate telemetry. Components pass rendered tunnel links into a shared React Query hook. Backend changes stay bounded to scoped `public_ip` projection and authenticated aggregate-only telemetry; no backend normalization, vendor, or poller changes.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Visual model boundary | `frontend/utils/tunnelVisuals.ts` owns encoding, labels, authority state, warnings, tooltips, and fallback. | Per-component mapping. | One source prevents `UNKNOWN`/ICMP drift. |
| Health polling bounds | `useVisibleTunnelHealth` enforces cap 50 visible IDs/surface, max 4 in-flight, `retry: false`, 30s interval with 10-20% jitter, 2-minute failure cooldown, and ≤120 requests/minute/page. | Visible+dedupe only. | Hard limits avoid large-topology storms. |
| Failure behavior | Keep stale cached visual when present; otherwise render neutral `UNKNOWN` with tooltip error context. Suppress repeated failing IDs during cooldown and aggregate counters. | Bubble query errors into red UI. | Operators keep usable topology while failures remain diagnosable. |
| Kill switch | Support `localStorage.tunnelHealthPollingDisabled === "true"` plus `VITE_TUNNEL_HEALTH_POLLING=false` build/env gate. | Backend flag only. | Frontend can immediately stop fan-out without backend deployment. |
| Production observability | Add authenticated `POST /api/tunnels/health/telemetry` (or equivalent existing route) accepting one redacted aggregate per tab/page/window at most once/minute when active or failing. | Console counters; vendor telemetry. | No frontend sink exists; backend-visible aggregates give production debugging without vendor or per-link leakage. |
| `link_id` source | Frontend `encodeTunnelLinkId(link)` matches backend JSON order `source`, `relationship`, `target`, `medium`, UTF-8, unpadded base64url. | Wait for backend `link_id`. | Payloads lack it; fixtures prove compatibility now. |
| `public_ip` contract | Add `GraphNode.public_ip?: string | null` and emit it only from already-scoped `/nodes` and `/graph/full`, preserving `metadata.public_ip`. | Read only metadata. | Stable tooltip path without changing scope authority. |

## Data Flow

```
Scoped /nodes or /graph/full -> visible tunnel links -> capped encoder queue
  -> useQueries /api/tunnels/{link_id}/health -> cached/stale/error-aware visual model
  -> aggregate telemetry window -> POST /api/tunnels/health/telemetry
  -> NetworkVisualizer / MonitoringConsole / TopologyViewer / CIDetailModal / editor
```

## File Changes

| File | Action | Description |
|---|---|---|
| `frontend/types.ts` | Modify | Add tunnel health types and `GraphNode.public_ip`. |
| `frontend/utils/tunnelVisuals.ts` | Create | Encoder, visual mapping, tooltip, fallback, budget helpers. |
| `frontend/utils/tunnelHealthTelemetry.ts` | Create | Redacted aggregate window, latency buckets, rate-limit/batch helper. |
| `frontend/services/queryResources.ts`, `queryKeys.ts` | Modify | Add `fetchTunnelHealth(linkId,{signal})` and query key. |
| `frontend/hooks/queries/useVisibleTunnelHealth.ts` | Create | Capped/concurrent/jittered polling, retry override, cooldown, kill switch, telemetry emission. |
| `backend/routers/tunnels.py` | Modify | Add authenticated aggregate telemetry ingest with server-side redaction validation/rate limits. |
| `frontend/components/{NetworkVisualizer,MonitoringConsole,VisualRelationshipEditor,RelationshipManager,TopologyViewer,CIDetailModal}.tsx` | Modify | Consume shared model; editor creates/edits medium; CIDetailModal uses scoped topology query. |
| `backend/services/node_service.py`, `backend/services/link_service.py` | Modify | Project top-level `public_ip` after scoped repository results only. |
| `backend/tests/test_routers_nodes.py`, `backend/tests/test_routers_links.py` | Modify | Scope assertions for public-IP-bearing `/nodes` and `/graph/full` paths. |

## Interfaces / Contracts

```ts
type TunnelVisualState = "up" | "down" | "unknown";
type TunnelWarning = "icmp_failed" | "icmp_poor_rtt" | "missing_public_ip" | null;
type TunnelHealthErrorKind = "bad_request" | "not_found" | "server" | "timeout" | "auth" | "network";
type TunnelHealthTelemetry = {
  window_seconds: 60; scheduled: number; skipped_over_cap: number; suppressed_cooldown: number;
  success: number; failure_by_kind: Record<TunnelHealthErrorKind, number>;
  latency_bucket: Record<"lt_250" | "lt_1000" | "lt_5000" | "gte_5000", number>;
  kill_switch_enabled: boolean;
};
```

Telemetry MUST omit `link_id`, endpoint identifiers, encoded-ID URLs, and IP/public IP values. Batching: max once/minute per tab/page, only while active or failures occurred. `UNKNOWN` stays neutral; `UP` with ICMP problems remains textual `UP` with warning/tooltip only.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | Encoder canonical fixtures; authority visual mapping; error fallback; budget/cooldown helpers; telemetry redaction/aggregation. | Vitest with fixtures mirrored from backend. |
| Hook/service | URL/key, cap 50, concurrency 4, retry false, jitter/backoff, stale fallback, cooldown, kill switch, once/minute batching. | React Query hook tests with fake timers. |
| Component | Supported surfaces render deterministic `UNKNOWN`, warning badge, tooltip errors, and editor medium create/edit. | RTL with mocked hook/model. |
| Backend | `/nodes` and `/graph/full` scope; telemetry auth/rate limit/redaction rejects `public_ip`, IP-like values, `link_id`, per-link arrays. | Pytest route/service tests. |

## Migration / Rollout

No data migration required. Use Feature Branch Chain because surfaces plus backend projection likely exceed 400 changed lines:

```
main -> tracker feat-324-tunnel-visualization
  -> PR1 helpers/query/bounds/telemetry 📍 -> PR2 scoped public_ip+editor -> PR3 surface integrations
```

PR1 verifies unit/hook/telemetry rollback by disabling hook import or telemetry env. PR2 verifies backend scope tests/editor and reverts projection/UI only. PR3 verifies surfaces/CIDetailModal and can rollback render integrations. Each child target ≤400 changed lines / ≤60 minutes review.

## Open Questions

None.
