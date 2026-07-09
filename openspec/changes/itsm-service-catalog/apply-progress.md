# Apply Progress — ITSM Service Catalog + Ticket/Folio

## Apply Progress — Work Unit 1

## Status
- change: `itsm-service-catalog`
- unit: `Work Unit 1 — Backend domain contracts + migration preflight`
- executed: with strict TDD (RED → GREEN → TRIANGULATE → REFACTOR)

## Files changed
- Added
  - `backend/tests/test_itsm_domain_contracts.py`
  - `backend/tests/test_migration_itsm_catalog.py`
  - `backend/models/itsm.py`
  - `backend/repositories/itsm_service_catalog_repo.py`
  - `backend/repositories/ticket_folio_repo.py`
  - `backend/services/itsm_bootstrap.py`
  - `backend/migrations/itsm_service_catalog.cypher`
  - `backend/tests/test_itsm_startup_checks.py`
- Updated
  - `backend/main.py` (startup bootstrap checks and migration application call)
  - `openspec/changes/itsm-service-catalog/tasks.md` (completed Work Unit 1 checkbox items)

## Completed Work Unit 1 tasks
- [x] 1.1 Add alias/domain contracts tests
- [x] 1.2 Add migration contract tests
- [x] 1.3 Create `backend/models/itsm.py`
- [x] 1.4 Add `backend/repositories/itsm_service_catalog_repo.py`
- [x] 1.5 Add `backend/repositories/ticket_folio_repo.py`
- [x] 1.6 Add startup bootstrap preflight service
- [x] 1.7 Add migration for constraints/indexes/compatibility
- [x] 1.8 Register bootstrap in `backend/main.py`
- [x] 1.9 Validate ordering and event-flow unchanged
- [x] 1.10 Define startup fail-fast policy
- [x] 1.11 Clean naming/docs in models/migration

## TDD Cycle Evidence (WU1)
- RED: added domain contract and migration migration tests
- GREEN: implemented models/repos/bootstrap/migration wiring
- TRIANGULATE: startup/order and event-path checks
- REFACTOR: docs and contract cleanup

## Verification commands run (WU1)
- `cd backend && python3 -m compileall backend/models/itsm.py ...` — PASS
- `cd backend && python3 -m pytest backend/tests/test_itsm_domain_contracts.py backend/tests/test_migration_itsm_catalog.py` — PASS
- `cd backend && python3 -m pytest backend/tests/test_itsm_startup_checks.py` — PASS

---

## Apply Progress — Work Unit 2

## Status
- change: `itsm-service-catalog`
- unit: `Work Unit 2 — Backend API services + routers + permissions + event compatibility`
- executed: with strict TDD (RED → GREEN → TRIANGULATE → REFACTOR)

## Files changed
- Added
  - `backend/tests/test_itsm_service_catalog_service.py`
  - `backend/tests/test_ticket_folio_service.py`
  - `backend/tests/test_routers_itsm.py`
  - `backend/routers/itsm_service_catalog.py`
  - `backend/routers/ticket_folios.py`
  - `backend/services/itsm_service_catalog_service.py`
  - `backend/services/ticket_folio_service.py`
- Updated
  - `backend/tests/test_event_service_smoke.py`
  - `backend/models/user.py`
  - `backend/models/itsm.py`
  - `backend/repositories/ticket_folio_repo.py`
  - `backend/main.py`

## Completed Work Unit 2 tasks
- [x] 2.1 Add `backend/tests/test_itsm_service_catalog_service.py`
- [x] 2.2 Add `backend/tests/test_ticket_folio_service.py`
- [x] 2.3 Add `backend/tests/test_routers_itsm.py`
- [x] 2.4 Add/extend event compatibility tests in `backend/tests/test_event_service_smoke.py`
- [x] 2.5 Create `backend/services/itsm_service_catalog_service.py`
- [x] 2.6 Create `backend/services/ticket_folio_service.py`
- [x] 2.7 Add `backend/routers/itsm_service_catalog.py`
- [x] 2.8 Add `backend/routers/ticket_folios.py`
- [x] 2.9 Register routers in `backend/main.py`
- [x] 2.10 `backend/models/core.py` unchanged (not required for this backend slice)
- [x] 2.11 Run endpoint permission audit against `routers/catalog.py` and `routers/events.py`
- [x] 2.12 Validate service-catalog/ticket reference behavior (property + relationship sync)
- [x] 2.13 Refactor for explicit 400/409 vs 404 error semantics
- [x] 2.14 Add router docstring contract note for explicit event-flow separation

## TDD Cycle Evidence (WU2)

