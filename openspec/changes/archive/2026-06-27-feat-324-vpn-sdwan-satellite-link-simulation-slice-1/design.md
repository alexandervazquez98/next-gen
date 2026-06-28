# Design: VPN, SD-WAN, and Satellite Link Simulation

## Architecture Overview

This change is delivered as 3 stacked-to-main slices. Slice 1 establishes stable model/catalog contracts, Slice 2 adds tunnel sampling and health rollup, and Slice 3 consumes those contracts for state-driven visuals.

```mermaid
flowchart LR
  S1[Slice 1: CI + relation primitives\nmodels/core.py, topology_repo.py\ncategoryIcons.ts, types.ts] --> S2[Slice 2: polling + health API\nsnmp_worker.py, icmp_measurements.py\nlinks.py, link_service.py]
  S2 --> S3[Slice 3: visual + filter\nNetworkVisualizer.tsx\nVisualRelationshipEditor.tsx\nMonitoringConsole.tsx]
  CI[CIs: type, public_ip] --> REL[Relations: relationship + medium]
  REL --> POLL[SNMP/CLI tunnel poll]
  CI --> ICMP[Existing ICMP ping pipeline]
  POLL --> ROLLUP[Health rollup: UP/DEGRADED/DOWN]
  ICMP --> ROLLUP
  ROLLUP --> API[GET /api/tunnels/{link_id}/health]
  API --> FE[Tooltip + link state styles]
```

## Slice 1 Design — Data Model + Catalog Primitives

| Concern | Design |
|---|---|
| `public_ip` | Add nullable `Node.public_ip`; validate with Python `ipaddress.ip_address` in `models/core.py` or service validator before `topology_repo.upsert_node`. Persist `n.public_ip`, expose through `/nodes`, `/graph/full`, metadata, and search only if intentionally added. |
| `vpn_hub` | Treat as CI/category `layer` value distinct from `router`; add default icon mapping to backend category resolver and frontend catalog. No migration/backfill. |
| Tunnel medium | Extend `Link` with optional `medium: Literal['vpn','sd_wan','satellite']`; persist as relationship property `r.medium`; return from `/links`, `/graph/full`, and relationship summaries. Relationship type remains existing `CONNECTS_TO` unless user selects another supported CI relation. |
| Endpoint rule | **Confirmed by product (2026-06-27)**: every relation with `medium` MUST connect two CIs and at least one endpoint MUST be `vpn_hub`. Non-hub site-to-site VPN is OUT OF SCOPE for this change. |
| Icons | Add `vpn_tunnel`, `sd_wan_tunnel`, `satellite_link`, `vpn_hub` to `CategoryIconKey`, `CATEGORY_ICON_KEY_SET`, `CATEGORY_ICON_CATALOG`, and name aliases. Icons identify technology only, never health. |
| API | Existing create/read endpoints gain optional `public_ip` and `medium`; invalid IP/medium/hub rule returns 400 without partial persistence. |

Strict TDD: add backend unit tests in `backend/tests/test_topology_relationships.py` / `test_topology_repo_nodes.py`; frontend catalog tests in `frontend/utils/categoryIcons.test.ts`.

## Slice 2 Design — Polling Engine + Health Endpoint

Extend `backend/engines/snmp_worker.py` with a separate tunnel poll path after normal metric polling, without changing existing `HAS_METRIC` contracts. Query CI-to-CI links with `r.medium`, resolve endpoint `public_ip`, select vendor probe from a registry such as `{brand: {medium: {snmp_oid, cli_command, up_values}}}`, and default unknown vendors to partial data.

```python
if authority_state == "DOWN": health = "DOWN"
elif authority_state == "UP" and (icmp_high_latency or icmp_intermittent_loss): health = "DEGRADED"
elif authority_state == "UP": health = "UP"
else: health = "UNKNOWN_PARTIAL"  # API partial data, never ICMP DOWN
```

ICMP reuses `fetch_icmp_ping(..., include_measurement=True)`, `PingMeasurement`, and thresholds from `get_icmp_settings`; no duplicate worker and no node status/event writes for tunnel ICMP. Store latest samples in Neo4j relationship properties (`health`, `health_source`, `rtt_ms`, `last_sample_at`, `partial`, `error`) because frontend needs latest state and this avoids a new Timescale schema. Add service helper and `GET /api/tunnels/{link_id}/health` returning `{link_id, medium, health, last_sample_at, health_source, rtt_ms, partial, error}`; 404 for missing/non-tunnel link, 200 partial when authority data is unavailable.

Strict TDD: unit-test rollup authority assertions: ICMP failure never returns `DOWN`; SNMP/CLI `DOWN` wins over ICMP success; unknown vendor returns partial.

## Slice 3 Design — Frontend Visual + Filter

Create shared pure helper `frontend/utils/tunnelHealthStyles.ts` used by `NetworkVisualizer`, `VisualRelationshipEditor`, and `MonitoringConsole`.

| State | Color | Motion | Dash |
|---|---|---|---|
| `UP` | emerald | normal particles | none / relationship default |
| `DEGRADED` | amber | slower particles | long dash |
| `DOWN` | red | stopped/minimal | dense dash |
| partial/unknown | neutral | none | dotted |

Fetch health for visible tunnel links from `/api/tunnels/{link_id}/health`; cache by `link_id`, refresh on the existing 5s graph/console cadence, and show tooltip fields: health, source, RTT, last sample, partial/error. Add `tunnelOnly` toggle in `MonitoringConsole`; it filters map links to `medium` links and keeps existing event stream semantics unchanged.

Strict TDD: helper unit tests for state-to-style mapping and a component/integration test proving tooltip shows RTT/source and tunnel-only hides non-tunnel links.

## Slice Sequencing and Dependencies

| Slice | Inputs | Outputs | Merge dependency |
|---|---|---|---|
| 1 | Existing CI/link/category models | Stable `public_ip`, `vpn_hub`, `medium`, icon keys | First; model contract required by all later slices |
| 2 | Slice 1 model + existing SNMP/ICMP helpers | Health rollup + endpoint | Second; no frontend dependency |
| 3 | Slice 1 `medium` + Slice 2 health endpoint | Visual styles, tooltip, tunnel-only filter | Third; consumes stable API only |

## Risks

| Severity | Risk | Mitigation |
|---|---|---|
| RESOLVED | Endpoint rule confirmed: hub obligatorio. | Product confirmed 2026-06-27; non-hub site-to-site is out of scope. |
| WARNING | ICMP authority creep could create false tunnel DOWN. | Pure rollup tests assert `DOWN` only comes from SNMP/CLI. |
| WARNING | `snmp_worker.py` is already large and event-sensitive. | Add isolated tunnel helpers; do not touch existing node status/event paths. |
| SUGGESTION | Vendor OID/CLI coverage can expand scope. | Ship registry placeholders only; document unknown vendor partial data. |

## Migration / Backfill

No migration or backfill. Existing CIs, node statuses, events, and links remain unchanged until edited or explicitly modeled as tunnels.

## Out of Scope

- Vendor-complete SNMP OID/CLI coverage.
- Historical tunnel sample retention or analytics.
- Replacing CI/node status, ICMP availability events, or event correlation semantics.
- Automatic inference of `public_ip`, `vpn_hub`, or tunnel links.
- Non-hub site-to-site tunnel support unless product confirms a different endpoint rule.

## Open Questions

_None at this time. Endpoint rule confirmed by product (2026-06-27): hub obligatorio._
