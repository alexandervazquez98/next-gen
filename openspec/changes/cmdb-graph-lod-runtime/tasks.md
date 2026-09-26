# Tasks: cmdb(graph) runtime slice for LOD overview and detail APIs (#391, #392, #393)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~4800 across 3 issues |
| 400-line budget risk | Low (Feature Branch Chain: each child PR < 400 LOC) |
| Chained PRs recommended | Yes — mirror PR #468 pattern |
| Suggested split | 8 child PRs across 3 tracker PRs |
| Delivery strategy | feature-branch-chain (tracker per issue, child PRs per slice) |
| Files changed | ~20 new + ~6 modified |

```text
Decision needed before apply: yes (aggregate-breakdown permission creation, NetworkVisualizer audit outcome)
Chained PRs recommended: yes
Chain strategy: feature-branch-chain
400-line budget risk: low (per child PR)
```

## Suggested Work Units

### #391 backend runtime (tracker `feat/391-lod-backend-apis`)

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|----------------------|-----------------|-------------------|
| W1 | `GET /graph/overview` endpoint, aggregation Cypher, auth/scoping pre-aggregation | `pytest backend/tests/test_graph_overview_aggregation.py backend/tests/test_graph_consumer_authorization.py -q` | `curl http://localhost:18000/api/graph/overview` against dev stack | revert `backend/routers/graph_lod.py`, `backend/repositories/graph_lod_repo.py`, `backend/services/graph_lod_service.py`, `backend/tests/test_graph_overview_*.py`, `backend/tests/test_graph_consumer_authorization.py` |
| W2 | `GET /graph/detail/{cluster_id}` endpoint, cursor pagination, `cluster_id` parse | `pytest backend/tests/test_graph_detail_retrieval.py backend/tests/test_graph_detail_cursor.py backend/tests/test_graph_detail_cluster_id.py -q` | `curl http://localhost:18000/api/graph/detail/location:datacenter-east?limit=50` | revert detail endpoint files; W1 unaffected |
| W3 | aggregate policy enforcement, hidden ≡ absent parity, `/graph/full` byte-equality regression | `pytest backend/tests/test_graph_hidden_absent_parity.py backend/tests/test_graph_aggregate_disclosure.py backend/tests/test_graph_full_snapshot.py -q` | manual: ensure hidden and absent cluster responses are byte-equivalent | revert aggregate policy integration; W1+W2 unaffected |

### #392 frontend GraphCMDB (tracker `feat/392-graphcmdb-overview-first`)

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|----------------------|-----------------|-------------------|
| W4 | overview-on-mount, no initial `/graph/full` | `cd frontend && npx vitest run __tests__/GraphCMDB.test.tsx -t "overview on mount"` | dev server network log inspection | revert `frontend/components/GraphCMDB.tsx`, `frontend/services/graphLod.ts` |
| W5 | detail hydration on click/expand + search/filter target, delimited subgraph merge | `cd frontend && npx vitest run __tests__/GraphCMDB.test.tsx -t "detail hydration"` | manual: click a cluster, observe delimited merge | revert detail hydration logic; W4 unaffected |
| W6 | fallback to `/graph/full` when LOD path fails, remove zoom-triggered fetch | `cd frontend && npx vitest run __tests__/GraphCMDB.test.tsx -t "fallback"` `__tests__/graphLod.test.ts` | manual: simulate LOD endpoint 500, verify fallback | revert fallback logic; W4+W5 unaffected |

### #393 migrate remaining consumers (tracker `feat/393-migrate-remaining-consumers`)

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|----------------------|-----------------|-------------------|
| W7 | caller inventory (audit only, no code changes) | `pytest backend/tests/test_spec_coverage_graph.py -q` | manual review of `docs/refactoring/cmdb-graph-consumer-inventory.md` | revert `docs/refactoring/cmdb-graph-consumer-inventory.md`; no code revert |
| W8 | migrate consumers based on audit (NetworkVisualizer first), backward-compat tests | depends on W7 outcome | manual: verify migrated consumers do not regress | revert consumer-specific changes; W7 unaffected |

## Phase 1: Pre-flight (all slices)

