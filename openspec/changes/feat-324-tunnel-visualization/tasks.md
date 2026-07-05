# Tasks: Tunnel Visualization

## Review Workload Forecast

| Field | Value |
|---|---|
| Review budget | 800 changed lines total; child PRs should stay near 400 |
| Estimated changed lines | PR1 360-430; PR2 260-340; PR3 360-460; total 980-1230 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Delivery strategy | ask-always |
| Chain strategy | feature-branch-chain |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

## Dependency Diagram and Rollback Boundary

`main -> tracker feat-324-tunnel-visualization -> PR1 helpers/query/bounds/telemetry 📍 -> PR2 public_ip+editor -> PR3 surfaces`

Rollback: PR1 disables hook/telemetry imports; PR2 reverts projection/editor only; PR3 reverts render integrations only. Preserve Slice 2 authority semantics throughout.

## Work Units / Commit Guidance

| Unit | Goal | Likely PR | Commit guidance |
|---|---|---|---|
| 1 | Shared helpers, bounded query hook, telemetry | PR1 | Commit tests with helpers/hook/telemetry behavior |
| 2 | Scoped `public_ip` projection and editor medium UI | PR2 | Commit backend scope tests with projection; editor tests with UI changes |
| 3 | Topology surface integrations | PR3 | Commit each surface with its mocked visual-model tests |

## PR1: Shared Helpers, Query Bounds, Telemetry

- [x] 1.1 RED: Add Vitest fixtures for `frontend/utils/tunnelVisuals.ts` covering encoder order, UTF-8 base64url, authority labels, fallback, tooltip rows, and icon-health separation.
- [ ] 1.2 GREEN: Create `frontend/utils/tunnelVisuals.ts` and update `frontend/types.ts` with tunnel health/model types and `GraphNode.public_ip`.
- [x] 1.3 RED: Add service/hook tests for `fetchTunnelHealth`, query key, visible-only dedupe, cap 50, max 4 in-flight, `retry:false`, jitter, 2-minute cooldown, kill switch, and ≤120 requests/min/page.
- [ ] 1.4 GREEN: Update `frontend/services/queryResources.ts`, `queryKeys.ts`, and create `frontend/hooks/queries/useVisibleTunnelHealth.ts`.
- [x] 1.5 RED: Add frontend and backend telemetry tests for aggregate-only payloads, once/minute batching, auth, rate limit, and rejection of `link_id`, endpoints, URLs, public IPs, IP-like values, and per-link arrays.
- [ ] 1.6 GREEN: Create `frontend/utils/tunnelHealthTelemetry.ts` and add authenticated redacted aggregate ingest in `backend/routers/tunnels.py`.

## PR2: Scoped Projection and Editor Medium

- [x] 2.1 RED: Add backend tests in `backend/tests/test_routers_nodes.py` and `backend/tests/test_routers_links.py` for admin, non-admin limited scope, and non-admin empty scope on `/nodes`, `/graph/full`, and CIDetailModal topology consumers.
- [x] 2.2 GREEN: Update `backend/services/node_service.py` and `backend/services/link_service.py` to project top-level nullable `public_ip` only after scoped repository results, preserving `metadata.public_ip`.
- [x] 2.3 RED: Add `frontend/components/VisualRelationshipEditor.tsx` tests for creating, editing, and displaying `vpn`, `sd_wan`, and `satellite` medium plus non-authoritative health context.
- [ ] 2.4 GREEN: Wire VisualRelationshipEditor medium create/edit/display through the shared tunnel visual model.

## PR3: Topology Surface Integrations

- [ ] 3.1 RED: Add component tests for `frontend/components/NetworkVisualizer.tsx` and `MonitoringConsole.tsx` covering neutral `UNKNOWN`, `UP` warning badge, tooltip errors, visible filtering, and kill-switch no-live-health context.
- [ ] 3.2 GREEN: Integrate `useVisibleTunnelHealth` and `tunnelVisuals` into NetworkVisualizer and MonitoringConsole without changing authority text.
- [ ] 3.3 RED: Add tests for `frontend/components/TopologyViewer.tsx`, `RelationshipManager.tsx`, and `CIDetailModal.tsx` requiring shared medium/icon/status/tooltip rows and scoped public-IP fallback.
- [ ] 3.4 GREEN: Wire TopologyViewer, RelationshipManager, and CIDetailModal to the shared visual contract and scoped topology data.
- [ ] 3.5 VERIFY: Run targeted frontend Vitest and backend pytest suites, then update checklist evidence only; do not add new health normalization, bulk health endpoints, pollers, assets, or authority semantics.

## Out-of-Scope Guardrails

- Do not modify backend tunnel-health normalization, ICMP authority, pollers, vendor telemetry, bulk health endpoints, or new icon assets.
- Do not expose `public_ip` outside server-side scoped results or include identifiers/IPs in telemetry.
