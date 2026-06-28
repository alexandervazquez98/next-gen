# Tasks: VPN, SD-WAN, and Satellite Link Simulation

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Low

Overall ~650-1000 lines, 3 stacked-to-main PRs (force-chained). Slice 2 needs Slice 1 model; Slice 3 needs Slice 1 + Slice 2 endpoint.

## Per-Slice Forecasts

| Slice | Lines | Budget risk | Decision needed | Chained PRs |
|-------|-------|-------------|------------------|-------------|
| 1 — Model + Catalog | 200-300 | Low | No | N/A (chained) |
| 2 — Polling + Health | 250-350 | Low | No | N/A (chained) |
| 3 — Visual + Filter | 200-350 | Low | No | N/A (chained) |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Low

---

# Slice 1 — Data Model + Catalog Primitives (PR 1 of 3)

## Phase 1: RED

- [x] 1.1 RED: Extend `backend/tests/test_topology_repo_nodes.py` with failing `public_ip` cases (valid round-trip, invalid rejected, no backfill). _Req: VPN-Rel R1; Sc: 1-3_
- [x] 1.2 RED: Extend `backend/tests/test_topology_relationships.py` with failing `medium` + hub-obligatorio cases (reject no-hub, accept hub-to-remote). _Req: VPN-Rel R2 R3; Sc: 4-7_
- [x] 1.3 RED: Extend `backend/tests/test_routers_links.py` asserting `/api/links` + `/graph/full` expose `medium` without changing node status/event fields. _Req: VPN-Rel R4; Sc: 8_
- [x] 1.4 RED: Extend `frontend/utils/categoryIcons.test.ts` with failing cases for `vpn_tunnel`, `sd_wan_tunnel`, `satellite_link`, `vpn_hub` (keys, EN/ES aliases, `vpn_hub` name inference, generic fallback). _Req: Cat-Icons ADDED 1; Sc: 1-3_
- [x] 1.5 RED: Extend `frontend/types.test.ts` (or add) asserting `CategoryIconKey` accepts the four new keys. _Req: Cat-Icons ADDED 1; Sc: 1_

## Phase 2: Backend GREEN

- [x] 2.1 GREEN: Add `public_ip: Optional[str]` to `Node` in `backend/models/core.py` with `ipaddress.ip_address` validator. _Req: VPN-Rel R1; Sc: 1-2_
- [x] 2.2 GREEN: Persist `n.public_ip` in `topology_repo.upsert_node` via `SET n.public_ip = $public_ip`; no backfill. _Req: VPN-Rel R1; Sc: 1, 3_
- [x] 2.3 GREEN: Add `Link.medium` Literal['vpn','sd_wan','satellite'] in `backend/models/core.py`; persist `r.medium` in `topology_repo.create_link`/`update_link`. _Req: VPN-Rel R2; Sc: 4-5_
- [x] 2.4 GREEN: Add `vpn_hub` layer value in `topology_repo` distinct from `router`; no migration. _Req: VPN-Rel R1; Sc: 1_
- [x] 2.5 GREEN: Add `validate_tunnel_endpoint_hub` in `backend/services/link_service.py`; raise `HTTPException(400)` on hub-rule violation; no partial persistence. _Req: VPN-Rel R3; Sc: 6-7_

## Phase 3: API GREEN

- [x] 3.1 GREEN: Extend `backend/routers/nodes.py` + node service to accept/return `public_ip`; 400 on invalid IP. _Req: VPN-Rel R4; Sc: 1-2_
- [x] 3.2 GREEN: Extend `backend/routers/links.py` + `link_service.get_links`/`get_full_graph` to return `medium`. _Req: VPN-Rel R4; Sc: 8_

## Phase 4: Frontend GREEN

- [x] 4.1 GREEN: Extend `CategoryIconKey` in `frontend/types.ts` with 4 new keys. _Req: Cat-Icons ADDED 1; Sc: 1-2_
- [x] 4.2 GREEN: Add entries to `CATEGORY_ICON_KEY_SET` + `CATEGORY_ICON_CATALOG` with symbols `vpn_key`, `hub`, `satellite_alt`, `vpn_lock` and EN/ES aliases. _Req: Cat-Icons ADDED 1 ADDED 2; Sc: 1-3_
- [x] 4.3 GREEN: Extend `CATEGORY_NAME_TO_ICON` with EN/ES `vpn_hub` names; preserve generic fallback. _Req: Cat-Icons MODIFIED 1; Sc: 1_
- [x] 4.4 GREEN: Add optional `medium?` to `GraphLink` in `frontend/types.ts`. _Req: VPN-Rel R4; Sc: 8_

## Phase 5: Verify + PR

