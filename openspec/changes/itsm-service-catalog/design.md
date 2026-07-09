# Design: ITSM Service Catalog Foundation + Ticket/Folio CRUD

This first slice adds two independent ITSM domains: a dedicated Service Catalog for operational service/SLA metadata and a Ticket/Folio workflow for `request` and `incident` records. Event response behavior remains unchanged; the design keeps stable identifiers and boundaries so future work can associate events to folios without retrofitting this slice.

## Discovery note

CodeGraph was required first for structural exploration, but this delegated environment exposes only file read/search tools and no shell or CodeGraph MCP tool. I could not run `git rev-parse`, inspect `.codegraph/`, or initialize/explore CodeGraph from here. Fallback was limited to targeted reads/searches of known artifacts and concrete project files referenced by the exploration/proposal: `backend/models/core.py`, `backend/services/event_service.py`, `backend/routers/*`, `backend/database.py`, `backend/postgres_db.py`, `frontend/App.tsx`, `frontend/services/api.ts`, and existing test conventions.

## Architecture decisions

| Area | Decision | Rationale |
|---|---|---|
| Service Catalog persistence | Extend the existing Neo4j `ServiceCatalog` node as the ITSM source of truth. | Current event SLA fallback already reads `(:ServiceCatalog)` through `BusinessService -> USES_SLA -> ServiceCatalog`; using the same graph label avoids dual-write and keeps event compatibility. |
| Service Catalog field compatibility | Store new fields (`service_id`, `name`, `owner_team`, `category`, `tier`, `criticality`, `sla_target_minutes`, `active`, audit fields) and keep compatibility aliases (`id`, `service_tier`, `sla_minutes`) synchronized. | Existing Pydantic/event response contracts expose `id`, `service_tier`, and `sla_minutes`; additive fields avoid breaking current SLA behavior. |
| Ticket/Folio persistence | Store `TicketFolio` nodes in Neo4j, independent from events. | Folios will later relate naturally to events and catalog services; first-slice CRUD remains independent by not creating event relationships. |
| Postgres boundary | Do not add ITSM tables to Postgres in this slice. | Current Postgres usage is auth/session/audit/runtime locking oriented; Neo4j already owns operational topology/events/SLA relationships. Avoid cross-store transactions. |
| API boundary | Add new routers under explicit ITSM paths: `/api/itsm/service-catalog` and `/api/itsm/tickets`. | Prevents collision with existing inventory endpoints such as `/api/categories`, `/api/hardware`, and the frontend “CI Inventory”/Catalog manager. |
| Validation | Put Pydantic request/response schemas in `backend/models/itsm.py`; enforce domain rules in services before repository writes. | Keeps routers thin, makes RED tests deterministic, and prevents partial writes on invalid payloads. |
| Lifecycle | Centralize status transitions in a pure state machine: `open -> in_progress -> in_validation -> resolved -> closed`. | The lifecycle must reject skips, regressions, and reopening closed folios consistently across API and service tests. |
| Permissions | Use existing admin-level authorization for the first slice, preferably `ADMIN` or `CI_EDIT` for writes and `EVENT_VIEW`/authenticated user for reads until dedicated `ITSM_*` permissions are introduced. | Proposal allows existing admin-level auth; adding a role migration can be a follow-up if product needs finer-grained ITSM permissions. |
| Frontend placement | Add a separate “ITSM” module/nav section, not a tab inside existing inventory/admin catalog UI. | The spec requires users to distinguish ITSM Service Catalog from inventory catalog/CI management. |

## Backend design

### Modules and files

