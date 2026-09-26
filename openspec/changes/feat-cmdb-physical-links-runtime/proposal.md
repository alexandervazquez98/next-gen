# Proposal: cmdb(cmdb) physical-link visualization runtime slices (#444, #439, #443)

## Problem

The CMDB link model currently treats `medium` as a tunnel-oriented enum (`vpn`, `sd_wan`, `satellite`, etc.) owned by the tunnel visualization work. Fiber and other physical links need a separate metadata model. Overloading `medium` would collide with existing tunnel semantics, break search/filter behavior, and create unsafe UX for editing.

The contract slice (#323) introduces the `PhysicalLink` metadata model and `CONNECTED_VIA` relationship. This proposal owns the runtime slices that consume that metadata:

- **#444** — static visual styling for fiber / copper / microwave / wireless_ptp link types
- **#439** — utilization read model aggregating interface counters to `PhysicalLink` level
- **#443** — interface-to-link polling integration bridging the metric data plane with the utilization read model

## Scope

### Owns

- **#444** — frontend visual styling registry for `PhysicalLink.type` (color, dash pattern, label style); default legend explaining link-type colors; no override of tunnel styling rules
- **#439** — backend read model aggregating interface counters per `PhysicalLink` over a configurable window; distinct "no data" state when no recent counters are available; staleness surfacing in the API
- **#443** — bridge between interface-level polling and `PhysicalLink` aggregation via `CONNECTED_VIA`; reuse existing interface pollers; feed aggregated results into the slice-3 read model

### Does not own

- `PhysicalLink` metadata model creation (owned by #323 contract slice)
- `CONNECTED_VIA` relationship definition (owned by #323)
- Tunnel visualization styling and tunnel `medium` semantics (untouched)
- Dynamic utilization overlay in slice 2 (deferred to slice 3 + slice 4)
- OpenAPI contract regeneration for PhysicalLink fields
- Bulk import path for `PhysicalLink` rows (separate workflow)

## Approach

Three sequential slices, each as a small PR (slice 1 and 2 are smaller; slice 3 is integration-heavy):

```
#444 — visual styling
  PR1: style registry + color/dash/label per PhysicalLink.type + legend
  PR2: visual regression tests (snapshot or contract)

#439 — utilization read model
  PR1: aggregation logic + endpoint + "no data" distinct from "0"
  PR2: staleness surfacing + windowed rollup tests

#443 — interface-to-link polling integration
  PR1: poll mapping via CONNECTED_VIA + aggregation feed
  PR2: backward-compat tests for tunnel polling unchanged
```

## Requirements

### From #444

1. Visual differentiation per `PhysicalLink.type` (`fiber`, `copper`, `microwave`, `wireless_ptp`)
2. Style registry owned by this slice
3. No override of tunnel styling rules
4. Default legend explaining link-type colors

### From #439

1. Read model aggregates interface counters per `PhysicalLink`
2. Configurable window for rollup
3. Distinct "no data" state when no recent counters available (NOT zero)
4. Staleness surfaced in API
5. No changes to existing tunnel metric paths

### From #443

1. Reuse existing interface pollers (no duplication)
2. Map polled interface counters to parent `PhysicalLink` via `CONNECTED_VIA`
3. Feed aggregated results into slice-3 read model
4. Hard rule: no impact on tunnel polling semantics
5. Hard rule: single source of truth for polling state

## Hard constraints

- `PhysicalLink` coexists with tunnel links — both queryable independently
- Tunnel visualization styling and `medium` semantics untouched
- No parallel representation of polling state introduced
- Distinct empty state: "no data" must NOT be zero utilization
- Backward compatibility: tunnel polling tests unchanged and green

## Non-goals

- Bulk-import of `PhysicalLink` rows
- Real-time topology sync via WebSocket
- Cross-link aggregation reasoning
- Dynamic utilization heatmap (deferred; static styling in #444 only)

## Affected files (rough)

### #444 frontend
- new: `frontend/components/cmdb/topology/PhysicalLinkStyleRegistry.ts`
- modify: `frontend/components/cmdb/topology/PhysicalLinkLayer.tsx`
- new: `frontend/components/cmdb/topology/LinkTypeLegend.tsx`
- new: `frontend/__tests__/PhysicalLinkStyle.test.tsx`
- new: `frontend/__tests__/LinkTypeLegend.test.tsx`

### #439 backend
- new: `backend/repositories/physical_link_repo.py`
- new: `backend/services/physical_link_utilization.py`
- new: `backend/routers/physical_link_utilization.py` (or extend existing graph router)
- new: `backend/tests/test_physical_link_utilization.py`
- new: `backend/tests/test_physical_link_utilization_no_data.py`

### #443 backend polling
- modify: `backend/polling/` (interface polling integration)
- new: `backend/polling/physical_link_aggregator.py`
- new: `backend/tests/test_physical_link_polling_integration.py`
- new: `backend/tests/test_tunnel_polling_unchanged.py` (backward-compat regression)

## Estimated footprint

| Slice | LOC estimate | Files | Review budget risk |
|---|---|---|---|
| #444 styling | ~600 (2 PRs) | 3 new + 1 modified | Low per PR |
| #439 read model | ~800 (2 PRs) | 4 new | Low per PR |
| #443 polling | ~700 (2 PRs) | 3 new + 1 modified | Low per PR |
| **Total** | **~2100** | **~12** | Low |

## Open decisions for the maintainer

1. **Aggregation window default** — 5 min, 15 min, or 1 hour? Affects how "no data" thresholds.
2. **Staleness threshold** — how many consecutive empty cycles before a link is flagged stale?
3. **`NetworkVisualizer` integration** — does it already visualize `PhysicalLink`, or is it tunnel-only? Affects whether slice 1 styling needs broader integration.