# Design: Category Technology Icons

## Technical Approach

Add catalog-owned `icon_key` metadata to Neo4j `Category` nodes and expose it through existing catalog and node/category contracts. The backend validates icon keys against a controlled catalog, seeds/backfills defaults, and preserves `/nodes.type` as the existing category-as-type value. The frontend centralizes category icon lookup/rendering so catalog, inventory, monitoring map, topology, and detail views share one fallback-safe component while status indicators remain separate.

## Architecture Decisions

| Option | Tradeoff | Decision |
|---|---|---|
| Store `icon_key` on `Category` nodes | One source of truth; requires API/test updates | Use `Category.icon_key` with generic fallback. |
| Frontend-only mapping | Fast but not admin-editable or persisted | Reject except as client fallback for legacy/missing metadata. |
| Custom uploads | Flexible but adds asset security/storage scope | Reject for v1; use controlled Material Symbols catalog. |
| Put icon metadata directly on `/nodes` | Easy rendering but risks bloating node contract | Add optional `category_icon_key` while keeping `type` unchanged. |

## Data Flow

```text
Admin selector -> PUT /categories/{name} -> catalog_service validates icon_key
              -> (:Category {name, icon_key})

/categories -> CategoryRecord[] -> useCategoriesQuery -> icon resolver/component
/nodes      -> node_service keeps type=category and adds category/category_icon_key
             -> maps/topology/inventory render technology icon + separate status
```

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/models/core.py` | Modify | Extend `Category` with optional `icon_key`. |
| `backend/services/category_icons.py` | Create | Allowed icon catalog, defaults, normalization, validation, generic fallback. |
| `backend/services/catalog_service.py` | Modify | Return/set `icon_key`, preserve it on rename, seed/backfill defaults on category create/read. |
| `backend/routers/catalog.py` | Modify | Replace `List[Dict[str,str]]` contract with typed category response/update accepting optional `icon_key`. |
| `backend/repositories/topology_repo.py` | Modify | Return `c.icon_key as category_icon_key` from `get_nodes`. |
| `backend/services/node_service.py` | Modify | Keep `type = category or layer`; add `category` and `category_icon_key` fields without removing current keys. |
| `frontend/types.ts` | Modify | Add `CategoryRecord.icon_key`, `GraphNode.category_icon_key`, and loosen runtime category/type expectations safely. |
| `frontend/services/queryResources.ts` | Modify | Update category API types. |
| `frontend/components/CategoryIcon.tsx` | Create | Shared Material Symbols renderer with default fallback and status-agnostic semantics. |
| `frontend/utils/categoryIcons.ts` | Create | Controlled catalog, defaults, lookup by category/icon key, search helpers. |
| `frontend/components/CatalogManager.tsx` | Modify | Add visual icon selector with current icon, search grid, preview, and generic option. |
| `frontend/components/HardwareCatalog.tsx` | Modify | Display category icons next to category labels. |
| `frontend/components/GlobalInventory.tsx` | Modify | Render category icons in list and detail chips. |
| `frontend/components/MonitoringConsole.tsx` | Modify | Add technology icon overlays/markers while retaining `STATUS_COLORS` for health. |
| `frontend/components/DependencyMiniMap.tsx`, `frontend/components/NetworkVisualizer.tsx`, `frontend/components/VisualRelationshipEditor.tsx`, `frontend/components/MassLinkEditor.tsx`, `frontend/components/CIDetailModal.tsx` | Modify | Replace scattered category/type visuals with shared renderer. |

## Interfaces / Contracts

```ts
type CategoryIconKey = "generic" | "switch_l2" | "switch_l3" | "router" | "server" | "saas" | "storage" | "camera" | "video_analytics";
interface CategoryRecord { name: string; icon_key?: CategoryIconKey | null; }
interface GraphNode { type: string; category?: string; category_icon_key?: CategoryIconKey | null; }
```

Backend rejects unknown `icon_key` with 422/400 and leaves previous metadata unchanged. Missing/null resolves to `generic` on both backend responses and frontend rendering.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Backend unit | Icon validation/default resolution and generic fallback | Add tests for `category_icons.py` before implementation. |
| Backend router/service | `/categories` returns/updates `icon_key`; invalid keys rejected; rename preserves metadata | Extend `backend/tests/test_routers_catalog.py`; add catalog service tests with mocked Neo4j. |
| Backend node compatibility | `/nodes` keeps category-as-`type` and adds icon metadata | Extend `backend/tests/test_node_service.py` and `backend/tests/test_topology_repo_nodes.py`. |
| Frontend unit | Resolver/component fallback, searchable selector, no blank icon | Add Vitest tests for `categoryIcons` and `CategoryIcon`. |
| Frontend integration | Catalog save flow and key surfaces render icons separate from status | Extend `GlobalInventory`, `MonitoringConsole`, topology/detail tests. |

Strict TDD applies: write failing tests for each slice before code, then implement and refactor.

## Migration / Rollout

No destructive migration. Add an idempotent Neo4j backfill in catalog service/startup or an explicit admin-safe script to set default `icon_key` for Layer 2 switch, Layer 3 switch, router, server, SaaS, storage, cameras, and video analytics by normalized category name. Existing categories without a match remain unset in storage but resolve to `generic` in API/UI. Roll out in chained PRs: backend contract/defaults first, shared frontend resolver second, admin selector third, surfaces fourth.

## Open Questions

- [ ] None blocking. Chained PR strategy is required later but not selected in this phase.
