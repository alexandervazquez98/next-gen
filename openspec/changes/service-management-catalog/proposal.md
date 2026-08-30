# Proposal: Service Management Catalog and Ticketing Evolution

Change ID: `service-management-catalog`
Status: Draft

## Executive Summary
Bring the product into a clean-slate **Service Management** domain by renaming the Tickets module, adopting server-generated numeric ticket IDs, and launching governed catalog/ticket data models with deterministic XLSX bulk workflows. The implementation assumes no existing deployed/active tickets or services, so no migration, backfill, or historical-compatibility work is required.

## Confirmed product decisions

| Topic | Decision |
|---|---|
| Environment assumption | No active/deployed tickets or services exist at rollout time (clean-slate implementation). |
| Ticket ID | The user-visible `ticket_id` is the numeric auto-increment primary key, with no prefix and no customer-provided IDs. |
| Assignee model | Exact one assignee per new/bulk ticket. Only active users are eligible. |
| User lifecycle | Users with history are deactivated instead of deleted; historical assignments remain visible. |
| Catalog typing | Service records are immutable and explicitly `incident` or `service_request`. |
| Value stream governance | Required value streams come from managed dictionary/list values and include active/inactive state. |
| Import transaction behavior | Catalog and ticket XLSX imports are atomic: any validation error rejects the full upload. |
| Service scope | A service belongs exclusively to Incident or Service Request. Duplicate names are allowed across scopes when IDs differ. |

## Scope

### In scope (first slice)
- Rename user-facing Tickets module to **Service Management**.
- Change ticket creation behavior so IDs are always generated server-side.
- Add/ evolve catalog records with:
  - unique service ID,
  - service name (duplicate names allowed only across different ticket types),
  - SLA,
  - description,
  - required controlled value stream,
  - immutable ticket type (`incident` or `service_request`).
- Enforce service-to-ticket type compatibility in UI and backend.
- Add XLSX bulk catalog import with:
  - downloadable template,
  - per-row/field validation reporting,
  - atomic all-or-nothing persistence.
- Add XLSX bulk ticket creation with:
  - dedicated template and reference worksheet of valid services by ticket type,
  - same type-compatibility rules,
  - exactly one assignee per ticket.
- Reuse CI bulk-import interaction/validation patterns where they fit (template download, upload flow, validation-report UX).

### Out of scope
- Multiple assignees, groups, and history/audit expansion.
- Bulk update/delete workflows.
- CSV import support.
- Additional ticket types beyond `incident` and `service_request` in this slice.
- Legacy-ID compatibility, historical-ticket/service migration or backfill, and compatibility/rollback for historic records.
- Maintenance-window-specific rollout constraints.

## Affected areas
- **Backend APIs**: ticket create payload/schema, ticket-to-service validation, catalog service and repository rules.
- **Frontend UX**: Service Management naming, catalog management UI, ticket create flows, assignee selector, XLSX template download/preview, and bulk upload flow.
- **Data model/schemas**: catalog and ticket PK/id strategy, service type constraints, controlled value stream references, and assignment fields.
- **Validation and tests**: row-level and entity-level validation for both bulk flows and compatibility constraints, plus import atomicity behavior.

## Business rules and product outcome
- Service records are immutable by type: either Incident or Service Request.
- Ticket/service type compatibility is mandatory and validated in both UI and backend.
- Name collisions are allowed only across scopes; `service_id` remains unique within scope.
- Value stream is required and must come from a controlled dictionary value.
- Clean-slate imports are deterministic and explainable: either fully committed or fully rejected.

## Risks
1. **Import adoption risk**: XLSX parsing can hide edge cases around date/number formats, hidden rows, and large files.
2. **Governance risk**: controlled value stream validation can block submissions until dictionary values are aligned.
3. **Compatibility drift risk**: catalog and ticket validation diverging if constraints are implemented unevenly across UI and backend.

## Rollback plan
- Roll back by disabling the new Service Management module features and restoring the prior tickets flow.
- For minimal blast radius, deactivate bulk-import endpoints and ticket-type compatibility enforcement before re-enabling the previous behavior.
- Keep user-visible behavior and data expectations unchanged for non-migrated flows during rollback.

## Success criteria
- Users can create tickets without entering IDs and receive a generated numeric ticket ID.
- Service catalog enforces immutable service type, all required fields, dictionary-driven value stream, and unique service IDs.
- Ticket creation and bulk ticket creation only allow compatible catalog services.
- XLSX catalog and ticket imports offer template access, row/field validation, and atomic all-or-nothing persistence.
- Bulk ticket creation is guided by reference-sheet service lists and enforces exactly one active assignee.
- Existing CI bulk-import validation UX patterns are reused where appropriate.

## Next recommended phase
Proceed to **spec**.