- [ ] 1.1 Confirm `graph:aggregate_breakdown:read` permission creation path (seed in `seed_roles.py`, gate on ADMIN)
- [ ] 1.2 Confirm `/graph/full` callers list (read existing code; results feed #393 W7 audit)
- [ ] 1.3 Confirm frontend bundle-splitting strategy for detail hydration chunk

## Phase 2: #391 backend runtime

### PR1 (overview endpoint)
- [ ] 2.1 RED test in `backend/tests/test_graph_consumer_authorization.py`: visible-set resolution happens before aggregation (assert query plan or mock call order)
- [ ] 2.2 RED test in `backend/tests/test_graph_overview_aggregation.py`: returns clusters with aggregates for authorized principal
- [ ] 2.3 `backend/repositories/graph_lod_repo.py`: aggregation Cypher with visible-set WHERE clause
- [ ] 2.4 `backend/services/graph_lod_service.py`: orchestrate auth → aggregate → disclose → DTO
- [ ] 2.5 `backend/routers/graph_lod.py`: `GET /graph/overview` handler, FastAPI dependency for principal
- [ ] 2.6 Register router in `backend/main.py`
- [ ] 2.7 GREEN tests; full backend suite green

### PR2 (detail endpoint)
- [ ] 3.1 RED tests in `backend/tests/test_graph_detail_cluster_id.py`: valid parse, sentinel, case-collapse, reject invalid (mirror #390 contract tests for runtime)
- [ ] 3.2 RED tests in `backend/tests/test_graph_detail_cursor.py`: encode/decode round-trip, `InvalidCursorError`, `StaleCursorError`, `PermissionChangedError`
- [ ] 3.3 RED tests in `backend/tests/test_graph_detail_retrieval.py`: bounded subgraph with pagination
- [ ] 3.4 `backend/repositories/graph_lod_repo.py`: detail subgraph Cypher with cursor and limit
- [ ] 3.5 `backend/services/graph_lod_service.py`: detail orchestration (cluster_id parse → principal hash → cursor → bounded query → DetailProjectionPolicy → DTO)
- [ ] 3.6 `backend/routers/graph_lod.py`: `GET /graph/detail/{cluster_id}` handler
- [ ] 3.7 GREEN tests; full backend suite green; PR1 unaffected

### PR3 (disclosure + parity)
- [ ] 4.1 RED tests in `backend/tests/test_graph_aggregate_disclosure.py`: tier selection (`none` < `minimum_count`, `region` < `minimum_count * 4`, `city` >= `minimum_count * 4` + permission)
- [ ] 4.2 RED tests in `backend/tests/test_graph_hidden_absent_parity.py`: hidden cluster response ≡ absent cluster response (status, body shape, no discriminator)
- [ ] 4.3 Aggregate policy enforcement in `graph_lod_service.overview` and `graph_lod_service.detail`
- [ ] 4.4 Hidden ≡ absent response shaping (both produce `cluster: null` + `empty_reason: "hidden_absent"`)
- [ ] 4.5 Re-run `backend/tests/test_graph_full_snapshot.py` to confirm `/graph/full` byte-equality preserved
- [ ] 4.6 GREEN tests; full backend suite green; PR1+PR2 unaffected

## Phase 3: #392 frontend GraphCMDB

### PR4 (overview-on-mount)
- [ ] 5.1 RED test in `frontend/__tests__/GraphCMDB.test.tsx`: mount triggers only `/graph/overview` (no `/graph/full` call in network log)
- [ ] 5.2 `frontend/services/graphLod.ts`: `fetchGraphOverview(filters)` using mirrors from PR #472
- [ ] 5.3 `frontend/components/GraphCMDB.tsx`: replace initial `/graph/full` call with overview fetch
- [ ] 5.4 `frontend/hooks/useGraphTopology.ts` (or equivalent): refactor to support overview-first data shape
- [ ] 5.5 GREEN tests; full frontend suite green

### PR5 (detail hydration)
- [ ] 6.1 RED tests: click cluster → `/graph/detail/{cluster_id}` call; search/filter target commit → same; zoom threshold does NOT trigger fetch
- [ ] 6.2 `frontend/services/graphLod.ts`: `fetchGraphDetail(clusterId, filters)`
- [ ] 6.3 `frontend/components/GraphCMDB.tsx`: click/expand and search/filter handlers call detail endpoint
- [ ] 6.4 Delimited subgraph merge: render detail payload as separate sub-scene with visual boundary cue
- [ ] 6.5 GREEN tests; full frontend suite green; PR4 unaffected

### PR6 (fallback + cleanup)
- [ ] 7.1 RED tests: LOD endpoint 500 → fallback to `/graph/full`; LOD endpoint network error → fallback; zoom threshold never triggers fetch (verify no fetch on `onZoom` handler)
- [ ] 7.2 `frontend/services/graphLod.ts`: error handling, fallback signal
- [ ] 7.3 `frontend/components/GraphCMDB.tsx`: fallback logic on LOD path failure; remove any zoom-triggered fetch handlers
- [ ] 7.4 GREEN tests; full frontend suite green; PR4+PR5 unaffected

## Phase 4: #393 migrate consumers

### PR7 (caller inventory — audit only)
- [ ] 8.1 Audit script (manual or scripted) of all `/graph/full` and `/api/graph/full` call sites in `backend/` and `frontend/`
- [ ] 8.2 `docs/refactoring/cmdb-graph-consumer-inventory.md`: per-consumer table (path, current behavior, decision, reason)
- [ ] 8.3 Decision per consumer: migrate (use overview/detail) or except (keep `/graph/full` with documented limits)
- [ ] 8.4 No code changes in this PR — review is the inventory itself

### PR8 (migration based on audit)
- [ ] 9.1 Implement migrations per W7 audit decisions
- [ ] 9.2 `NetworkVisualizer` migration (if feasible per audit)
- [ ] 9.3 Backward-compat tests: each migrated consumer still works with overview/detail; each excepted consumer still works with `/graph/full`
- [ ] 9.4 Polling/cache behavior normalized across consumers (avoid duplicate full-graph pressure)
- [ ] 9.5 GREEN tests; full suite green

## Phase 5: Activation of #214

- [ ] 10.1 After #393 tracker merges, move #214 from `status:needs-review` to `status:approved` with comment referencing #393 closure

## Critical sequencing

- Phase 2 PR1 must precede PR2 (detail uses overview's auth/scoping foundation)
- Phase 2 PR3 must follow PR1 + PR2 (disclosure enforcement wraps both)
- Phase 3 PR4 depends on Phase 2 PR1 merged (frontend needs the endpoint)
- Phase 3 PR5 depends on Phase 2 PR2 merged (detail endpoint)
- Phase 3 PR6 depends on Phase 2 PR3 merged (parity guarantees the fallback shape)
- Phase 4 PR7 must precede PR8 (audit feeds migration)
- Phase 5 happens after Phase 4 PR8 tracker merges

## Cross-references

- Contract slice: PR #468 (v1.17.6), `openspec/changes/archive/2026-09-10-feat-390-lod-contracts/`
- Parent epic: #230 (archived), `openspec/changes/archive/2026-07-08-cmdb-graph-level-of-detail/`
- Dependent issue for activation: #214 (visual editor scaling)
- Reference PR pattern: PR #468 with child PRs #469 / #471 / #472