| File | Action | Purpose |
|---|---|---|
| `backend/models/itsm.py` | Create | Pydantic enums, create/update schemas, response schemas for Service Catalog and Ticket/Folio. |
| `backend/repositories/itsm_service_catalog_repo.py` | Create | Neo4j Cypher for catalog CRUD, constraints/bootstrap helpers if needed, and compatibility field mapping. |
| `backend/repositories/ticket_folio_repo.py` | Create | Neo4j Cypher for folio CRUD and list/detail queries. No event relationship writes. |
| `backend/services/itsm_service_catalog_service.py` | Create | Validation orchestration, deterministic defaults, active/deactivate semantics, audit attribution. |
| `backend/services/ticket_folio_service.py` | Create | Ticket validation, lifecycle transition enforcement, service reference validation, close behavior. |
| `backend/routers/itsm_service_catalog.py` | Create | REST endpoints for catalog CRUD. |
| `backend/routers/ticket_folios.py` | Create | REST endpoints for ticket/folio CRUD and status transitions. |
| `backend/main.py` | Modify | Include the two routers with the existing `/api` prefix convention. |
| `backend/models/core.py` | Minimal modify if needed | Keep existing event response models stable; avoid renaming current `ServiceCatalog`/`BusinessContextCatalog`. |

### API contracts

Use no trailing slashes, matching the convention documented in `backend/main.py`.

```text
GET    /api/itsm/service-catalog
POST   /api/itsm/service-catalog
GET    /api/itsm/service-catalog/{service_id}
PUT    /api/itsm/service-catalog/{service_id}
POST   /api/itsm/service-catalog/{service_id}/deactivate

GET    /api/itsm/tickets
POST   /api/itsm/tickets
GET    /api/itsm/tickets/{ticket_id}
PUT    /api/itsm/tickets/{ticket_id}
POST   /api/itsm/tickets/{ticket_id}/transition
```

Deletion should be logical for Service Catalog (`active=false`) to preserve historical SLA references. For tickets, prefer no hard delete in the first slice; if CRUD acceptance requires delete, implement it only as `archived=true` or keep it out of first PR and document the product decision before apply.

### Domain schemas

Service Catalog response fields:

```python
service_id: str
name: str
owner_team: str | None
category: str | None
tier: str | None
criticality: str | None
sla_target_minutes: int
active: bool
created_at: str
updated_at: str
updated_by: str | None
```

Neo4j compatibility properties on the same node:

```text
id = service_id
service_tier = tier
sla_minutes = sla_target_minutes
```

Ticket/Folio response fields:

```python
ticket_id: str
type: Literal["request", "incident"]
title: str
description: str | None
service_catalog_id: str | None
status: Literal["open", "in_progress", "in_validation", "resolved", "closed"]
closed_reason: str | None
created_at: str
updated_at: str
updated_by: str | None
```

`service_catalog_id` is an optional reference in this slice. If provided, validate that the target Service Catalog exists; do not require an event context.

### Neo4j data model

```text
(:ServiceCatalog {
  service_id,
  id,
  name,
  owner_team,
  category,
  tier,
  service_tier,
  criticality,
  sla_target_minutes,
  sla_minutes,
  active,
  created_at,
  updated_at,
  updated_by
})

(:TicketFolio {
  ticket_id,
  type,
  title,
  description,
  service_catalog_id,
  status,
  closed_reason,
  created_at,
  updated_at,
  updated_by
})
```

Optional first-slice relationship:

```text
(:TicketFolio)-[:FOR_SERVICE]->(:ServiceCatalog)
```

This relationship is allowed only when a ticket explicitly references a service. Do not create any relationship between events and folios in this slice.

### Validation and state machine

Implement the transition rule as a pure function in `ticket_folio_service.py`:

```python
TICKET_STATUS_ORDER = ["open", "in_progress", "in_validation", "resolved", "closed"]

def validate_ticket_transition(current: str, next_status: str) -> None:
    # accepts only current_index + 1
```

Rules:

- New tickets always start as `open`; client-provided create status is ignored or rejected consistently.
- `type` must be exactly `request` or `incident`.
- `sla_target_minutes` must be numeric and non-negative.
- Empty `name`/`title` is rejected.
- Invalid writes return deterministic 4xx errors and do not write partial data.
- `closed_reason` is required when transitioning to `closed` if product wants closure audit; otherwise keep optional but persist it when provided.

## Frontend design

### Module placement

Add a top-level sidebar item labeled `ITSM` (or `Service Management`) routed separately from inventory:

```text
/itsm/service-catalog
/itsm/tickets
```

