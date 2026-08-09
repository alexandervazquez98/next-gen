# Tasks: Clean-Slate Service Management Catalog and Ticketing Evolution

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,100-1,900 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 backend ID/core contracts; PR 2 catalog + value-stream domain; PR 3 cross-store lock semantics + assignee lifecycle; PR 4 atomic XLSX imports; PR 5 frontend renaming + compatibility + import UX |
| Delivery strategy | feature-branch-chain |
| Chain strategy | feature-branch-chain (tracker; child PRs merge sequentially to tracker) |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain (tracker; child PRs merge sequentially to tracker)
400-line budget risk: High

## Ground rules (this slice)
- Clean-slate only: **no migrations** and no backfill.
- Numeric ticket PK is server-generated only.
- Catalog `service_type` is immutable and typed (`incident` | `service_request`).
- Dictionary value-stream is required and must be actively selected.
- One active assignee per ticket with shared PostgreSQL lock + Neo4j write, no two-phase distributed claim.
- Catalog and ticket XLSX imports are atomic: any validation error results in zero writes.
- Excel catalog header for SLA must be `SLA` (external workbook), mapped to internal `sla_target_minutes`.
- Ticket template must include service reference worksheets.
- Maintain backend/frontend contract compatibility for shared types/endpoints.
- **Approved PR1 boundary adjustment:** include only the catalog backend `service_type`/`active` contract needed for independently usable required compatible-ticket creation. Exclude value streams, catalog UI, XLSX, user locking/lifecycle, and frontend work.
    - Every ticket create contract requires `service_catalog_id`; the referenced catalog must exist, be active, and match the ticket type.

## Strict TDD loop (per work unit)
**RED -> GREEN -> TRIANGULATE -> REFACTOR**
- RED: add/extend tests first.
- GREEN: implement behavior in target files.
- TRIANGULATE: verify sequencing, invariants, and cross-file consistency.
- REFACTOR: clean-up without changing behavior.

## Acceptance requirements map (from `openspec/changes/service-management-catalog/specs/service-management-catalog/spec.md`)
- **REQ-01**: Ticket IDs are server-generated numerics; client-supplied `ticket_id` rejected.
- **REQ-02**: Catalog is typed (`incident`/`service_request`), immutable by type, unique by `service_id`, active `value_stream` from dictionary.
- **REQ-03**: Ticket/catalog compatibility enforced in UI and backend.
- **REQ-04**: Exactly one active assignee per ticket.
- **REQ-05**: User deactivation is logical and preserves historical ticket context.
- **REQ-06**: Catalog import is atomic, with workbook header validation and per-row errors.
- **REQ-07**: Ticket import is atomic, template-based, reference-driven, compatibility- and assignee-safe.
- **REQ-08**: Strict TDD evidence for all requirements.

## [x] Work Unit 1 — backend: ticket domain contracts and clean-slate identity model (foundational)
Dependencies: proposal, design, spec complete.

- **Target areas**: `backend/models/itsm.py`, `backend/tests/test_itsm_domain_contracts.py`
- **RED evidence**:
  - Add/extend tests for `TicketFolioCreate` request rejects `ticket_id` and `ticket_id` in response is numeric.
  - Add tests for allowed ticket types only (`incident`, `service_request`) and default ticket response shape.
  - Add test proving no migration-backed legacy alias assumptions for IDs.
- **GREEN evidence**:
  - Update domain model aliases/types and validation constraints for `ticket_id`, `type`, and required create payload fields.
  - Add explicit numeric ID contract and canonical enum values.
- **Acceptance linkage**:
  - REQ-01, REQ-08.
- **Validation commands**:
  - `cd backend && python -m pytest backend/tests/test_itsm_domain_contracts.py -q`

- **TRIANGULATE evidence**:
  - Confirm existing ticket model consumers (`backend/tests`, service/router code) continue to pass with numeric-only IDs and no `ticket_id` input.
- **REFACTOR evidence**:
  - Normalize naming and validation messages to keep API error shapes deterministic across tests and UI clients.

## [x] Work Unit 2 — backend: sequence allocator + single-ticket create persistence with shared lock semantics
Dependencies: Work Unit 1 complete.

- **Target areas**:
  - `backend/repositories/ticket_folio_repo.py`
  - `backend/services/ticket_folio_service.py`
  - `backend/routers/ticket_folios.py`
  - `backend/tests/test_ticket_folio_repo.py`
  - `backend/tests/test_ticket_folio_service.py`
- **RED evidence**:
  - Add failing tests for generated ID allocation and deterministic failure when allocator missing.
  - Add failing tests asserting create rejects payloads containing `ticket_id`.
  - Add failing tests for optimistic preflight vs persistence guard when write-time validation fails.
