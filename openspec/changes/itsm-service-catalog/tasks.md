# Tasks: ITSM Service Catalog + Ticket/Folio CRUD

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~640-900 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 foundation/domain contracts; PR 2 backend API/services/repositories; PR 3 frontend service-catalog module; PR 4 frontend ticket/folio module |
| Delivery strategy | single-pr size exception accepted by user |
| Chain strategy | not applicable — single oversized PR accepted |

Decision needed before apply: No — user accepted single oversized PR
Chained PRs recommended: Yes, but overridden by accepted size exception
Chain strategy: not applicable
400-line budget risk: High — accepted by user

> Forecast rationale: cross-domain backend migration/bootstrap + 4 backend routers/repos/services + 2 UI modules and route wiring will likely exceed 400 lines and couples two domains plus extension-point safeguards.

## TDD ordering (strict TDD)
- Backend behavior changes: **RED → GREEN → TRIANGULATE → REFACTOR** per work unit.
- Backend tests must be added/updated before implementation in the same work unit.
- Frontend behavior changes: **frontend tests first**, then component/service implementation in the same work unit.

## Global in-slice constraints (must remain true)
1. No event-to-folio auto-association in this slice.
2. Service catalog stays separate from inventory catalog/domain routes and UI.
3. Ticket/Folio delete semantics are LOGICAL (archive/close-oriented) only unless a follow-up explicit hard-delete task is approved.
4. ITSM read/write endpoints must have explicit permission gates.
5. `service_catalog_id` reference for Ticket/Folio is the authoritative identifier; any `FOR_SERVICE` relationship is kept in sync and is non-authoritative.
6. Migration/bootstrap MUST preflight existing `ServiceCatalog` data (duplicates/invalid legacy IDs) before enabling uniqueness constraints.

## Suggested work units and verification boundaries

### Work Unit 1 — Backend domain contracts + migration preflight (PR 1)
Dependencies: proposal + design only.
Finish state: domain entities, migration script, and startup preflight are in place and test-covered.

- **RED**
  - [x] 1.1 Add `backend/tests/test_itsm_domain_contracts.py` covering:
    - `ServiceCatalog` alias compatibility (`id`/`service_id`, `service_tier`/`tier`, `sla_minutes`/`sla_target_minutes`) and non-negative SLA validation.
    - Ticket/Folio type enum (`request`, `incident`) and required linear lifecycle order.
    - no hard-delete behavior expectation for ticket updates (`archived`/`closed` path only; physical delete absent).
  - [x] 1.2 Add `backend/tests/test_migration_itsm_catalog.py` asserting `backend/migrations/itsm_service_catalog.cypher` contains:
    - `service_catalog_service_id` unique constraint with `IF NOT EXISTS`,
    - ticket folio constraint/indexes,
    - additive/compatibility comments for legacy data.

- **GREEN**
  - [x] 1.3 Create `backend/models/itsm.py` with Pydantic payload/response models:
    - service catalog fields (`service_id`, `name`, `owner_team`, `category`, `tier`, `criticality`, `sla_target_minutes`, `active`, timestamps, `updated_by`, optional compatibility fields as needed),
    - ticket/folio fields (`ticket_id`, `type`, `title`, `description`, `service_catalog_id`, `status`, `archived`, `closed_reason`, `created_at`, `updated_at`, `updated_by`).
  - [x] 1.4 Add `backend/repositories/itsm_service_catalog_repo.py` with additive Neo4j write/read queries:
    - list/get by `service_id`,
    - create/update with deterministic defaults and optional compatibility aliases,
    - logical deactivate (`active=false`).
  - [x] 1.5 Add `backend/repositories/ticket_folio_repo.py` with query patterns for ticket CRUD and status-based list filtering.
  - [x] 1.6 Add `backend/services/itsm_bootstrap.py` with preflight:
    - detect duplicate/collision risks in candidate `(service_id/id)` keys,
    - detect invalid legacy `ServiceCatalog` nodes lacking resolvable canonical identity,
    - emit startup-failing exception if preflight blockers exist.
  - [x] 1.7 Add `backend/migrations/itsm_service_catalog.cypher` with:
    - `ServiceCatalog`/`TicketFolio` constraints/indexes,
    - a safe backfill block mapping legacy `id/service_tier/sla_minutes` into new fields when present,
    - explicit additive behavior comments (no event snapshot mutation).
  - [x] 1.8 Register startup preflight in `backend/main.py` startup path (before Neo4j writes for catalog constraints).

