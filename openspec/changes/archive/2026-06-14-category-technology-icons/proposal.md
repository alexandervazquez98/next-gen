# Proposal: Category Technology Icons

## Intent

Create a catalog-owned icon system so operators recognize technology type across maps, topology, inventory, monitoring, detail, and catalog views. Icons represent technology type only, not operational status; unknown categories keep a generic fallback.

## Scope

### In Scope
- Add icon metadata and defaults for Layer 2 switch, Layer 3 switch, router, server, SaaS, storage, cameras, and video analytics.
- Allow admin users to edit category/icon association from the catalog UI.
- Expose metadata through category APIs and a shared frontend resolver/component.
- Preserve `/nodes` UI assumptions while improving category/type icon rendering.

### Out of Scope
- Operational status icons, severity indicators, or status color replacement.
- Hardware model, vendor, or instance-level icon overrides.
- Full visual redesign of topology, maps, or inventory screens.

## Capabilities

### New Capabilities
- `category-technology-icons`: Category icon metadata, admin editing, fallback behavior, migration/backfill, and shared UI rendering.

### Modified Capabilities
- None. Existing `audit-logging` requirements remain unchanged.

## Approach

Use the exploration-recommended hybrid model: store icon metadata on catalog categories, seed/backfill defaults, expose metadata through category endpoints, and centralize frontend resolution with fallbacks. Keep status color/health separate from technology icons. Maintain compatibility with `/nodes` consumers that rely on category values mapped into `type`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/models/core.py` | Modified | Add category icon metadata fields. |
| `backend/services/catalog_service.py` | Modified | Read/write icon associations and defaults. |
| `backend/routers/catalog.py` | Modified | Extend category API contracts. |
| `backend/repositories/topology_repo.py`, `backend/services/node_service.py` | Modified | Preserve category/type compatibility. |
| `frontend/services/queryResources.ts`, `frontend/types.ts` | Modified | Type and fetch category icon metadata. |
| `frontend/components/CatalogManager.tsx`, `HardwareCatalog.tsx` | Modified | Admin icon editing UI. |
| `frontend/components/*map*`, `*Topology*`, `GlobalInventory.tsx`, `MonitoringConsole.tsx`, `CIDetailModal.tsx` | Modified | Use shared technology icon rendering. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Breaking `/nodes` category-as-`type` consumers | Med | Preserve payload compatibility and add regression tests first. |
| Inconsistent visuals remain scattered | Med | Use one resolver/component and migrate surfaces through chained PRs. |
| Unknown categories render blank | Low | Require generic fallback in backend/client contracts. |

## Rollback Plan

Revert API/schema/UI changes and seeded metadata; frontend generic fallbacks keep legacy category rendering usable.

## Dependencies

- Strict TDD is required.
- Chained PRs are required later due to the 400-line review budget; strategy is not selected yet.

## Success Criteria

- [ ] Admins can assign/edit category icons from UI.
- [ ] Initial technology types have defaults; unmapped categories show generic icons.
- [ ] Maps, topology, inventory, monitoring, detail, and catalog use consistent technology icons without status/icon confusion.
