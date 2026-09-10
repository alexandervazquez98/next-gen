# Design: feat(cmdb) finalize LOD graph overview and detail contracts (#390)

## Technical Approach

Schema-first additive contract slice. DTOs in `backend/schemas/graph.py`. Value objects in `backend/contracts/` (pure functions, no IO). Revision is a DI stub — algorithm pinned here, real impl needs not-yet-built repo queries (#391). Cursor is `base64url(json({cluster_id, filters_hash, revision, principal_hash, nonce}))` — stateless, revocable via `(revision, principal_hash)`. TS mirrors in `frontend/types/graph.ts`. Cross-layer fixtures in `fixtures/graph-contracts/*.json` shared by pytest and Vitest so drift breaks both suites. `safe_geo_precision` is tiered from `visible_count` vs `minimum_count`. Codec tests use `pytest.mark.parametrize` (Hypothesis not in deps). No backend query, route, consumer, or `/graph/full` byte changes. Frozen snapshot test pins `/graph/full`. Runtime implementation of additive endpoints, the `graph:aggregate_breakdown:read` permission, and the detail projection helper all live in #391.

## File Impact

| File | Action | Description |
|------|--------|-------------|
| `backend/schemas/graph.py` | Create | Pydantic DTOs: `OverviewResponse`, `OverviewCluster`, `InterClusterLink`, `Legend`, `Page`, `AggregatePolicy`, `SafeGeoPrecision`, `DetailResponse`, `DetailCluster`, `DetailNode`, `DetailLink`, `BoundaryStub`, `ProjectionFlags`, `SensitiveSource`, `EmptyReason`. Plus structured errors. |
| `backend/contracts/cluster_id.py` | Create | `ClusterId` parse/render, `__unassigned__` sentinel, case-insensitive match / case-preserving display. |
| `backend/contracts/cursor.py` | Create | Cursor encode/decode; bind `(cluster_id, filters_hash, revision, principal_hash, nonce)`; raises `InvalidCursorError` / `StaleCursorError`. |
| `backend/contracts/revision.py` | Create | `Revision` opaque string; algorithm pinned; `Revision("test-revision-0001")` stub injector. |
| `backend/contracts/aggregate_policy.py` | Create | `AggregatePolicy` + `derive_safe_geo_precision(visible_count, minimum_count)`. |
| `backend/contracts/projection.py` | Create | `DetailProjectionPolicy` Protocol — interface only, no impl. |
| `backend/tests/test_graph_contracts.py` | Create | Parametrize matrix per codec, DTO, spec scenario. |
| `backend/tests/test_graph_full_snapshot.py` | Create | TestClient vs `get_full_graph`; asserts byte-equality vs frozen fixture. |
| `fixtures/graph-contracts/*.json` | Create | Authorized, empty-scope, single-cluster, hidden-present, low-cardinality, multi-page overview; visible, no-visible-members, hidden, absent, boundary-stub, error detail. |
| `fixtures/graph-full/frozen_response.json` | Create | Captured today from live `/graph/full`. |
| `frontend/types/graph.ts` | Create | TS mirrors of every Pydantic DTO. |
| `frontend/services/graphContract.ts` | Create | `fetchGraphOverview(filters)`, `fetchGraphDetail(clusterId, filters)` request builders. |
| `frontend/__tests__/graphContract.test.ts` | Create | TS snapshots, null/omission, field-name parity vs backend fixtures. |

No edits to `backend/routers/`, `backend/services/`, `backend/repositories/`, `backend/models/user.py`, `backend/routers/links.py`, or any frontend component.

## Interfaces / Contracts

**ClusterId.** Regex `^(?P<axis>location):(?P<key>[A-Za-z0-9._\-]{1,128})$`. Reserved `location:__unassigned__` -> display `Unassigned`. Keys normalize lowercase for matching; `display_label` preserves canonical case. Reject: empty / whitespace / contains `:` or `/` / length > 128 / axis != `location`. Error: `{"error": "invalid_cluster_id", "reason": "<text>", "cluster_id": "<original>"}` — NO label/count/geo in body. Conflicting `?axis=` returns `{"error": "axis_conflict"}` BEFORE authorization-sensitive lookup.

**Cursor.** `encode = base64url(json({v:1, cluster_id, filters_hash, revision, principal_hash, nonce}))` where `filters_hash = sha256(canonical_json(filters)).hexdigest()[:16]`, `principal_hash = sha256(sorted(principal.permission_set))[:16]`. Parse failure -> 400 `invalid_cursor`. Revision mismatch -> 409 `stale_cursor` with `current_revision`. Principal mismatch -> 400 `stale_cursor` / `permission_changed`.

**Revision (pinned, impl in #391).** `Revision.derive(snapshot) = "rev-" + sha256(snapshot).hexdigest()[:16]`. Tests inject `Revision("test-revision-0001")`.

**AggregatePolicy.** `SafeGeoPrecision ∈ {city, region, none}`. `minimum_count = 5` (configurable). `permission_required = "graph:aggregate_breakdown:read"`. `derive_safe_geo_precision(visible_count, min)` returns `none` if `< min`, `region` if `< min*4`, else `city`.

**DetailProjectionPolicy (Protocol only).** `apply_to_node(node, principal) -> DetailNode`; `show_sensitive_metadata(principal, requested) -> bool`; `sensitive_source(principal, allowed) -> SensitiveSource`. `show_sensitive_metadata` default ALWAYS `False`; `True` requires BOTH `graph:aggregate_breakdown:read` AND `?sensitive=include`. Endpoint MUST NEVER default to `True`.

**Boundary stubs.** `visible_link_count` = count of boundary links (one endpoint in requested cluster, other in adjacent cluster) AS VISIBLE TO THE CALLER. Stubs whose adjacent cluster is hidden are NEVER emitted. Below `minimum_count` -> `{redacted: true, redaction_reason: "low_cardinality"}`.

## Open-question resolutions

1. **`safe_geo_precision`**: tiered enum per `derive_safe_geo_precision`. Thresholds tunable per deployment; shape fixed.
2. **Cursor revocation**: binds `(cluster_id, filters_hash, revision, principal_hash, nonce)`. Principal mismatch -> 400 `stale_cursor` / `permission_changed`. Revision drift -> 409 with `current_revision`.
3. **Overview paging**: `page_size = 100`, `paging_engaged_when > 100` visible clusters. Defaults pinned; per-deployment knobs.
4. **`show_sensitive_metadata` default**: `False` always. `True` only with BOTH permission AND `?sensitive=include`. MUST NEVER default to `True`.
5. **`boundary_stubs` aggregation**: `visible_link_count` = count of boundary links AS VISIBLE TO THE CALLER. Hidden-adjacent stubs NEVER emitted. Below `minimum_count` -> redacted.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Backend unit | Codecs, DTO serialization, error paths, suppression tiers, projection-policy conformance | `pytest.mark.parametrize`; ~80+ cases; no IO. |
| Backend integration | `/graph/full` byte-equality | `test_graph_full_snapshot.py` via TestClient. |
| Backend spec map | All 43 spec scenarios | Parametrize `(req_id, scenario_id, expected)`; CI fails if any scenario has no test. |
| Frontend unit | TS snapshots, null/omission for 5 sensitive fields | Vitest `toMatchSnapshot`. |
| Cross-layer | Field-name parity Pydantic vs TS | `parity.test.ts` enumerates fixture keys vs TS type. |
| Strict TDD | Every spec scenario -> named test | Coverage gate in CI. |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS, executable-file, or process-integration boundary introduced. New endpoints and `/graph/full` snapshot run inside existing TestClient.

## Migration / Rollout

No migration. `/graph/full` is frozen. Rollback = `git revert` of #390 commits; no runtime wire touched.

## Out of Scope (explicit)

Neo4j queries; route handlers; consumer migration; `/graph/full` redaction; `graph:aggregate_breakdown:read` permission (prereq for #391); `DetailProjectionPolicy` impl; `Revision` impl (stubbed).

## Prerequisites for #391

Add `graph:aggregate_breakdown:read` to `UserPermission`; implement `DetailProjectionPolicy` reusing `/graph/full` policy; implement `Revision.derive(...)`.

## Open Questions

None — all five spec open questions are resolved above.