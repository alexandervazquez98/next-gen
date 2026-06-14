## Exploration: Category Technology Icons

### Current State
Categories are Neo4j `Category` nodes identified only by `name`. CI creation/upsert stores both `CI.layer = node.type` and a `(:CI)-[:CATEGORIZED_AS]->(:Category)` relationship; `/nodes` returns the resolved category as `type` rather than a separate `category` field. Hardware catalog entries link to categories via `(:HardwareModel)-[:BELONGS_TO]->(:Category)`, but categories currently have no icon/color metadata. Frontend visuals use category/type strings inconsistently: some screens show text badges, some use hard-coded Material Symbols by broad node type, and map markers are status-colored circles without technology icons.

### Affected Areas
- `backend/models/core.py` — `Category` is `name` only; API schemas would need icon metadata if icons are catalog-driven.
- `backend/services/catalog_service.py` — category CRUD and hardware catalog queries are the central place to read/write category metadata and migration defaults.
- `backend/routers/catalog.py` — `/categories` response model currently exposes `List[Dict[str, str]]`; mutations accept only category names.
- `backend/repositories/topology_repo.py` — CI upsert/bulk import creates categories from `node.type`; `/nodes` resolves `c.name as category` but `node_service` maps it into `type`.
- `backend/services/node_service.py` — node payload normalization currently loses the separate `category` field; this affects all frontend consumers.
- `backend/services/event_service.py` — availability and SNMP reports already include `category`; icon metadata could be enriched here or resolved on the client.
- `frontend/types.ts` — `GraphNode` has optional `category`, but backend `/nodes` often returns category as `type`; `NodeType` is a narrow broad-type union while runtime categories include values like `NETWORK`.
- `frontend/services/queryResources.ts` and `frontend/hooks/queries/useMonitoringConsoleData.ts` — category records and filter options are name-only today.
- `frontend/components/CatalogManager.tsx` and `frontend/components/HardwareCatalog.tsx` — category management UI is the natural place to select/edit category icons.
- `frontend/components/GlobalInventory.tsx`, `MonitoringConsole.tsx`, `CIDetailModal.tsx`, `DependencyMiniMap.tsx`, `NetworkVisualizer.tsx`, `VisualRelationshipEditor.tsx`, `MassLinkEditor.tsx` — visual category/type rendering is spread across badges, maps, SVG/D3, 3D graph, and filtering.
- `frontend/constants.tsx` — contains a broad `ICONS` map for `SERVICE`, `INFRASTRUCTURE`, etc.; not connected to catalog categories.
- Tests: `backend/tests/test_routers_catalog.py`, `backend/tests/test_node_service.py`, `backend/tests/test_topology_repo_nodes.py`, `frontend/components/__tests__/MonitoringConsole*.tsx`, `frontend/components/GlobalInventory.test.tsx`, `frontend/hooks/queries/useMonitoringConsoleData.test.tsx` — likely regression points under strict TDD.

### Approaches
1. **Catalog-owned category icon metadata** — Add icon fields to `Category` nodes and expose them through `/categories`; frontend resolves icons from category catalog with safe fallback icons.
   - Pros: Single source of truth; supports migration defaults; allows admin-managed icons; avoids duplicating mappings in every UI.
   - Cons: Requires backend schema/API changes, frontend type updates, migration/backfill, and UI changes.
   - Effort: Medium

2. **Frontend-only category-to-icon registry** — Keep backend categories name-only and add a client utility mapping known category strings to Material Symbols.
   - Pros: Fast, minimal backend risk, easy to test in UI helpers.
   - Cons: Not catalog-driven, no admin configurability, migration is just code defaults, and unknown categories degrade silently.
   - Effort: Low

3. **Hybrid default registry plus catalog override** — Seed default icon/color metadata for existing categories, expose/edit via catalog, and keep frontend fallback registry for legacy/unknown records.
   - Pros: Best migration story; resilient during rollout; keeps icons reflected system-wide while preventing blank UI for old data.
   - Cons: More moving parts and likely exceeds one reviewable PR, so chained delivery is required.
   - Effort: Medium/High

### Recommendation
Use the hybrid approach. Store `icon` and optionally `color`/`description` on `Category` nodes, add a migration/backfill for existing categories, expose metadata through `/categories`, and centralize frontend icon resolution in one utility/component used across catalog, inventory, monitoring, detail, and graph views. Keep frontend fallbacks for categories without metadata and broad node types such as `SERVICE`/`INFRASTRUCTURE`.

Product questions for proposal: Which icon source is allowed (Material Symbols only, custom SVGs, or both)? Should admins choose icons, or should the system assign fixed icons? Are icons by category only, or can hardware model/brand override the category icon? Is color part of the technology identity or status-only? What are the initial canonical categories and their default icons?

### Risks
- Existing `/nodes` maps category into `type`; changing this carelessly may break filters, tests, and visual layouts that expect `node.type`.
- Category rename/delete currently changes/deletes `Category` nodes without explicit migration semantics for icon metadata and relationships.
- Visual rendering is scattered; without a shared frontend resolver, behavior will remain inconsistent.
- Backend tests currently assume category payloads are name-only; strict TDD requires contract tests before implementation.
- Chained PRs are required later because backend schema/API, migration, and multiple UI surfaces likely exceed the 400 changed-line review budget.

### Ready for Proposal
Yes — proceed to proposal after the orchestrator confirms the product questions above, especially icon source, admin editability, and whether category is the only technology identity dimension.