Do not add these screens under the current `AdminPage` Catalog tab, because that tab is CI/inventory oriented (`HardwareCatalog`, categories, owners). The implementation can still require admin-level permissions to render write actions.

### Frontend files

| File | Action | Purpose |
|---|---|---|
| `frontend/types/itsm.ts` | Create | Shared TS types/enums matching backend response contracts. |
| `frontend/services/itsm.ts` | Create | API client functions using existing `api` wrapper. |
| `frontend/hooks/queries/useItsmServiceCatalogQuery.ts` | Create | React Query list/detail hooks and mutations for Service Catalog. |
| `frontend/hooks/queries/useTicketFoliosQuery.ts` | Create | React Query list/detail hooks and mutations for folios/transitions. |
| `frontend/components/itsm/ItsmServiceCatalogPage.tsx` | Create | List + create/edit/deactivate UI. |
| `frontend/components/itsm/TicketFolioPage.tsx` | Create | List + create/edit + transition UI. |
| `frontend/components/itsm/TicketStatusStepper.tsx` | Create | Linear status display/actions. |
| `frontend/App.tsx` | Modify | Add nav item and routes. |

### UX behavior

- Service Catalog list shows `name`, `category`, `tier`, `criticality`, `sla_target_minutes`, and `active`.
- Deactivation is explicit and reversible only if update API permits setting `active=true`; no hard delete by default.
- Ticket/Folio list filters by `type` and `status`.
- Ticket form allows `request`/`incident`, title/description, and optional Service Catalog selection.
- Status transition UX shows only the next valid action. For example, an `open` ticket only offers “Move to in progress”; it must not offer “Resolve”.
- Closed tickets render read-only lifecycle controls.
- Error messages from 4xx validation responses are displayed inline and do not mutate local optimistic state unless the mutation succeeds.

## Event SLA compatibility

Existing event detail behavior must remain stable:

- Do not change `backend/services/event_service.py` event-to-business-context queries for this slice unless tests prove compatibility is preserved.
- Do not mutate historical event SLA snapshots when Service Catalog entries change.
- Existing `BusinessContextCatalog` response fields (`id`, `category`, `service_tier`, `sla_minutes`) remain available.
- New catalog writes keep `id/service_tier/sla_minutes` aliases synchronized so current fallback queries still resolve.
- No event ingestion, acknowledgement, close, recovery, or modal behavior creates or updates `TicketFolio` nodes.

## Future extension point: event manager association

Reserve the following boundary without implementing behavior now:

```text
(:Event)-[:HAS_FOLIO]->(:TicketFolio)
(:TicketFolio)-[:FOR_SERVICE]->(:ServiceCatalog)
```

Future implementation can add an `EventFolioAssociationService` that owns event-driven creation/linking. This first slice must not call that service, register event hooks, or add event router endpoints that link folios. Keep the extension documented through stable IDs (`event.id`, `ticket_id`, `service_id`) and independent service methods:

```python
def create_ticket_folio(payload, *, actor: str | None = None) -> TicketFolioResponse: ...
def get_ticket_folio(ticket_id: str) -> TicketFolioResponse: ...
def transition_ticket_folio(ticket_id: str, next_status: str, *, actor: str | None = None) -> TicketFolioResponse: ...
```

A future association service should consume these APIs rather than bypassing lifecycle validation.

## Migration and data backfill

### Required migration/bootstrap

Add Neo4j constraints/indexes during startup or via a small idempotent migration script:

```cypher
CREATE CONSTRAINT service_catalog_service_id IF NOT EXISTS
FOR (s:ServiceCatalog) REQUIRE s.service_id IS UNIQUE;

CREATE INDEX service_catalog_active IF NOT EXISTS
FOR (s:ServiceCatalog) ON (s.active);

CREATE CONSTRAINT ticket_folio_ticket_id IF NOT EXISTS
FOR (t:TicketFolio) REQUIRE t.ticket_id IS UNIQUE;

CREATE INDEX ticket_folio_status IF NOT EXISTS
FOR (t:TicketFolio) ON (t.status);
```

