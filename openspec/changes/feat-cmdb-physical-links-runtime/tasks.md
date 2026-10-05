# Tasks: cmdb(cmdb) physical-link visualization runtime slices (#444, #439, #443)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~2100 across 3 issues |
| 400-line budget risk | Low (small child PRs) |
| Chained PRs recommended | No (each slice is small enough) |
| Suggested split | 1 PR per issue, possibly 2 if any exceeds 400 LOC |
| Delivery strategy | single-pr per issue |
| Files changed | ~12 new + ~2 modified |

```text
Decision needed before apply: yes (aggregation window default, staleness threshold)
Chained PRs recommended: no
Chain strategy: single-pr
400-line budget risk: low
```

## Suggested Work Units

### #444 visual styling (tracker `feat/444-physical-link-styling`)

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|----------------------|-----------------|-------------------|
| W1 | Style registry + per-type visual differentiation + legend | `cd frontend && npx vitest run __tests__/PhysicalLinkStyle.test.tsx __tests__/LinkTypeLegend.test.tsx` | manual: open topology view, verify link colors per type | revert `frontend/components/cmdb/topology/PhysicalLinkStyleRegistry.ts`, `PhysicalLinkLayer.tsx`, `LinkTypeLegend.tsx` |

### #439 utilization read model (tracker `feat/439-physical-link-utilization`)

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|----------------------|-----------------|-------------------|
| W2 | Aggregation logic, endpoint, "no data" distinct from "0" | `pytest backend/tests/test_physical_link_utilization.py backend/tests/test_physical_link_utilization_no_data.py -q` | `curl http://localhost:18000/api/cmdb/physical-links/{id}/utilization?window=15m` | revert `backend/repositories/physical_link_repo.py`, `backend/services/physical_link_utilization.py`, `backend/routers/physical_link_utilization.py`, tests |

### #443 interface-to-link polling (tracker `feat/443-interface-to-link-polling`)

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|----------------------|-----------------|-------------------|
| W3 | Poll mapping via `CONNECTED_VIA`, feed slice-3 read model | `pytest backend/tests/test_physical_link_polling_integration.py backend/tests/test_tunnel_polling_unchanged.py -q` | manual: verify tunnel polling still produces same events as before | revert `backend/polling/physical_link_aggregator.py`, interface polling integration point, tests |

## Phase 1: Pre-flight (all slices)