| Task(s) | RED (test-first) | GREEN (implementation) | TRIANGULATE | REFACTOR |
|---|---|---|---|---|
| WU2 backend services + routers + permission gates | Added tests for service validation, transitions, router permission enforcement, and event compatibility before implementation | Implemented service/route layers, added ITSM permission enums, router registration, and repository relationship-sync support | Added compatibility event test to verify no event-to-folio write/mutation references in event detail path | Kept logic tight; no further refactor in this cycle |

## Verification commands run
- `cd backend && python3 -m py_compile models/user.py models/itsm.py repositories/ticket_folio_repo.py services/itsm_service_catalog_service.py services/ticket_folio_service.py routers/itsm_service_catalog.py routers/ticket_folios.py tests/test_itsm_service_catalog_service.py tests/test_ticket_folio_service.py tests/test_routers_itsm.py tests/test_event_service_smoke.py main.py`
  - Result: PASS
- `cd backend && /tmp/next-gen-it-sm-venv/bin/python -m pytest tests/test_itsm_domain_contracts.py tests/test_migration_itsm_catalog.py tests/test_itsm_startup_checks.py tests/test_itsm_service_catalog_service.py tests/test_ticket_folio_service.py tests/test_routers_itsm.py tests/test_event_service_smoke.py -q`
  - Result: PASS (97 passed, 0 warnings)

## Remaining backend risks
- None for WU2 focused backend scope.

## Workload / PR boundary
- Review workload forecast remains high.
- Delivery PR boundary this batch: **PR 2**.

---

## Apply Progress — Work Unit 3

## Status
- change: `itsm-service-catalog`
- unit: `Work Unit 3 — Frontend ITSM catalog surface + routes/navigation isolation`
- executed: with strict TDD (RED → GREEN → TRIANGULATE → REFACTOR)

## Files changed
- Added
  - `frontend/types/itsm.ts`
  - `frontend/services/itsm.ts`
  - `frontend/services/__tests__/itsm_api.test.ts`
  - `frontend/components/ItsmServiceCatalogPage.tsx`
  - `frontend/components/__tests__/ItsmServiceCatalogPage.test.tsx`
  - `frontend/App.itsm-route.test.tsx`
- Updated
  - `frontend/App.tsx`
  - `openspec/changes/itsm-service-catalog/tasks.md`

## Completed Work Unit 3 tasks
- [x] 3.1 Add Service Catalog page tests
- [x] 3.2 Add ITSM API wrapper tests
- [x] 3.3 Add frontend ITSM types
- [x] 3.4 Add Service Catalog API client functions
- [x] 3.5 Add Service Catalog page/form flow
- [x] 3.6 Add dedicated `/itsm/service-catalog` route/navigation
- [x] 3.7 Keep inventory catalog navigation untouched
- [x] 3.8 Verify route isolation with routing test
- [x] 3.9 Refactor loading/error UI and English labels

## TDD Cycle Evidence (WU3)
- RED: frontend route/page/API tests were added before passing implementation.
- GREEN: Service Catalog types, API client, page, and route/navigation were implemented.
- TRIANGULATE: route isolation test verifies `/itsm/service-catalog` and existing `/inventory` remain separate.
- REFACTOR: App route test was corrected to use `HashRouter` behavior directly and not nest routers.

## Verification commands run
- `cd frontend && corepack pnpm install --frozen-lockfile`
  - Result: PASS (installed missing dependency links, including `sonner`, from existing lockfile)
- `cd frontend && corepack pnpm exec vitest run App.itsm-route.test.tsx components/__tests__/ItsmServiceCatalogPage.test.tsx services/__tests__/itsm_api.test.ts`
  - Result: PASS (3 files, 10 tests)

## Remaining frontend WU3 risks
- None for focused WU3 scope.

---

## Apply Progress — Work Unit 4

## Status
- change: `itsm-service-catalog`
- unit: `Work Unit 4 — Frontend ticket/folio UX + lifecycle controls`
- executed: with strict TDD (RED → GREEN → TRIANGULATE → REFACTOR)

## Files changed
- Added
  - `frontend/components/ItsmTicketFolioPage.tsx`
  - `frontend/components/TicketStatusStepper.tsx`
  - `frontend/components/__tests__/TicketFolioPage.test.tsx`
  - `frontend/components/__tests__/TicketStatusStepper.test.tsx`
- Updated
  - `frontend/types/itsm.ts`
  - `frontend/services/itsm.ts`
  - `frontend/services/__tests__/itsm_api.test.ts`
  - `frontend/App.tsx`
  - `frontend/App.itsm-route.test.tsx`
  - `openspec/changes/itsm-service-catalog/tasks.md`