### Backfill for existing `ServiceCatalog` nodes

If existing nodes have only legacy fields (`id`, `service_tier`, `sla_minutes`), backfill additively:

```cypher
MATCH (s:ServiceCatalog)
SET s.service_id = coalesce(s.service_id, s.id),
    s.name = coalesce(s.name, s.category, s.id),
    s.tier = coalesce(s.tier, s.service_tier),
    s.sla_target_minutes = coalesce(s.sla_target_minutes, s.sla_minutes, 0),
    s.active = coalesce(s.active, true)
```

Do not rewrite event nodes or historical event snapshots. Backfill only Service Catalog node properties required by the new admin CRUD surface.

## Testing strategy under strict TDD

Strict TDD applies. Implementation should produce RED evidence before code and GREEN evidence after code for each slice.

| Layer | RED evidence | GREEN evidence |
|---|---|---|
| Backend service catalog model/service | Tests fail for negative SLA, empty name, default `active=true`, alias mapping, and no partial write. | `pytest backend/tests/test_itsm_service_catalog_service.py` passes with mocked repository/driver. |
| Backend service catalog router | Tests fail for create/list/update/deactivate auth and response shape. | FastAPI TestClient tests pass with service mocked, following existing router test style. |
| Backend ticket lifecycle | Tests fail for invalid type, skipped transition, regression, closed reopening, and valid full sequence. | `pytest backend/tests/test_ticket_folio_service.py` passes with pure state machine and mocked repository. |
| Backend event compatibility | Tests fail if event detail creates folios or changes SLA snapshot/fallback response fields. | Existing `test_event_service_smoke.py` / `test_routers_metrics_events.py` SLA cases still pass plus one no-folio-regression test. |
| Frontend hooks | Tests fail until ITSM hooks call `/itsm/service-catalog` and `/itsm/tickets` through `api`. | Vitest hook tests pass with mocked `api` and QueryClient. |
| Frontend pages | Tests fail until pages render separate ITSM labels, CRUD forms, validation errors, and next-only status transition actions. | Testing Library tests pass for Service Catalog page, Ticket/Folio page, and `TicketStatusStepper`. |

Recommended commands once implementation exists:

```bash
cd backend && pytest backend/tests/test_itsm_service_catalog_service.py backend/tests/test_ticket_folio_service.py
cd backend && pytest backend/tests/test_routers_itsm.py backend/tests/test_event_service_smoke.py
cd frontend && pnpm test:run frontend/components/itsm frontend/hooks/queries
```

Adjust exact paths to match the repository’s test invocation conventions if the test runner expects execution from inside each package.

## Implementation slicing recommendation

This scope is likely to exceed the 400-line review budget if implemented as one PR. Recommended chained slices:

1. **Backend domain foundation**: schemas, repositories, services, state machine, Neo4j constraints/backfill helper, unit tests. No frontend.
2. **Backend API surface**: routers, auth checks, main router registration, router tests, event compatibility regression tests.
3. **Frontend ITSM Service Catalog**: types, service client, query hooks, Service Catalog page, route/nav, tests.
4. **Frontend Ticket/Folio workflow**: ticket hooks, page, status stepper, transition UX, tests.

If the team insists on a single PR, record a review-budget exception before apply and keep commits grouped by the same boundaries.

## Rollout and rollback

- Roll out additively: constraints/indexes first, backend APIs second, frontend routes last.
- Keep new routes isolated under `/api/itsm/*` and `/itsm/*` so disabling the UI does not affect monitoring/event flows.
- Rollback frontend by removing the ITSM nav/routes.
- Rollback backend APIs by unregistering routers while leaving additive Neo4j properties/constraints in place.
- Never roll back by deleting or rewriting existing event SLA snapshot data.

## Open questions before apply

- Should dedicated permissions (`ITSM_VIEW`, `ITSM_EDIT`, `ITSM_DELETE`) be introduced now, or should first slice explicitly use `ADMIN`/existing permissions and defer a permission migration?
- Does CRUD require hard delete for Ticket/Folio, or is archive/close sufficient for auditability?