- **TRIANGULATE**
  - [x] 1.9 Verify migration/application ordering against existing startup flow (`backend/main.py` startup path) and confirm no change to event snapshot usage (`main.startup_event`) and confirm no change to event snapshot usage paths.
  - [x] 1.10 Reconcile whether `service_catalog_id` conflicts are resolved pre-migration or blocked with startup error (document chosen behavior in task notes).

- **REFACTOR**
  - [x] 1.11 Clean naming/docs in `backend/models/itsm.py` and migration file comments; keep backward-compatible aliases explicit.

### Work Unit 2 — Backend API services + routers + permissions + event compatibility (PR 2)
Dependencies: Work Unit 1 complete.
Finish state: all backend endpoints are implemented and validated; event compatibility is proven unchanged.

- **RED**
  - [x] 2.1 Add `backend/tests/test_itsm_service_catalog_service.py`:
    - create/list/update/deactivate catalog semantics,
    - validation failures (empty name, negative SLA,
      partial write safety).
  - [x] 2.2 Add `backend/tests/test_ticket_folio_service.py`:
    - create defaults (`open`),
    - transition validator rejects skip/rollback,
    - close transition preserves history and requires closed state handling.
  - [x] 2.3 Add `backend/tests/test_routers_itsm.py` for ITSM auth + route behavior:
    - catalog/ticket reads require read permission,
    - writes require explicit write permission,
    - CRUD endpoints return expected models.
  - [x] 2.4 Add/extend event compatibility tests in `backend/tests/test_event_service_smoke.py` or `backend/tests/test_routers_events.py` to assert no event-path creates/updates/deletes folios and existing snapshot/fallback reads remain unchanged.

- **GREEN**
  - [x] 2.5 Create `backend/services/itsm_service_catalog_service.py`:
    - catalog defaults + validation + compatibility sync,
    - no hard-delete semantics (logical deactivate only).
  - [x] 2.6 Create `backend/services/ticket_folio_service.py`:
    - enforce pure state machine `open -> in_progress -> in_validation -> resolved -> closed`,
    - define authoritative `service_catalog_id` contract and synchronize optional `FOR_SERVICE` relationship.
  - [x] 2.7 Add `backend/routers/itsm_service_catalog.py` with explicit permission checks:
    - list/get/create/update/deactivate routes under `/api/itsm/service-catalog`.
  - [x] 2.8 Add `backend/routers/ticket_folios.py` with explicit permission checks:
    - list/get/create/update/transition under `/api/itsm/tickets`.
    - if delete is present, document `archived=true` only and route name accordingly.
  - [x] 2.9 Register routers in `backend/main.py` with `/api` prefix and ensure naming/tag isolation from inventory routes.
  - [x] 2.10 Add/update `backend/models/core.py` if needed for backward-compatible `BusinessContextCatalog` alias exposure only (no breaking rename).

- **TRIANGULATE**
  - [x] 2.11 Run endpoint permission audit against `routers/catalog.py` and `routers/events.py` to prevent overlap/ambiguity with inventory permission model.
  - [x] 2.12 Validate service-catalog/ticket reference behavior:
    - service relation and property both accepted on writes,
    - repository writes keep property/relationship in sync,
    - reads remain deterministic when relation missing but property present.

- **REFACTOR**
  - [x] 2.13 Refactor router/service wiring for pure transition function and explicit error messages (400/409 vs 404 semantics).
  - [x] 2.14 Add short API contract note in code docstring for both routers: explicit separation from event flows.