## Completed Work Unit 4 tasks
- [x] 4.1 Add Ticket/Folio page and status stepper tests
- [x] 4.2 Add ticket endpoint and transition API client functions
- [x] 4.3 Add Ticket/Folio page and status stepper components
- [x] 4.4 Add `/itsm/tickets` route/navigation entry
- [x] 4.5 Add API/client/component sanity coverage ensuring no event endpoints are used
- [x] 4.6 Keep ITSM UI labels distinguishable from inventory wording

## TDD Cycle Evidence (WU4)
- RED: Ticket/Folio page, status stepper, API wrapper, and route tests were added/extended before implementation passed.
- GREEN: Ticket/Folio client functions, page, status stepper, and `/itsm/tickets` route were implemented.
- TRIANGULATE: UI exposes only next linear status transition and uses `/api/itsm/tickets` wrappers, not event endpoints.
- REFACTOR: Shared ITSM API wrapper now owns both Service Catalog and Ticket/Folio endpoints.

## Verification commands run
- `cd frontend && corepack pnpm exec vitest run App.itsm-route.test.tsx components/__tests__/ItsmServiceCatalogPage.test.tsx components/__tests__/TicketFolioPage.test.tsx components/__tests__/TicketStatusStepper.test.tsx services/__tests__/itsm_api.test.ts`
  - Result: PASS (5 files, 19 tests)
- `cd backend && /tmp/next-gen-it-sm-venv/bin/python -m pytest tests/test_itsm_domain_contracts.py tests/test_migration_itsm_catalog.py tests/test_itsm_startup_checks.py tests/test_itsm_service_catalog_service.py tests/test_ticket_folio_service.py tests/test_routers_itsm.py tests/test_event_service_smoke.py -q`
  - Result: PASS (97 passed, 0 warnings)

## Remaining apply risks
- None for focused ITSM backend/frontend scope.

---

## Apply Progress — Verify Remediation

## Status
- change: `itsm-service-catalog`
- unit: `Verify remediation — Ticket/Folio update + close flow`

## Files changed
- Updated
  - `frontend/components/ItsmTicketFolioPage.tsx`
  - `frontend/components/__tests__/TicketFolioPage.test.tsx`

## Remediated verification blockers
- Ticket/Folio UI now supports editing existing folios through `updateTicketFolio`.
- Closing a resolved ticket prompts for a close reason and sends it to `transitionTicketFolio`.
- Closed tickets remain read-only for edit actions.

## Verification commands run
- `cd frontend && corepack pnpm exec vitest run components/__tests__/TicketFolioPage.test.tsx components/__tests__/TicketStatusStepper.test.tsx services/__tests__/itsm_api.test.ts App.itsm-route.test.tsx`
  - Result: PASS (4 files, 17 tests)
- `cd frontend && corepack pnpm test:run`
  - Result: PASS (69 files, 571 tests)

---

## Delivery Strategy Exception

The user explicitly accepted delivering this change as a single oversized PR despite the 400-line review budget forecast. This is recorded as a `size:exception` for `itsm-service-catalog`.

---

## Apply Progress — 4R Remediation

## Status
- change: `itsm-service-catalog`
- unit: `Review remediation — risk/resilience/reliability`

## Remediated review findings
- Backend now treats closed tickets as read-only and rejects direct updates after closure.
- Backend rejects blank Ticket/Folio titles.
- Backend rejects direct `archived` updates unless they are produced by the `closed` transition.
- Service/repository update paths preserve explicit `null` clears for optional fields.
- Clearing `service_catalog_id` now synchronizes/removes the derived `FOR_SERVICE` relationship.
- Ticket/Folio list endpoint now has bounded pagination via `limit` with default 100/max 500.
- Startup bootstrap now runs an additive ServiceCatalog compatibility backfill before strict duplicate/conflict preflight and constraints.
- Accidental unrelated Python 3.9 compatibility edits were reverted from non-ITSM files.

## Verification commands run
- `cd backend && /tmp/next-gen-backend-py311/bin/python -m pytest tests/test_itsm_startup_checks.py tests/test_itsm_service_catalog_service.py tests/test_ticket_folio_service.py tests/test_routers_itsm.py -q`
  - Result: PASS (36 passed; one third-party passlib deprecation warning from auth import path)
- `cd backend && /tmp/next-gen-backend-py311/bin/python -m pytest tests/test_itsm_domain_contracts.py tests/test_migration_itsm_catalog.py tests/test_itsm_startup_checks.py tests/test_itsm_service_catalog_service.py tests/test_ticket_folio_service.py tests/test_routers_itsm.py tests/test_event_service_smoke.py tests/test_auth_extended.py::TestPermissionSecurity::test_permission_enum_completeness -q`
  - Result: PASS (103 passed; one third-party passlib deprecation warning from auth import path)
- `cd frontend && corepack pnpm test:run`
  - Result: PASS (69 files, 571 tests)