- **GREEN evidence**:
  - Implement sequence node allocation flow in write transaction.
  - Reject client `ticket_id` at boundary.
  - Create ticket transaction writes numeric `ticket_id`; no row persistence on create failure.
- **Acceptance linkage**:
  - REQ-01.
- **Validation commands**:
  - `cd backend && python -m pytest backend/tests/test_ticket_folio_repo.py backend/tests/test_ticket_folio_service.py -q`

- **TRIANGULATE evidence**:
  - Validate transaction boundary: sequence increment and ticket create are atomic and rollback-safe.
- **REFACTOR evidence**:
  - Extract allocation + mapping helpers for easier lock/transaction testing.

## [x] PR1 boundary extension — minimum persisted catalog compatibility contract
Dependencies: Work Units 1–2 complete.

- **Completed scope:** `ServiceCatalogCreate`/update validation accepts only immutable `service_type` values (`incident`, `service_request`); repository create/read/update responses persist and return `service_type` and `active`; ticket preflight and same-transaction Neo4j write require active type compatibility.
- **RED/GREEN evidence:** integration/service coverage creates a catalog through the supported catalog service, creates a same-type ticket, rejects an incompatible persisted type, and rejects service-type mutation; focused backend suite passes.
- **Explicit exclusions:** value streams, catalog UI, XLSX import, user locking/lifecycle, and frontend work remain later work units.
- **Acceptance linkage:** REQ-02 and REQ-03 (minimum backend contract only).

## [ ] PR3 boundary adjustment — cross-store assignee locking + user lifecycle
Dependencies: Work Units 1, 2, and PR2 boundary extension complete.

- **Slice scope:** Work Unit 3 only. Adds `assignee_username` (required, exactly one) to `TicketFolioCreate`; resolves the user through the user repository; acquires a PostgreSQL per-user advisory lock (`pg_advisory_xact_lock(hashtext('user:' || lower(username)))`) for the duration of the ticket create transaction; revalidates `is_active=True` while the lock is held; releases on commit, rollback, or bounded timeout. Exposes `POST /api/users/{username}/deactivate` (logical, no destructive delete). Snapshot fields (`assignee_display_name`, `assignee_active_at_assignment`) captured at create time; `assignee_currently_active` recomputed at read time and updated by deactivation flows.
- **Explicit exclusions:** bulk XLSX ticket import (`WU 7` consumes the lock helper but ships with PR 4), frontend assignee selector and ticket form rename (`WU 8` ships with PR 5), end-to-end release verification (`WU 9`).
- **Acceptance linkage:** REQ-04 (single active assignee on create), REQ-05 (logical deactivation preserves ticket history). REQ-03 (catalog/ticket compatibility) is already covered by the PR2 boundary extension and remains green.
- **Lock-ordering rule:** when batch operations acquire multiple per-user locks in the same transaction, they acquire in normalized (`lower()`) username order. PR 3 implements the helper; PR 4 (import) consumes it.
- **Strict TDD:** every behavior change ships with failing RED tests first. Lock helper, validator, and deactivate endpoint each get their own RED → GREEN → TRIANGULATE → REFACTOR cycle in the same work unit. Local verify uses `cd backend && python -m pytest …` and `cd backend && python -m ruff check --config ruff.toml …` from the `backend/` working directory (matching CI).
- **Slice design doc:** `openspec/changes/service-management-catalog/pr3-design.md`.

## Work Unit 3 — backend: shared active-user locking + logical deactivation contract
Dependencies: Work Unit 2 complete.

- **Target areas**:
  - `backend/services/ticket_folio_service.py`
  - `backend/routers/users.py`
  - `backend/repositories/user_repo.py`
  - `backend/tests/test_users.py` or equivalent user lifecycle test file
- **RED evidence**:
  - Add failing tests for single assignee cardinality (1 required, exactly).
  - Add failing tests for inactive assignee rejection at write-time after preflight.
  - Add failing interleaving tests proving shared lock ordering and conflict behavior for create/import vs user deactivate.
- **GREEN evidence**:
  - Implement PostgreSQL per-user lock acquisition and write-time revalidation while holding lock through Neo4j write.
  - Ensure deactivation is logical-only (no destructive ticket rewrites), keeps snapshots stable.
  - Make duplicate assignee handling deterministic in batch paths.
- **Acceptance linkage**:
  - REQ-04, REQ-05, REQ-03 (compatibility with active-state assumptions).
- **Validation commands**:
  - `cd backend && python -m pytest backend/tests/test_ticket_folio_service.py backend/tests/test_routers_users.py backend/tests/test_users.py -q`