- [ ] 1.1 Confirm `PhysicalLink` contract slice (#323) has landed (check `backend/contracts/` or wherever the schema lives)
- [ ] 1.2 Confirm aggregation window default and staleness threshold (maintainer decision)
- [ ] 1.3 Audit existing interface pollers to identify which ones to bridge

## Phase 2: #444 visual styling

### PR1 (style registry + legend) — SHIPPED in #444
- [x] 2.1 RED test in `frontend/__tests__/physicalLinkStyles.test.ts`: each `PhysicalLink.type` (`fiber`, `copper`, `microwave`, `wireless_ptp`) maps to a distinct color, dash pattern, and label style. (File path differs: style tests live next to the helper under `frontend/utils/__tests__/physicalLinkStyles.test.ts`.)
- [x] 2.2 RED test in `frontend/components/cmdb/topology/__tests__/LinkTypeLegend.test.tsx`: legend renders all link types with their colors and a one-line description
- [x] 2.3 `frontend/utils/physicalLinkStyles.ts`: lookup by `PhysicalLink.type` (frozen const + `getPhysicalLinkStyle` accessor — exhaustive via `Record<PhysicalLinkType, PhysicalLinkStyle>`)
- [x] 2.4 ~`PhysicalLinkLayer.tsx`~: deferred to a follow-up slice — none of the legacy renderers (TopologyViewer / NetworkVisualizer / VisualRelationshipEditor / MonitoringConsole) consume PhysicalLink data today. Wiring will land when the data flow ships.
- [x] 2.5 `frontend/components/cmdb/topology/LinkTypeLegend.tsx`: render legend from registry (data-driven, accessible, semantic)
- [x] 2.6 GREEN tests; visual snapshot or contract test if applicable; full frontend suite green (881/881)

### PR2 (CRUD API + preview route) — SHIPPED in #444 (scope expansion)
- [x] 2.7 Backend CRUD: `backend/{schemas,repositories,services,routers}/physical_link_*.py` + register in `backend/main.py` — POST / GET list (filters: ci_id/type/status) / GET by id / PATCH status. Auth: `CI_EDIT` write, public read (mirrors tunnel-link precedent), Admin bypasses. 38 new backend tests, RED→GREEN observed.
- [x] 2.8 Frontend API client + React Query hooks: `frontend/services/physicalLinks.ts` + `hooks/queries/{usePhysicalLinksQuery,usePhysicalLinkMutations}.ts` + `services/queryKeys.ts` keys. Cache invalidation on mutation success. 6 new frontend tests, RED→GREEN observed.
- [x] 2.9 `frontend/components/cmdb/topology/PhysicalLinkPreview.tsx`: showcase component — legend + live CRUD list + create form + per-row status selector. 5 RTL tests, RED→GREEN observed.
- [x] 2.10 `frontend/pages/PhysicalLinksPage.tsx`: page wrapper mounted at `/physical-links`. 2 page tests (header + back link).
- [x] 2.11 Backend feature flag `FEATURE_CMDB_PHYSICAL_LINKS_ENABLED` (default off, 404 when off) — mirrors `FEATURE_CMDB_PROPOSALS_ENABLED`. 4 flag-off tests.

### PR2 (regression)
- [ ] 3.1 Visual regression test: tunnel links (`vpn`, `sd_wan`, `satellite`) render unchanged (snapshot diff vs baseline)
- [ ] 3.2 Test: `medium` field on tunnel links is untouched
- [ ] 3.3 Test: legend does not show tunnel types (separate legend or omitted)
- [ ] 3.4 GREEN tests

## Phase 3: #439 utilization read model

### PR1 (aggregation + endpoint)
- [x] 4.1 RED tests in `backend/tests/test_physical_link_utilization.py`: aggregation correctness for known input → expected rollup
- [x] 4.2 RED tests in `backend/tests/test_physical_link_utilization_no_data.py`: empty case returns `null` utilization + `empty_reason: "no_data"` (NOT zero)
- [x] 4.3 `backend/repositories/physical_link_repo.py`: read model query (Cypher against `PhysicalLink` + `CONNECTED_VIA`)
- [x] 4.4 `backend/services/physical_link_utilization.py`: orchestration (window selection, empty detection)
- [x] 4.5 Endpoint: `GET /api/cmdb/physical-links/{id}/utilization?window=<duration>`
- [x] 4.6 GREEN tests; full backend suite green

### PR2 (staleness + windowing)
- [x] 5.1 RED tests: windowed rollup (1h, 6h, 24h windows produce different aggregation granularity)
- [x] 5.2 RED tests: staleness surfacing (`stale: true` when no recent counters within threshold)
- [x] 5.3 Staleness calculation in service layer
- [x] 5.4 GREEN tests; full backend suite green; PR1 unaffected

## Phase 4: #443 interface-to-link polling

### PR1 (bridge + aggregation feed) — SHIPPED in v1.19.8 (PR #543)
- [x] 6.1 RED test in `backend/tests/test_physical_link_bridge.py` (+ `test_physical_link_bridge_registration.py`): bridge stamps `pl.last_polled_at` when at least one endpoint has fresh `metric_values` rows; integration via `PhysicalLink.endpoints` field (the 2-tuple, NOT `:CONNECTED_VIA` traversal yet — deferred to PR2 for status derivation scope)
- [x] 6.2 `backend/polling/physical_link_bridge.py`: scheduled bridge (`run_once(settings, driver, now)`) updates `pl.last_polled_at` on active links (status IN {UP, UNKNOWN, PLANNED}); `metric_values` is the source of truth
- [x] 6.3 New registration in `backend/main.py` (`_register_physical_link_polling_bridge_job` on `backup_scheduler`); no changes to `snmp_worker.py`, `writer_pool.py`, `link_service.py` (REQ-PHYSLINK-UTIL-3 hard rule honored). Sub-flag `FEATURE_CMDB_PHYSICAL_LINK_POLLING_ENABLED` (default off, kill-switch independent of slice-2/3 flag).
- [x] 6.4 GREEN tests (10 tests, TDD strict RED→GREEN, 11/11 CI verde on PR #543)

### PR2 (backward compat)
- [ ] 7.1 RED test in `backend/tests/test_tunnel_polling_unchanged.py`: tunnel polling still produces same events as before the bridge
- [ ] 7.2 No new state representation introduced
- [ ] 7.3 GREEN tests; full backend suite green; PR1 unaffected

## Critical sequencing

- Phase 2 depends on #323 contract slice merged (provides `PhysicalLink` model + `CONNECTED_VIA`)
- Phase 3 depends on Phase 2 merged (visual styling needs the model)
- Phase 4 depends on Phase 3 merged (polling integration feeds the read model)
- Phase 4 PR2 (backward compat) depends on Phase 4 PR1

## Cross-references

- Contract slice: #323 (approved), `PhysicalLink` metadata model
- Visual tests: `frontend/__tests__/LinkTypeLegend.test.tsx`, `PhysicalLinkStyle.test.tsx`
- Backward compat gate: `backend/tests/test_tunnel_polling_unchanged.py`
- Source proposal: `openspec/changes/feat-cmdb-physical-links-runtime/proposal.md`