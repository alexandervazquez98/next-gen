# Tasks: feat(cmdb) finalize LOD graph overview and detail contracts (#390)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 250–350 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | single PR on branch `feat/390-lod-contracts` |
| Delivery strategy | single-pr |
| Chain strategy | stacked-to-main |
| Files changed | 13 new (+ 0 modified) |

```text
Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: stacked-to-main
400-line budget risk: Low
```

### Suggested Work Units

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|----------------------|-----------------|-------------------|
| W1 | Backend DTOs + value objects + snapshot guard | `pytest backend/tests/test_graph_contracts.py backend/tests/test_graph_full_snapshot.py backend/tests/test_spec_coverage_graph.py -q` | `curl http://localhost:18000/api/graph/full` (N/A CI; manual W1-T1) | revert `backend/schemas/graph.py`, `backend/contracts/`, `backend/tests/test_graph_*.py`, `fixtures/graph-full/` |
| W2 | TS mirrors + cross-layer fixtures + parity gate | `cd frontend && npx vitest run __tests__/graphContract.test.ts __tests__/parity.test.ts` | `cd frontend && npx tsc --noEmit` (N/A; types + Vitest) | revert `frontend/types/graph.ts`, `frontend/services/graphContract.ts`, `frontend/__tests__/graphContract.test.ts`, `frontend/__tests__/parity.test.ts`, `fixtures/graph-contracts/` |

## Phase 1: Frozen snapshot

- [x] 1.1 Capture `/graph/full` → `fixtures/graph-full/frozen_response.json` (live curl); `jq 'keys'` = `["links","nodes"]`. **REQ-3**. MUST precede 2.1.

## Phase 2: Backend contracts (W1)

- [x] 2.1 `backend/contracts/cluster_id.py`: `ClusterId` parse/render, `__unassigned__` sentinel, regex `^(?P<axis>location):(?P<key>[A-Za-z0-9._\-]{1,128})$`, case-insensitive match / case-preserving display; reject empty/`:`/`/`/>128/axis!=`location`. Error `{error:"invalid_cluster_id", reason, cluster_id}` no metadata. **REQ-4**.
- [x] 2.2 RED tests in `backend/tests/test_graph_contracts.py`: valid parse, sentinel, case-collapse, reject invalid, error shape no metadata, `?axis=tenant` → 400 `axis_conflict` before authorization. **REQ-4**.
- [x] 2.3 `backend/contracts/aggregate_policy.py`: enum `SafeGeoPrecision ∈ {city, region, none}`, `minimum_count=5`, `permission_required="graph:aggregate_breakdown:read"`, `derive_safe_geo_precision(visible, min)` → `<min` none, `<min*4` region, else city. **REQ-9**.
- [x] 2.4 `backend/contracts/cursor.py`: `encode` → base64url JSON `{v:1, cluster_id, filters_hash=sha256(canonical_json(filters)).hexdigest()[:16], revision, principal_hash, nonce}`; `decode` raises `InvalidCursorError` (400), `StaleCursorError` (409+`current_revision`), `PermissionChangedError` (400). **REQ-5**.
- [x] 2.5 `backend/contracts/revision.py`: `Revision("test-revision-0001")` stub, `.value: str`, docstring-only `derive` (impl #391). **REQ-6**.
- [x] 2.6 `backend/contracts/projection.py`: `DetailProjectionPolicy` Protocol — `apply_to_node`, `show_sensitive_metadata` (default False; True only with permission AND requested=True), `sensitive_source`. NO impl. **REQ-2, REQ-9**.

## Phase 3: Backend DTOs (W1)

- [x] 3.1 `backend/schemas/graph.py`: Pydantic v2 — `OverviewResponse`, `OverviewCluster`, `InterClusterLink`, `Legend`, `Page`, `AggregatePolicy`, `SafeGeoPrecision`, `DetailResponse`, `DetailCluster`, `DetailNode`, `DetailLink`, `BoundaryStub`, `ProjectionFlags`, `SensitiveSource`, `EmptyReason` (`none|no_visible_members|hidden_absent|unavailable`); error bodies. **REQ-1, REQ-2, REQ-7, REQ-8, REQ-9**.
- [x] 3.2 Append serialization tests to `backend/tests/test_graph_contracts.py`: each DTO round-trip, 5 sensitive-field omission in overview, `cluster: null`+`empty_reason:"unavailable"` for hidden/absent. Split 3.2a/3.2b if >80 LOC test.

## Phase 4: Guards (W1)

- [x] 4.1 `backend/tests/test_graph_full_snapshot.py`: TestClient → `/api/graph/full`; byte-equality vs frozen fixture, `nodes`/`links` keys present, no added/removed fields, ordering preserved 2 calls. **REQ-3**.
- [x] 4.2 `backend/tests/test_spec_coverage_graph.py`: parse spec, extract `#### Scenario:` IDs, assert each named in `@pytest.mark.parametrize` id. CI gate. **REQ-1..9**.

## Phase 5: Cross-layer fixtures (W2)

- [x] 5.1 `fixtures/graph-contracts/*.json` (12 files): `overview_{authorized,empty_scope,single_cluster,hidden_present,low_cardinality,multi_page}`, `detail_{visible,no_visible_members,hidden,absent,boundary_stub,error}`. Validates vs Phase 3 DTOs. **REQ-1, REQ-2, REQ-7, REQ-9**.

## Phase 6: Frontend mirrors + parity gate (W2)

- [x] 6.1 `frontend/types/graph.ts`: TS mirrors of every Pydantic DTO, enums as `as const` literal unions. Follows `frontend/types/itsm.ts` — no edit to root `frontend/types.ts`. **REQ-1, REQ-2, REQ-8**.
- [x] 6.2 `frontend/services/graphContract.ts`: `fetchGraphOverview(filters)`, `fetchGraphDetail(clusterId, filters)`. `npx tsc --noEmit` clean. **REQ-1, REQ-2**.
- [x] 6.3 `frontend/__tests__/graphContract.test.ts`: Vitest locks field names + null/omission vs Phase 5 fixtures; 5 sensitive fields never in overview; hidden ≡ absent body shape. **REQ-1, REQ-2, REQ-7, REQ-9**.
- [x] 6.4 `frontend/__tests__/parity.test.ts` (CI gate): enumerate fixture keys vs TS types; fail if any key missing either side. **REQ-1, REQ-2** drift guard.

## Critical sequencing

- 1.1 MUST precede 2.1 — byte-equality (4.1) needs clean baseline.
- 3.1–3.2 depend on 2.6. 5.1 depends on 3.1. 6.3 + 6.4 depend on 5.1 + 6.1.