- **TRIANGULATE evidence**:
  - Validate timeout/retryable conflict behavior and no partial ticket creation on lock timeout.
- **REFACTOR evidence**:
  - Move lock orchestration behind a narrow boundary for easier testability and deterministic error mapping.

## Work Unit 4 — backend: catalog domain governance (typed catalog + immutable type + value streams)
Dependencies: Work Unit 2 complete.

- **Target areas**:
  - `backend/services/itsm_service_catalog_service.py`
  - `backend/repositories/itsm_service_catalog_repo.py`
  - `backend/tests/test_itsm_service_catalog_service.py`
  - `backend/tests/backend_tests_for_value_streams` (new or existing dict/list seam tests)
- **RED evidence**:
  - Add failing tests for immutable `service_type`.
  - Add failing tests for unique `service_id` and `(service_type, normalized_name)`.
  - Add failing tests for required fields (`SLA`, `description`, `value_stream`) and active dictionary enforcement.
- **GREEN evidence**:
  - Implement catalog create/update rules and validation pipeline.
  - Integrate dictionary/list lookup seam for active `value_stream` only.
- **Acceptance linkage**:
  - REQ-02.
- **Validation commands**:
  - `cd backend && python -m pytest backend/tests/test_itsm_service_catalog_service.py -q`

- **TRIANGULATE evidence**:
  - Confirm dictionary value lifecycle (`active`/`inactive`) impacts only validation path and does not mutate service rows.
- **REFACTOR evidence**:
  - Consolidate catalog validation errors into deterministic canonical field keys.

## Work Unit 5 — backend: compatibility enforcement in single-ticket flows (backend+front data source)
Dependencies: Work Unit 4 complete.

- **Target areas**:
  - `backend/services/ticket_folio_service.py`
  - `backend/routers/ticket_folios.py`
  - `backend/services/itsm_service_catalog_service.py`
  - `backend/tests/test_itsm_service_catalog_service.py`
  - `backend/tests/test_ticket_folio_service.py`
  - `backend/tests/test_routers_itsm.py`
- **RED evidence**:
  - Add/update tests asserting backend rejects incompatible service type mapping and inactive service references.
  - Add tests verifying error field mapping on write-time rejection (`service_catalog_id` / mismatch/inactive).
  - Add tests for deterministic response when payload includes client `ticket_id`.
- **GREEN evidence**:
  - Add service-type compatibility checks both preflight and write-time, with service refresh before write.
  - Ensure all reject paths persist zero tickets.
- **Acceptance linkage**:
  - REQ-03, REQ-01.
- **Validation commands**:
  - `cd backend && python -m pytest backend/tests/test_routers_itsm.py backend/tests/test_ticket_folio_service.py -q`

- **TRIANGULATE evidence**:
  - Confirm request validation and write-time validation return identical canonical field errors for equivalent invalid cases.
- **REFACTOR evidence**:
  - Normalize error constructors and payload contract helper shared by ticket create/import.

## Work Unit 6 — backend: atomic XLSX catalog import stack (template, parser, validator, transaction)
Dependencies: Work Unit 4 and Work Unit 5 complete.

- **Target areas**:
  - `backend/services/itsm_imports/workbook.py`
  - `backend/services/itsm_imports/errors.py`
  - `backend/services/itsm_imports/catalog_import.py`
  - `backend/routers/itsm_service_catalog.py`
  - `backend/tests/test_itsm_catalog_import.py` (new)
- **RED evidence**:
  - Add failing tests for template header contract requiring `SLA` and rejecting `sla_target_minutes`.
  - Add failing row/field error tests with deterministic `row/field/code` payload.
  - Add failing atomicity tests: any invalid row → zero writes.
- **GREEN evidence**:
  - Implement template download with mandatory `Catalog Import` and `Ref - Value Streams` sheets.
  - Add parser/validator/normalizer and repository write in one atomic operation.
  - Return `validation_failed` payload schema with error caps and workbook-aware row numbers.
- **Acceptance linkage**:
  - REQ-02, REQ-06.
- **Validation commands**:
  - `cd backend && python -m pytest backend/tests/test_itsm_catalog_import.py -q`

- **TRIANGULATE evidence**:
  - Verify generated template/workbook import cycle and guard behavior (`.xlsx` + size limit).
- **REFACTOR evidence**:
  - Extract shared workbook helpers usable by ticket import package.

## Work Unit 7 — backend: atomic XLSX ticket import with reference sheets + lock-aware full-batch behavior
Dependencies: Work Unit 3, Work Unit 5, and Work Unit 6 complete.