### Work Unit 3 — Frontend ITSM catalog surface + routes/navigation isolation (PR 3)
Dependencies: Work Unit 2 completed enough for mocked service wiring.
Finish state: users can manage Service Catalog in a dedicated ITSM route (not inside inventory UI).

- **RED**
  - [x] 3.1 Add `frontend/components/__tests__/ItsmServiceCatalogPage.test.tsx`:
    - reads and renders `/itsm/service-catalog` route,
    - list/create/edit/deactivate behavior,
    - read/write API calls hit `/api/itsm/service-catalog`.
  - [x] 3.2 Add `frontend/services/__tests__/itsm_api.test.ts` (or inline vitest mock test file in same folder convention): API client method tests for catalog endpoints.

- **GREEN**
  - [x] 3.3 Add `frontend/types/itsm.ts` with TicketFolio and ServiceCatalog response/input types.
  - [x] 3.4 Add `frontend/services/itsm.ts` client wrapper functions:
    - `listServiceCatalog`, `createServiceCatalog`, `updateServiceCatalog`, `deactivateServiceCatalog`.
  - [x] 3.5 Add `frontend/components/ItsmServiceCatalogPage.tsx` and optional `frontend/components/ItsmServiceCatalogForm.tsx` for CRUD flow.
  - [x] 3.6 Add dedicated ITSM navigation in `frontend/App.tsx`:
    - new route `/itsm/service-catalog`,
    - sidebar item under ITSM.
  - [x] 3.7 Ensure no shared navigation path with inventory catalog tabs (keep Inventory/Hardware catalogs untouched).

- **TRIANGULATE**
  - [x] 3.8 Verify route isolation by end-to-end route test + manual smoke plan:
    - `/inventory` behavior unchanged,
    - ITSM screens visible only under `/itsm/*`.

- **REFACTOR**
  - [x] 3.9 Refactor shared query/loading/error UI patterns for catalog page; keep labels concise and user-facing English.

### Work Unit 4 — Frontend ticket/folio UX + lifecycle controls (PR 4)
Dependencies: Work Units 1–3 complete (backend APIs and auth contract stable).
Finish state: operators can manage request/incident folios and enforce linear transitions from UI.

- **RED**
  - [x] 4.1 Add `frontend/components/__tests__/TicketFolioPage.test.tsx` and `frontend/components/__tests__/TicketStatusStepper.test.tsx`:
    - list/filter by type/status,
    - create/update/transition controls only allow next-step transitions,
    - closed items are read-only,
    - endpoint calls go through `/api/itsm/tickets` and `/api/itsm/tickets/{id}/transition`.

- **GREEN**
  - [x] 4.2 Add/extend `frontend/services/itsm.ts` for ticket endpoints and transition calls.
  - [x] 4.3 Add `frontend/components/ItsmTicketFolioPage.tsx` and `frontend/components/TicketStatusStepper.tsx`.
  - [x] 4.4 Update `frontend/App.tsx` with `/itsm/tickets` route and ITSM nav entry (if not already covered in Work Unit 3).

- **TRIANGULATE**
  - [x] 4.5 Add contract sanity test for API client + component using `api` mock to ensure no event endpoints are called by Ticket/Folio UI.

- **REFACTOR**
  - [x] 4.6 Rename/add UI strings and action labels so ITSM is distinguishable from catalog/inventory wording.

## Acceptance / completion checklist before apply
- [x] All work units in PR 1 and PR 2 pass backend tests (unit + router + migration contract).
- [x] PR 3 and PR 4 include frontend tests for the changed screens.
- [x] Event path behavior remains unchanged (existing event tests still pass).
- [x] Navigation/UI separation from inventory/catalog routes is demonstrable by route checks.
- [x] Deletion policy for Ticket/Folio is documented in code/test assertions as logical/archival-first.
- [x] Migration preflight behavior for legacy/duplicate catalog IDs is implemented and documented.
- [x] Rollback playbook: remove ITSM routers from `backend/main.py` + remove `/itsm/*` routes from `frontend/App.tsx` without touching event or inventory modules.
