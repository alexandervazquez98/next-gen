# Proposal: ITSM Service Catalog Foundation + Ticket/Folio CRUD

Status: Draft  
Change ID: `itsm-service-catalog`

## Executive Summary
Implement a first-slice ITSM foundation that adds:
1) dedicated Service Catalog CRUD for operational service definitions and SLA metadata, and 2) independent Ticket/Folio CRUD with an initial `request`/`incident` lifecycle. The first delivery intentionally excludes automatic event-to-folio association; that will be implemented later as a controlled extension point.

## Problem and business outcome
**Problem:** The current codebase has fragments (service metadata references, event SLA snapshots, external ticket references) but no coherent ITSM product surface for teams to define services and manage request/incident folios. This creates fragmented behavior, unclear ownership of SLAs, and inconsistent service operations.

**Business outcome:** Define a clear operational domain that teams can use immediately to:
- register/manage services and SLA expectations centrally,
- create and track request/incident folios independently,
- keep event-response paths untouched and simple while preparing for future automation.

## Proposal question round (assumptions captured)
Based on your provided decisions:
1. First slice MUST include both **Service Catalog CRUD** and **Ticket/Folio CRUD**.
2. Ticket/Folio CRUD is **independent of events** in this delivery.
3. Event-response association is a **future extension**.
4. Initial ticket/folio types are only `request` and `incident`.
5. Workflow is linear and includes `in_validation`.
6. Recommended linear lifecycle is: `open -> in_progress -> in_validation -> resolved -> closed`.

If any assumption should change, or if you want a second question round, say so before moving to spec.

## Scope (first slice)
### In scope
- Service Catalog domain CRUD and admin-facing management flow.
- Ticket/Folio domain CRUD and linear lifecycle transitions (initial types: `request`, `incident`).
- API and data model groundwork that keeps ticket/folio and catalog independent.
- Boundary/interface design for future event-response association.
- Minimal tests around lifecycle, CRUD boundaries, and validation rules.

### Out of scope (non-goals)
- Automatic event-to-folio association from event-response workflows.
- Event routing/reassignment from catalog/business rules for initial delivery.
- External ITSM connector workflows (e.g., Jira/ServiceNow sync).
- SLA recalculation retroactively mutating already-created event artifacts.
- Advanced ITSM policies (priorities/escalation matrices/SLAs by priority calendars) beyond first-slice metadata.

## Proposed domain boundaries
1. **Service Catalog**
   - Canonical operational service registry used by operations workflows.
   - Separate name/meaning from existing inventory/catalog concepts.
   - Own fields: identification, owner/context references, category/tier/criticality, base SLA configuration, active/disabled state.

2. **Ticket/Folio**
   - Dedicated ITSM entities with types `request` and `incident`.
   - Independent lifecycle and CRUD in this slice.
   - Status lifecycle is linear and must include: `open` → `in_progress` → `in_validation` → `resolved` → `closed`.

3. **Future Event Response association**
   - No functional association in first slice.
   - Keep explicit extension points (service reference and lifecycle compatibility) so event workflows can create/attach folios in later iterations without major migration.

## Minimal data/behavior expectations
- **Service Catalog** should include required identity and SLA fields with deterministic defaults and validation.
- **Ticket/Folio** should enforce valid type + status transitions in linear order only.
- **Separation of concerns:** catalog management and folio operations must not be coupled in a way that prevents running either feature independently.
- **Auditability:** create/update timestamps and user attribution are expected for both domains.
- **Permissions:** use existing admin-level authorization model unless a dedicated ITSM permission needs to be introduced as a follow-up.

## Affected areas (expected)
- Backend domain/API work for Service Catalog and Ticket/Folio persistence and endpoints.
- Frontend admin and operational UI surfaces for both CRUD areas.
- Shared models/schemas, validations, and tests.
- Initial routing/navigation labels/sections to avoid inventory catalog confusion.

## Proposed design direction
- Introduce/solidify Service Catalog as its own bounded domain with explicit naming in API and UI.
- Implement Ticket/Folio lifecycle with explicit status enum and linear state validation.
- Keep event-response code unchanged for now; introduce clean hooks/interfaces for later association.
- Keep models and services additive to avoid breaking existing event SLA snapshot behavior.

## Acceptance criteria
1. Service Catalog can be created, read, updated, and deactivated via API/admin flow.
2. Ticket/Folio can be created, read, updated, and closed via API/admin flow.
3. Ticket/Folio supports exactly initial `request` and `incident` types.
4. Ticket/Folio status transitions only allow linear progression through: `open` → `in_progress` → `in_validation` → `resolved` → `closed`.
5. No event-to-folio association behavior is introduced in this slice.
6. Existing issue/feature behaviors around event SLA snapshots remain stable.
7. Existing users can distinguish Service Catalog (ITSM) from inventory catalog areas.

## Risks
1. **Naming collision risk:** confusion between new ITSM catalog and existing inventory catalog; require explicit module naming and route labels.
2. **Scope creep:** adding full ITSM parity too early can exceed delivery intent and review budget.
3. **Permission misalignment:** existing roles may not map cleanly to new domains.
4. **Workflow migration risk:** adding status values later could require backward-compatible transition strategy.

## Rollback plan
- Feature-flag where practical and keep domain changes additive.
- If needed, disable/remove new catalog/folio modules independently without impacting existing event/SLA logic.
- Revert API/controller surfaces if behavior coupling breaks existing flows.

## Review workload note
This is likely to cross the **400 changed lines** threshold (especially if both domains plus frontend screens are included). Plan for slicing (recommended: separate PRs or batches) based on `delivery_strategy` and review capacity.

## Success criteria
- Service Catalog and Ticket/Folio first-slice capabilities are usable end-to-end by operators.
- Ticket/Folio lifecycle is strictly linear with `in_validation` in sequence.
- No regressions in existing event SLA retrieval/usage.
- Future event association can be implemented without breaking current ticket/folio and catalog data contracts.

## Next recommended phase
Proceed to **spec**.