- [x] 5.1 Run `cd backend && python -m pytest backend/tests/test_topology_repo_nodes.py backend/tests/test_topology_relationships.py backend/tests/test_routers_links.py`; capture RED→GREEN. _Req: VPN-Rel all; Sc: 1-8_
- [x] 5.2 Run `cd frontend && corepack pnpm test:run`; capture RED→GREEN. _Req: Cat-Icons all; Sc: 1-3_
- [ ] 5.3 Open PR 1 → main linked to #324 with Slice 1 chain context. _Req: all; Sc: all_

### Slice 1 Commit Boundaries

| Commit | Tasks |
|--------|-------|
| 1 RED | 1.1-1.5 |
| 2 GREEN-BE | 2.1-2.5, 3.1-3.2 |
| 3 GREEN-FE | 4.1-4.4 |
| 4 Verify | 5.1-5.3 |

---

# Slice 2 — Polling Engine + Health Endpoint (PR 2 of 3)

## Phase 1: RED

- [ ] 1.1 RED: Add `backend/tests/test_tunnel_health_rollup.py` asserting authority rule (UP+normal=UP, UP+highlat=DEGRADED, UP+icmp_unreach≠DOWN, DOWN+icmp_ok=DOWN, unknown=UNKNOWN_PARTIAL). _Req: Tun-Mon R3 R2; Sc: 5-8_
- [ ] 1.2 RED: Add `backend/tests/test_tunnel_polling_isolation.py` asserting `poll_tunnels` does NOT write `HAS_METRIC`, `Event`, or CI status; only writes `r.health/health_source/rtt_ms/last_sample_at/partial/error`. _Req: Tun-Mon R1 R4; Sc: 4, 9_
- [ ] 1.3 RED: Add `backend/tests/test_tunnel_health_endpoint.py` for `GET /api/tunnels/{link_id}/health` (latest fields, 404 missing/non-tunnel, partial on timeout, `icmp_unavailable` flag). _Req: Tun-Mon R4; Sc: 9-11_
- [ ] 1.4 RED: Add `backend/tests/test_tunnel_vendor_registry.py` asserting placeholder up-values for known mediums and `partial=True` for unknown vendor/medium (no fabrication). _Req: Tun-Mon R1; Sc: 4_

## Phase 2: Helpers GREEN

- [ ] 2.1 GREEN: Create `backend/services/tunnel_health.py` exposing `TUNNEL_VENDOR_REGISTRY` + `resolve_vendor_probe(brand, medium)`. _Req: Tun-Mon R1; Sc: 4_
- [ ] 2.2 GREEN: Add `collect_authority_sample(link_row, session)` running SNMP GET via `fetch_snmp_value`; CLI placeholder returns `UNKNOWN_PARTIAL`. _Req: Tun-Mon R1; Sc: 4_
- [ ] 2.3 GREEN: Add `collect_icmp_degradation(public_ip)` reusing `fetch_icmp_ping(include_measurement=True)` + `get_icmp_settings()` from #270. _Req: Tun-Mon R2; Sc: 5-6, 11_

## Phase 3: Rollup GREEN

- [ ] 3.1 GREEN: Add `rollup_tunnel_health(authority, icmp)` enforcing DOWN-only-from-authority; ICMP failure never returns DOWN. _Req: Tun-Mon R3; Sc: 5-8_
- [ ] 3.2 GREEN: Add `topology_repo.set_link_health_sample(link_id, sample)` writing via `SET r += $sample` on `medium` links. _Req: Tun-Mon R4; Sc: 9_

## Phase 4: Engine + Endpoint GREEN

- [ ] 4.1 GREEN: Add `poll_tunnels()` in `backend/engines/snmp_worker.py` invoked after metric cycle; MUST NOT touch `HAS_METRIC`/`Event`/CI status paths. _Req: Tun-Mon R1 R4; Sc: 4, 9_
- [ ] 4.2 GREEN: Create `backend/routers/tunnels.py` with `GET /api/tunnels/{link_id}/health` returning `{link_id, medium, health, last_sample_at, health_source, rtt_ms, partial, error, icmp_unavailable}`. _Req: Tun-Mon R4; Sc: 9-11_
- [ ] 4.3 GREEN: Register router in `backend/main.py` (or `server.py`) without modifying existing routers. _Req: Tun-Mon R4; Sc: 9_

## Phase 5: Verify + PR

- [ ] 5.1 Run `cd backend && python -m pytest backend/tests/test_tunnel_health_rollup.py backend/tests/test_tunnel_polling_isolation.py backend/tests/test_tunnel_health_endpoint.py backend/tests/test_tunnel_vendor_registry.py`; existing snmp/event-correlation tests must pass. _Req: Tun-Mon all; Sc: 4-11_
- [ ] 5.2 Manual smoke: poll cycle produces no new `Event`/`HAS_METRIC` for tunnel links; capture Cypher output. _Req: Tun-Mon R1; Sc: 4_
- [ ] 5.3 Open PR 2 → main (rebased on Slice 1) linked to #324 with Slice 2 chain context. _Req: all; Sc: all_

### Slice 2 Commit Boundaries

