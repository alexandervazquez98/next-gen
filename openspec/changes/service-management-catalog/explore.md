# Explore Service Management Catalog

The current ITSM implementation already has a ticket folio and service catalog. This change extends those surfaces rather than creating a second catalog.

## Existing implementation

| Area | Current state | Change implication |
|---|---|---|
| Ticket API | `backend/routers/ticket_folios.py` exposes `/itsm/tickets`; create receives `TicketFolioCreate`. | Remove client-supplied ticket ID and generate the identifier server-side. |
| Ticket client model | `frontend/types/itsm.ts` requires `ticket_id` in `TicketFolioCreatePayload`. | Remove the input/payload field and display the returned generated identifier. |
| Service catalog | `frontend/components/ItsmServiceCatalogPage.tsx` manages `service_id`, name, owner, category, tier, criticality, SLA, and active state. | Add description, exclusive ticket type, and controlled value stream. Preserve service ID as the business-unique catalog key. |
| Ticket-to-service relation | Tickets already store nullable `service_catalog_id`. | Filter selectable services by the selected exclusive ticket type and reject incompatible relations in the backend. |
| Catalog repository | `backend/repositories/itsm_service_catalog_repo.py` is called by catalog and ticket-folio services. | Extend persistence and service validation; add direct coverage because CodeGraph found no covering tests. |
| CI bulk import reference | Administration downloads `/nodes/template`; `backend/routers/nodes.py` delegates upload to `services.node_service.bulk_upload_nodes`; tests are in `backend/tests/test_node_service.py` and `backend/tests/test_routers_nodes.py`. | Reuse the download-template + file-upload + row validation/error aggregation pattern for catalog import. |

## Product decisions captured

| Decision | Rule |
|---|---|
| Module name | Use **Service Management** in English. |
| Ticket identifier | Generated automatically, unique, and suitable as the primary key for future ticket correlations. |
| Catalog scope | A catalog record is exclusively either `incident` or `service_request`. |
| Duplicate names | Allowed across scopes when they represent different value flows; `service_id` remains unique. |
| Value stream | Required controlled value selected from an administrable list. |
| Bulk import | Provide a downloadable template and import workflow based on the existing CI bulk-import experience. |

## Risks and open product decisions

- The exact generated ticket identifier representation remains to be decided: numeric database primary key only, or a human-readable prefixed folio backed by a numeric primary key.
- The controlled source and lifecycle for value streams must be specified: seed list only or dedicated administration management.
- Import behavior must define whether the entire file is atomic or valid rows are imported while invalid rows are reported. The CI reference should be inspected during design before choosing.

## Likely verification areas

- Backend request/model/repository/service tests for generated IDs, uniqueness, service-type compatibility, and import validation.
- Frontend component tests for no editable ticket-ID field, type-filtered service dropdown, new catalog fields, template download, row-error display, and successful import.
