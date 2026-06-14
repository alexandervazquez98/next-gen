# Tasks: Category Technology Icons

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 900-1300 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 backend contract → PR 2 shared frontend primitives → PR 3 admin selector → PR 4 surfaces |
| Delivery strategy | force-chained |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Persist and expose category icon metadata | PR 1 | Backend tests/code; preserves `/nodes.type`. |
| 2 | Add shared frontend icon types/resolver/component | PR 2 | Depends on PR 1 API contract. |
| 3 | Add admin visual icon selector | PR 3 | Depends on PR 2 primitives. |
| 4 | Migrate inventory, monitoring, map, topology, and detail surfaces | PR 4 | Depends on PR 2; keep status separate. |

## Phase 1: Backend Contract and Defaults

- [x] 1.1 RED: Add tests in `backend/tests/test_routers_catalog.py` for `icon_key` reads, saves, invalid rejection, and generic/default behavior.
- [x] 1.2 RED: Add tests in `backend/tests/test_node_service.py` and `backend/tests/test_topology_repo_nodes.py` proving `/nodes.type` remains compatible and `category_icon_key` is added.
- [x] 1.3 GREEN: Create `backend/services/category_icons.py` with controlled keys, defaults, normalization, validation, and generic fallback.
- [x] 1.4 GREEN: Update `backend/models/core.py`, `backend/services/catalog_service.py`, `backend/routers/catalog.py`, `backend/repositories/topology_repo.py`, and `backend/services/node_service.py` for persisted `icon_key` and node metadata.
- [x] 1.5 REFACTOR: Run `cd backend && python -m pytest backend/tests/test_routers_catalog.py backend/tests/test_node_service.py backend/tests/test_topology_repo_nodes.py` and simplify duplicated fallback logic.

## Phase 2: Shared Frontend Primitives

- [x] 2.1 RED: Add Vitest coverage in `frontend/utils/categoryIcons.test.ts` and `frontend/components/CategoryIcon.test.tsx` for lookup, search, fallback, and no blank icon.
- [x] 2.2 GREEN: Update `frontend/types.ts` and `frontend/services/queryResources.ts` for `CategoryRecord.icon_key` and `GraphNode.category_icon_key`.
- [x] 2.3 GREEN: Create `frontend/utils/categoryIcons.ts` and `frontend/components/CategoryIcon.tsx` using controlled Material Symbols and status-agnostic semantics.
- [x] 2.4 REFACTOR: Run `cd frontend && corepack pnpm test:run -- categoryIcons CategoryIcon queryResources` and remove local duplicate icon mappings.

## Phase 3: Admin Selector

- [x] 3.1 RED: Extend `frontend/components/CatalogManager.test.tsx` or nearest catalog test for current icon, search grid, preview, generic option, and save flow.
- [x] 3.2 GREEN: Update `frontend/components/CatalogManager.tsx` and `frontend/components/HardwareCatalog.tsx` to show/edit category icons via the shared primitives.
- [x] 3.3 REFACTOR: Run targeted catalog frontend tests and keep selector state isolated from category rename/edit state.

## Phase 4: System-Wide Rendering

- [x] 4.1 RED: Extend tests for `frontend/components/GlobalInventory.tsx`, `MonitoringConsole.tsx` live stream and event-detail category strip, topology/map/detail components to assert shared technology icons and separate status indicators.
- [x] 4.2 GREEN: Migrate `GlobalInventory.tsx`, `MonitoringConsole.tsx`, `DependencyMiniMap.tsx`, `NetworkVisualizer.tsx`, `VisualRelationshipEditor.tsx`, `MassLinkEditor.tsx`, and `CIDetailModal.tsx` to `CategoryIcon`.
- [x] 4.3 REFACTOR: Run `cd frontend && corepack pnpm test:run` plus `cd backend && python -m pytest`, then update this checklist with completed PR slice evidence (completed under maintainer-approved scoped verification exception; backend full suite remains red and is tracked in issue #267).