- **Target areas**:
  - `backend/services/itsm_imports/ticket_import.py`
  - `backend/services/itsm_imports/catalog_import.py` (shared helpers)
  - `backend/routers/ticket_folios.py`
  - `backend/tests/test_itsm_ticket_import.py` (new)
- **RED evidence**:
  - Add failing tests for required headers on `Ticket Import` and reference sheet contents (`Ref - Incident Services`, `Ref - Service Request Services`, `Ref - Active Users`).
  - Add failing tests for assignee/service validation at row-level and write-time.
  - Add failing tests proving all-or-nothing commit and lock-ordered behavior for distinct assignees.
- **GREEN evidence**:
  - Implement full parser/validator path for ticket bulk import with compatibility checks against active references.
  - Implement lock acquisition before all-or-nothing Neo4j write; return zero-created on any failure.
- **Acceptance linkage**:
  - REQ-03, REQ-04, REQ-07.
- **Validation commands**:
  - `cd backend && python -m pytest backend/tests/test_itsm_ticket_import.py -q`

- **TRIANGULATE evidence**:
  - Assert import failure cannot consume ticket IDs or create partial writes.
- **REFACTOR evidence**:
  - Consolidate common error payload mapping between catalog and ticket import paths.

## Work Unit 8 — frontend: Service Management naming, contract-aligned ticket/catalog forms, and compatibility selectors
Dependencies: Work Unit 5 complete.

- **Target areas**:
  - `frontend/components/ItsmTicketFolioPage.tsx`
  - `frontend/components/ItsmServiceCatalogPage.tsx`
  - `frontend/services/itsm.ts`
  - `frontend/types/itsm.ts`
  - `frontend/components/__tests__/TicketFolioPage.test.tsx`
  - `frontend/components/__tests__/ItsmServiceCatalogPage.test.tsx`
- **RED evidence**:
  - Add/extend component tests:
    - no editable ticket ID field;
    - numeric ticket ID shown after create;
    - service selectors filtered by selected ticket type;
    - assignee required and exactly one target;
    - rejection of incompatible service/service-type combinations in UI flow.
  - Update API/type tests for numeric `ticket_id` and canonical enums.
- **GREEN evidence**:
  - Rename visible surfaces to **Service Management**.
  - Update payloads to omit client `ticket_id`.
  - Add value-stream selector and catalog type controls with immutability-safe behavior.
- **Acceptance linkage**:
  - REQ-03, REQ-04, REQ-02, REQ-01.
- **Validation commands**:
  - `cd frontend && corepack pnpm test:run frontend/components/__tests__/TicketFolioPage.test.tsx frontend/components/__tests__/ItsmServiceCatalogPage.test.tsx`

- **TRIANGULATE evidence**:
  - Run component route and render smoke checks if available for isolated nav labels.
- **REFACTOR evidence**:
  - Share canonical type/value enum and service option utilities across catalog and ticket views.

## Work Unit 9 — end-to-end compatibility checks and release-ready verification
Dependencies: Work Units 1–8 complete.

- **Target areas**:
  - `backend/routers/ticket_folios.py`
  - `backend/routers/itsm_service_catalog.py`
  - `frontend/App.tsx` or routing entry used for ITSM surface
  - any shared API client wrappers
- **RED evidence**:
  - Add/extend router tests for route coverage and permissions across create/read/import endpoints.
  - Add/extend component+integration tests ensuring Service Management remains isolated from unrelated modules.
- **GREEN evidence**:
  - Confirm API contract compatibility between frontend and backend types for all impacted responses/payloads.
  - Ensure catalog/ticket import endpoints remain under explicit ITSM permission gates.
- **Acceptance linkage**:
  - REQ-01, REQ-02, REQ-03, REQ-04, REQ-06, REQ-07, REQ-08.
- **Validation commands**:
  - `cd backend && python -m pytest backend/tests/test_routers_itsm.py backend/tests/test_routers_nodes.py -q`
  - `cd frontend && corepack pnpm test:run`

- **TRIANGULATE evidence**:
  - Validate one run of strict TDD sequence can be demonstrated by test diff ordering per unit; no implementation without prior RED coverage.
- **REFACTOR evidence**:
  - Add final changelog/test notes in tasks/completion notes if any cross-PR boundary assumptions remain.

## Completion checklist before apply
- [ ] All required spec requirements (REQ-01 through REQ-08) have direct automated evidence.
- [ ] No migration file is added in this change.
- [ ] Import work proves atomic persistence on catalog and ticket XLSX workflows.
- [ ] Cross-store locking behavior remains single-assignee and active-only.
- [ ] Service Management naming and route/path compatibility is preserved without breaking inventory/catalog routes.