| Commit | Tasks |
|--------|-------|
| 1 RED | 1.1-1.4 |
| 2 GREEN helpers | 2.1-2.3 |
| 3 GREEN rollup | 3.1-3.2 |
| 4 GREEN wiring | 4.1-4.3 |
| 5 Verify | 5.1-5.3 |

---

# Slice 3 — Frontend Visual + Filter (PR 3 of 3)

## Phase 1: RED

- [ ] 1.1 RED: Add `frontend/utils/tunnelHealthStyles.test.ts` for state-to-style (UP=emerald/normal, DEGRADED=amber/long-dash, DOWN=red/dense-dash, UNKNOWN_PARTIAL=neutral/dotted). _Req: Tun-Mon R3; Sc: 5-8_
- [ ] 1.2 RED: Add `frontend/services/tunnelHealth.test.ts` for fetch helper (cache by `link_id`, 5s TTL, undefined on 404). _Req: Tun-Mon R4; Sc: 9_
- [ ] 1.3 RED: Extend `frontend/components/__tests__/NetworkVisualizer.test.tsx` asserting tunnel links render with helper-mapped color/dash and tooltip surfaces health/source/RTT from `/api/tunnels/{link_id}/health`. _Req: Cat-Icons R3; Tun-Mon R4; Sc: 3, 9_
- [ ] 1.4 RED: Extend `frontend/components/__tests__/MonitoringConsole.test.tsx` asserting `tunnelOnly` toggle hides non-tunnel links; event stream unchanged. _Req: Tun-Mon R4; Sc: 9_

## Phase 2: Helper + Fetcher GREEN

- [ ] 2.1 GREEN: Create `frontend/utils/tunnelHealthStyles.ts` exporting `mapHealthToStyle(health)` with `{color, particleSpeed, dashArray, label}`. _Req: Tun-Mon R3; Sc: 5-8_
- [ ] 2.2 GREEN: Create `frontend/services/tunnelHealth.ts` exporting `fetchTunnelHealth(link_id)` + `TunnelHealthCache` (5s TTL). _Req: Tun-Mon R4; Sc: 9_

## Phase 3: Visuals GREEN

- [ ] 3.1 GREEN: Extend `NetworkVisualizer.tsx` to fetch + cache on 5s cadence; pass `mapHealthToStyle` into `linkColor`/`linkWidth`/`linkDirectionalParticles`. _Req: Tun-Mon R4; Sc: 9_
- [ ] 3.2 GREEN: Add tooltip overlay on `NetworkVisualizer` showing health/source/RTT/last_sample/partial/error. _Req: Tun-Mon R4; Sc: 9_
- [ ] 3.3 GREEN: Extend `VisualRelationshipEditor.tsx` to consume `mapHealthToStyle` for SVG `stroke`/`stroke-opacity`/`stroke-dasharray` on `medium` links. _Req: Tun-Mon R4; Sc: 9_

## Phase 4: Filter GREEN

- [ ] 4.1 GREEN: Add `tunnelOnly` toggle (default off) to `MonitoringConsole.tsx`; filter `links` to `medium` entries when on. _Req: Tun-Mon R4; Sc: 9_
- [ ] 4.2 GREEN: Apply `mapHealthToStyle` to `Polyline` color/weight/dashArray when `tunnelOnly` is on. _Req: Tun-Mon R3; Sc: 5-8_

## Phase 5: Verify + PR

- [ ] 5.1 Run `cd frontend && corepack pnpm test:run`; existing icon/NetworkVisualizer/MonitoringConsole/VisualRelationshipEditor tests must pass. _Req: all; Sc: 1-11_
- [ ] 5.2 Manual smoke: hover tunnel link → tooltip shows health/source/RTT; tunnel-only filter hides non-tunnel links. _Req: Tun-Mon R4; Sc: 9_
- [ ] 5.3 Open PR 3 → main (rebased on Slice 1+2) linked to #324 with Slice 3 chain context. _Req: all; Sc: all_

### Slice 3 Commit Boundaries

| Commit | Tasks |
|--------|-------|
| 1 RED | 1.1-1.4 |
| 2 GREEN helper | 2.1-2.2 |
| 3 GREEN visuals | 3.1-3.3 |
| 4 GREEN filter | 4.1-4.2 |
| 5 Verify | 5.1-5.3 |

---

## Cross-Slice Risks

| Sev | Risk | Mitigation |
|-----|------|------------|
| WARN | Slice 2 needs Slice 1 `medium`/`public_ip` | Slice 1 merges first; Slice 2 rebases; verify clean diff. |
| WARN | Slice 3 needs Slice 2 endpoint payload | Type response early in `frontend/types.ts`; mock in Slice 3 RED. |
| SUGG | Vendor OID/CLI registry scope creep | Placeholder-only this change; flag full coverage as future. |
| SUGG | `snmp_worker.py` is large and event-sensitive | Isolated `poll_tunnels()`; isolation test guards regressions. |