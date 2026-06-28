# Proposal: VPN, SD-WAN, and Satellite Link Simulation

## Intent

Model VPN/SD-WAN/satellite tunnels as first-class topology links with visible health. Operators can identify tunnel technology, see SNMP/CLI-authoritative state, and use ICMP RTT as degradation context without treating ping loss as tunnel DOWN.

## Scope

### In Scope
- Add CI metadata `public_ip`, CI type/icon `vpn_hub`, and icon keys `vpn_tunnel`, `sd_wan_tunnel`, `satellite_link`, `vpn_hub`.
- Add tunnel relation `medium: vpn|sd_wan|satellite` and health `UP|DEGRADED|DOWN`.
- Combine SNMP/CLI tunnel state with ICMP RTT/loss from `public_ip`.
- Render state in topology editors and Monitoring Console tunnel-only filter.

### Out of Scope
- Backfill existing CIs or historical links.
- Vendor-complete OID/CLI coverage beyond extensible placeholders.
- Replacing node status/event semantics with tunnel status.

## Capabilities

### New Capabilities
- `vpn-tunnel-relations`: CI metadata, `vpn_hub` CI type, tunnel relation medium metadata, and public-IP persistence rules.
- `tunnel-monitoring`: SNMP/CLI-authoritative tunnel state, ICMP degradation context, health rollup endpoint, and state samples.

### Modified Capabilities
- `category-technology-icons`: Add four controlled icon keys and fallback-safe catalog entries.

## Approach

Deliver stacked-to-main PRs under 400 changed lines. Slice 1 adds model/catalog primitives. Slice 2 extends `snmp_worker.py` and ICMP measurement so SNMP/CLI decides `UP`/`DOWN`; ICMP only marks `DEGRADED` and feeds tooltip RTT. Slice 3 consumes health payloads with shared state-to-style helpers.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| Backend CI/link model | Modified | `public_ip`, `vpn_hub`, relation metadata/validation. |
| Backend polling | Modified | Tunnel polling, ICMP degradation context, rollup. |
| `backend/routers/links.py`, `backend/services/link_service.py` | Modified | Health/topology payload exposure. |
| `frontend/utils/categoryIcons.ts`, `frontend/types.ts` | Modified | Four new icon keys and graph/link types. |
| `frontend/components/NetworkVisualizer.tsx`, `VisualRelationshipEditor.tsx`, `MonitoringConsole.tsx` | Modified | State rendering, tooltip, tunnel-only filter. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Relationship model lacks existing spec coverage | Med | Create `vpn-tunnel-relations` spec before implementation. |
| ICMP could accidentally override tunnel DOWN authority | Med | Test rollup rule: SNMP/CLI owns DOWN; ICMP only degrades UP. |
| Slice 3 exceeds review budget | Med | Extract pure style/filter helpers and tests with the visual slice. |

## Rollback Plan

Revert by slice: remove catalog/model primitives; disable tunnel polling/health endpoint; remove frontend rendering/filter. No backfill means no migration reversal.

## Dependencies

- Strict TDD backend/frontend test commands.
- #270 ICMP behavior and SNMP worker loop.
- Archived category icon pattern.

## Success Criteria

- [ ] Slice 1 persists `public_ip`, `vpn_hub`, tunnel medium, and four icon keys.
- [ ] Slice 2 reports `UP`, `DEGRADED`, `DOWN` with SNMP/CLI authority.
- [ ] Slice 3 renders green/amber/red tunnel styles, tooltip details, and tunnel-only filtering.
- [ ] End-to-end tests prove no backfill and no ICMP-driven DOWN override.
