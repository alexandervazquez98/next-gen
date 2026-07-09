# Exploration: ITSM Service Catalog

## Issue / Intent

Issue #14 requests a `ServiceCatalog` entity in Neo4j to enable `SLA Restante` in the event modal. The maintainer comment correctly reframes it: this should not be solved as an isolated node/field. The product needs a dedicated ITSM Service Catalog / Service Management foundation where operational services are registered, associated to categories, tier/criticality, and configured with operational SLA values consumed by event response flows.

Initial target concepts from the user:

- Service catalog for all business/system services.
- Ticket/folio types: `request` and `incident`.
- Later integration with "respuesta al evento", where events receive folios based on administrator-defined configurations.
- CRUD for tickets/folios independent of events.

## Current State

### Existing Event and SLA Context

- Domain models already include `BusinessService`, `ServiceCatalog`, `BusinessContext`, `ItsmContext`, and `ExternalTicketRef` in `backend/models/core.py`.
- Event detail resolution in `backend/services/event_service.py` uses event snapshot data first, then can resolve/fallback through `BusinessService -> ServiceCatalog` when needed.
- Event responses expose SLA context such as service catalog/category/SLA and `sla_remaining_minutes`.
- Frontend types and monitoring UI already consume the business context for event detail display.

### Existing Catalog Meaning

- Current admin/catalog surfaces are inventory/CI-oriented: categories, hardware, owners.
- These are not an ITSM Service Catalog management module.
- Naming collision risk is high if the new module is called only "Catalog" in routes/UI.

### Ticket / Folio State

- A first-class ticket/folio lifecycle was not found.
- Existing external ticket support appears passive: event-level external ticket references can be returned, but there is no dedicated writer, workflow, assignment, or CRUD surface for ITSM folios.

## Issue #14 Assessment

Issue #14 is valid but too narrow as the implementation unit.

Partially covered already:

- Event SLA context and modal contract have foundation pieces.
- Snapshot/fallback behavior exists for event details.

Still missing:

- Dedicated Service Catalog CRUD/admin module.
- Clear source of truth for service categories, tiers, criticality, and SLA policies.
- Ticket/folio domain for request and incident lifecycle.
- Event-response configuration that decides when and how to create/assign a folio.

Recommendation: keep #14 as the tactical event-SLA issue, but create/use a parent change for the broader ITSM Service Catalog foundation.

## Recommended First Slice

First slice should focus on the catalog foundation, not the whole ITSM workflow.

Include:

1. Dedicated Service Catalog domain/API/admin UI for managing business/system services and operational SLA metadata.
2. Clear separation from the existing hardware/inventory catalog.
3. Compatibility with existing event SLA snapshot/fallback behavior.
4. Tests around catalog CRUD and event detail compatibility.

Defer:

- Full ticket/folio lifecycle.
- Automatic folio assignment from events.
- External ITSM sync with tools like Jira/ServiceNow.
- SLA recalculation for historical events unless explicitly required.

## Initial Domain Vocabulary

- `ServiceCatalog`: existing graph/domain concept, source of operational SLA metadata.
- `BusinessService`: business-facing service related to CIs and SLA catalog entries.
- `ServiceOffering` or `Service`: candidate naming for admin-managed service records; must be decided before implementation.
- `SlaPolicy`: candidate abstraction if SLA becomes more complex than `sla_minutes`.
- `Ticket` / `Folio`: future workflow entity.
- `Request`: service request ticket type.
- `Incident`: incident ticket type.
- `EventResponseConfiguration`: future admin configuration deciding folio creation/assignment from events.

## Key Risks

- Naming collision between inventory catalog and ITSM Service Catalog.
- Scope creep: tickets, incidents, event automation, and external sync can quickly exceed the 400-line review budget.
- Permission model may need new ITSM permissions instead of reusing broad CI edit/delete permissions.
- Historical event snapshots should not silently change if Service Catalog configuration changes later.
- Existing issue #14 may be closed incorrectly if only a graph node is added without admin/product flow.

## Open Product Questions for Proposal

1. Is the first release only Service Catalog administration, or must it include ticket/folio CRUD too?
2. Should the user-facing term be "Service Catalog", "Service Management", or "ITSM" in navigation?
3. Are `request` and `incident` enough as initial folio types, or do we also need states/priorities/assignment from day one?
4. Should event-created folios be immutable historical records, or can admin rule changes update them retroactively?
5. Should SLA remain a single `sla_minutes` field initially, or do we need tier/priority calendars and working-hours policies?

## Next Recommended Phase

Proceed to proposal for `itsm-service-catalog`, using this exploration as the scope guard.
