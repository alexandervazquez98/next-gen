# Technical Design: Clean-Slate Service Management Catalog

This design defines the initial target state for Service Management in a confirmed clean-slate environment. No active or deployed tickets or services exist at rollout time, so the implementation creates the new schema, bootstrap data, API contracts, UI behavior, and tests directly in the target shape.

## Design summary

| Area | Decision |
|---|---|
| Environment | Clean-slate launch: no existing Service Management tickets or services need data conversion or prior-record support. |
| Ticket identity | `ticket_id` is a server-generated numeric primary key allocated inside the ticket write transaction. Clients never provide it. |
| Ticket type vocabulary | Canonical type is exactly `incident` or `service_request`. New UI, APIs, templates, and tests use these values only. |
| Catalog governance | Service catalog records require globally unique `service_id`, unique name within each `service_type`, required SLA, description, active dictionary value stream, and immutable `service_type`. |
| Value streams | Value streams come from a managed dictionary/list model with active/inactive lifecycle. Only active values are valid for new catalog rows. |
| Service compatibility | Backend and UI enforce that ticket type matches the referenced catalog service `service_type`. |
| Assignee | Each created ticket has exactly one active user assignee. The ticket stores assignee identity fields so future logical user deactivation does not break prior ticket display. |
| XLSX imports | Catalog and ticket imports use downloadable templates, structured row/field errors, and all-or-nothing persistence. Ticket templates include service reference worksheets. |
| CI bulk reuse | Reuse CI import interaction shape and route ergonomics where useful, but Service Management imports are atomic and never partially successful. |
| Strict TDD | Implementation must begin with failing tests for every requirement seam before production changes. |

## Approved PR1 boundary adjustment

PR1 includes the minimum catalog backend contract required for an independently usable ticket create flow. The catalog API/repository now persists and returns immutable `service_type` (`incident` or `service_request`) plus `active` status. Ticket selection and the same Neo4j write transaction require an existing active catalog whose persisted `service_type` matches the ticket `type`; incompatible or inactive references create no ticket. This slice does not include value streams, catalog UI, XLSX import, user locking/lifecycle, or frontend changes.

## Current code anchors

| Concern | Current anchor | Required change |
|---|---|---|
| Ticket router | `backend/routers/ticket_folios.py` | Keep `/itsm/tickets`; add template/import routes; reject create bodies containing `ticket_id`. |
| Ticket model | `backend/models/itsm.py::TicketFolioCreate` | Remove required client `ticket_id`; add `assignee_username`; switch type enum to `incident`/`service_request`. |
| Ticket service | `backend/services/ticket_folio_service.py` | Generate numeric IDs, validate active assignee, validate service compatibility, create in one transaction. |
| Ticket repo | `backend/repositories/ticket_folio_repo.py` | Add initial `TicketSequence` allocator and atomic bulk ticket create method. |
| Catalog router/service/repo | `backend/routers/itsm_service_catalog.py`, `backend/services/itsm_service_catalog_service.py`, `backend/repositories/itsm_service_catalog_repo.py` | Add governed fields, active value-stream validation, immutable type enforcement, typed list filtering, template/import routes. |
| Catalog UI | `frontend/components/ItsmServiceCatalogPage.tsx` | Add required fields, value-stream selector, import UX, structured validation table. |
| Ticket UI | `frontend/components/ItsmTicketFolioPage.tsx` | Rename visible surface, remove ticket ID input, add type-filtered service selector, assignee selector, import UX. |
| Frontend API/types | `frontend/types/itsm.ts`, `frontend/services/itsm.ts` | Use numeric ticket IDs, canonical type enum, assignee fields, and import contracts. |
| User management | `backend/routers/users.py`, `backend/repositories/user_repo.py` | Provide active-user lookup for assignee selectors and logical deactivation for users with ticket references. |
| CI bulk reference | `backend/routers/nodes.py`, `backend/services/node_service.py` | Reuse file guard/template/download/upload patterns where they reduce duplicate UX or validation code. |

## Initial schema and bootstrap

### Ticket identity

Create the Service Management ticket model in the target form:

| Field | Rule |
|---|---|
| `ticket_id` | Numeric server-generated primary key, visible to users and returned by APIs. |
| `type` | Required enum: `incident` or `service_request`. |
| `title` | Required non-empty string. |
| `description` | Required for imports; single create follows product validation and should reject blank values unless explicitly relaxed. |
| `service_catalog_id` | Required for every ticket; must point to an existing active compatible service. |
| `assignee_username` | Required; exactly one active user. |
| `assignee_display_name` | Snapshot at assignment time for stable display. |
| `assignee_active_at_assignment` | `true` at create time. Current active state may be shown as enrichment later. |
| `status`, `closed_reason`, timestamps, `updated_by` | Existing lifecycle fields retained where they still apply. |

Bootstrap a singleton sequence node as part of initial environment setup:

```cypher
MERGE (seq:TicketSequence {name: 'ticket_folio'})
ON CREATE SET seq.next_value = 0
```

`TicketFolioRepository.allocate_ticket_id(tx)` increments this sequence inside the same Neo4j write transaction that creates the ticket:

```cypher
MATCH (seq:TicketSequence {name: 'ticket_folio'})
SET seq.next_value = seq.next_value + 1
RETURN seq.next_value AS ticket_id
```

Rules:

- The allocator does not accept client IDs.
- A missing sequence is a bootstrap error; create/import fails without writing tickets.
- The sequence increment and ticket creation occur in the same transaction.
- Bulk ticket import allocates one ID per valid row inside the final write transaction.
- Use database uniqueness constraints for `TicketFolio.ticket_id` and `TicketSequence.name` during initial setup.

### Catalog model

Create `ServiceCatalog` records in the governed target shape:

| Field | Type | Rule |
|---|---|---|
| `service_id` | string | Required globally unique business key. |
| `name` | string | Required non-empty; unique within the same `service_type`; same name may exist once in each type when `service_id` differs. |
| `sla_target_minutes` | integer | Required, non-negative internal SLA field. The user-facing UI and XLSX workbook label it `SLA`. |
| `description` | string | Required non-empty. |
| `service_type` | enum | Required: `incident` or `service_request`; immutable after create. |
| `value_stream` | string key | Required; must reference an active value-stream dictionary value. |
| `active` | boolean | Active services can be selected for new tickets/import rows; inactive services remain readable but not selectable. |
| timestamps, `updated_by` | metadata | Standard create/update metadata. |

Catalog constraints and repository validation should enforce:

- unique `service_id`;
- unique normalized `(service_type, name)`;
- immutable `service_type` for every update path;
- required governed fields on create and update;
- active value-stream lookup before persistence.

### Value-stream dictionary

Add a generic managed dictionary/list value model under the existing dictionary surface:

| Field | Rule |
|---|---|
| `dictionary_key` | `value_stream` for this slice. |
| `value` | Stable key stored on catalog records and XLSX rows. |
| `label` | Display label. |
| `active` | Only active values are selectable and valid for catalog create/import. |
| `created_at`, `updated_at`, `updated_by` | Standard lifecycle metadata. |

Backend seam:

```python
ValueStreamLookup.list_active() -> list[dict]
ValueStreamLookup.is_active(value: str) -> bool
```

Keep this behind a small repository/service boundary so tests can inject active and inactive values without depending on the dictionary UI.

## API contracts

### Ticket create

Request bodies must omit `ticket_id`.

```json
{
  "type": "incident",
  "title": "Router down",
  "description": "Core router unreachable",
  "service_catalog_id": "NET-INC-001",
  "assignee_username": "operator1"
}
```

Response:

```json
{
  "ticket_id": 12345,
  "type": "incident",
  "title": "Router down",
  "description": "Core router unreachable",
  "service_catalog_id": "NET-INC-001",
  "assignee_username": "operator1",
  "assignee_display_name": "Operator One",
  "assignee_currently_active": true,
  "status": "open",
  "closed_reason": null,
  "created_at": "...",
  "updated_at": "...",
  "updated_by": "admin"
}
```

Validation:

- If request body contains `ticket_id`, return `400` or `422` with a deterministic field error and create nothing.
- `type` must be `incident` or `service_request`.
- `assignee_username` is required and must resolve to exactly one active user.
- `service_catalog_id` is required and must resolve to an existing active service with matching `service_type`.
- Preflight validation may provide early feedback, but is not authoritative for persistence.
- The ticket write transaction must re-read the catalog service, confirm that it is active and type-compatible, then create the ticket, store assignment snapshot fields, and link the selected catalog service. PostgreSQL user state cannot be re-read in that Neo4j transaction.
- Active-assignee revalidation uses the cross-store serialization protocol below. It is authoritative at persistence time; preflight is not.
- If write-time revalidation fails, create nothing and return a deterministic field error: `assignee_username` / `assignee_inactive_at_write` for a missing or inactive assignee; `service_catalog_id` / `service_unavailable_at_write` for a missing or inactive service; or `service_catalog_id` / `service_type_mismatch_at_write` for an incompatible service.

### Cross-store assignee serialization

PostgreSQL is authoritative for user status and Neo4j is authoritative for tickets. This design does **not** use or imply a distributed transaction. Instead, ticket assignment and user deactivation serialize on the same PostgreSQL per-user lock.

1. For a single create, acquire a transaction-scoped PostgreSQL advisory lock derived deterministically from `assignee_username` (or lock the authoritative user row with an equivalent documented per-user lock). For an import, acquire the same locks for every distinct assignee in normalized username order before any Neo4j write; duplicate usernames acquire one lock.
2. While holding the PostgreSQL lock, read the authoritative user row and require exactly one active user. Keep the PostgreSQL transaction and lock open through the Neo4j write transaction: revalidate the catalog service, allocate ticket ID(s), create ticket(s), and commit Neo4j.
3. If Neo4j commits, commit the PostgreSQL transaction and release the lock. The resulting ticket was assigned while its user was active. If user validation fails, Neo4j validation fails, or the Neo4j transaction fails or times out, roll back/close the PostgreSQL transaction, release all locks, and return no created ticket(s). A Neo4j commit failure must never be reported as success.
4. User deactivation starts a PostgreSQL transaction, acquires that exact same per-user lock, then re-reads the user. Only after acquiring it may it change `active` to `false` and commit. It does not delete the user or ticket snapshots, so later logical deactivation preserves ticket history.
5. Lock acquisition has a bounded configured timeout. A timeout or retryable serialization/deadlock error creates no ticket(s), changes no user state, releases acquired locks, and returns a retryable deterministic conflict/error. Retry policy uses bounded retries with backoff; an import retries the whole batch only before any Neo4j commit, never individual rows. Lock ordering is normalized username order for imports and deactivation acquires only one lock, preventing lock-order cycles.

The only permitted interleavings are: (a) ticket create/import obtains the lock first, validates active, commits Neo4j, then deactivation obtains the lock and logically deactivates; or (b) deactivation commits first, then ticket create/import obtains the lock and rejects the inactive assignee. A process crash after Neo4j commit but before PostgreSQL commit/release is an operational reconciliation risk, not an atomic distributed outcome: the lock is released by PostgreSQL transaction recovery and reconciliation must detect any ticket whose snapshot assignment conflicts with the authoritative user transition audit before retrying or reporting the request.

### Ticket reads and updates

- `GET /itsm/tickets/{ticket_id}` accepts numeric IDs only.
- Responses include numeric `ticket_id` and assignee display/enrichment fields.
- Edit flows keep ticket type immutable for this slice unless a later proposal defines safe type transitions.
- Reassignment, if supported in this slice, must validate exactly one active target user and update assignment snapshot fields in the same ticket update transaction.

### Catalog create/update

Create payloads require `service_id`, `name`, `sla_target_minutes`, `description`, `service_type`, and `value_stream`.

Update rules:

- `service_id` is path-authoritative and immutable.
- `service_type` is immutable after create.
- `name` changes must preserve unique `(service_type, normalized_name)`.
- `value_stream` changes must reference an active dictionary value.
- `active=false` removes the service from new ticket selectors and import reference sheets.

### Import endpoints

Add endpoints under existing ITSM routers:

| Endpoint | Behavior |
|---|---|
| `GET /itsm/service-catalog/template` | Download catalog XLSX template. |
| `POST /itsm/service-catalog/import` | Validate and atomically import catalog rows. |
| `GET /itsm/tickets/template` | Download ticket XLSX template with reference worksheets. |
| `POST /itsm/tickets/import` | Validate and atomically create tickets. |

Use the same permission model as manual writes: `ITSM_EDIT` required.

## XLSX workbook contracts

### Shared parsing architecture

Create a small import package rather than embedding parser logic in routers:

```text
backend/services/itsm_imports/
  workbook.py              # file guards, workbook loading, sheet/header helpers
  errors.py                # ImportValidationError / RowFieldError contracts
  catalog_import.py        # template + parse + validate + persist orchestration
  ticket_import.py         # template + parse + validate + persist orchestration
```

Use `openpyxl` for deterministic workbook/sheet handling and cell-aware row numbers. CI import code can guide route shape and upload UX, but Service Management validation owns its row/field error contract.

### Error response contract

All import validation failures return zero persisted records and a machine-readable payload:

```json
{
  "status": "validation_failed",
  "message": "Workbook validation failed; no records were imported.",
  "errors": [
    {
      "row": 4,
      "field": "service_type",
      "reason": "Must be one of: incident, service_request",
      "code": "invalid_enum"
    }
  ]
}
```

Rules:

- `row` is the visible Excel row number; the header row is row `1`.
- `field` is the canonical field key.
- Return one entry per independent failure.
- Cap error count for response safety and include `error_count` when capped.
- Parse failures before row extraction use `row: null`, `field: "workbook"`.

### Catalog workbook

Sheet: `Catalog Import`

Required external workbook headers:

- `service_id`
- `name`
- `SLA`
- `description`
- `service_type`
- `value_stream`
- optional `active`

`SLA` is the sole canonical user-facing workbook header. Template generation emits `SLA`; header validation requires `SLA` and rejects `sla_target_minutes` as a header. The parser explicitly maps `SLA` to the internal `sla_target_minutes` DTO/model field before integer and non-negative validation. Row/field errors use the internal canonical field key `sla_target_minutes`.

Reference sheet: `Ref - Value Streams`

- active value stream keys and labels;
- no inactive values in selectable reference rows.

Validation phases:

1. File guard: `.xlsx` and configured size limit.
2. Header validation: all required canonical headers are present.
3. Row normalization: trim strings, parse integers/booleans.
4. In-file validation: duplicate `service_id`, duplicate `(service_type, name)`, required values, `SLA` mapped to non-negative `sla_target_minutes`, valid enum, active value stream.
5. Database validation: existing `service_id` and `(service_type, name)` conflicts; immutable type rules for any supported upsert mode.
6. Transactional write: one Neo4j write transaction after every row passes validation.

### Ticket workbook

Sheet: `Ticket Import`

Required headers:

- `type`
- `title`
- `description`
- `service_catalog_id`
- `assignee_username`

Reference sheets:

| Sheet | Contents |
|---|---|
| `Ref - Incident Services` | Active `service_id`, `name`, `value_stream` where `service_type=incident`. |
| `Ref - Service Request Services` | Active `service_id`, `name`, `value_stream` where `service_type=service_request`. |
| `Ref - Active Users` | Active assignable usernames and display fields. |

Validation phases:

1. File/header validation.
2. Row normalization with canonical type values only.
3. Required field validation.
4. Service lookup validation: service exists, active, and type-compatible.
5. Assignee validation: exactly one `assignee_username`, user exists, and user is active.
6. Acquire PostgreSQL per-user locks for all distinct normalized assignees in sorted order, validate each authoritative user is active while locks remain held, then allocate IDs and create all tickets in one Neo4j write transaction while revalidating every service immediately before its ticket is created.

Transaction boundary: validate all rows before any write. If validation passes, acquire the shared PostgreSQL assignee locks and keep them through the one Neo4j write transaction. If a concurrent deactivation wins the lock or any assignee/service becomes invalid, return the deterministic write-time row/field error, roll back the Neo4j transaction, release PostgreSQL locks, and persist zero tickets. No distributed transaction is claimed.

## Backend validation flow

### Single ticket create

```text
Router
  -> reject body containing ticket_id at request boundary
  -> Pydantic model validation
  -> optional service preflight validates assignee and catalog compatibility for early feedback
  -> repository.create_with_generated_id
       -> begin PostgreSQL transaction and acquire the shared per-user lock
       -> re-read authoritative user and require exactly one active assignee
       -> keep PostgreSQL lock through Neo4j transaction: re-read catalog, require active compatible service, allocate ID, create ticket, snapshot assignee, and commit Neo4j
       -> commit PostgreSQL transaction; otherwise roll back/close it, release lock, and return deterministic write-time field error or retryable lock error
  -> response normalization
```

### Catalog create/update

```text
Router
  -> Pydantic model validation
  -> service.validate_value_stream_active
  -> service.validate_service_type
  -> service.enforce_type_immutability
  -> service.enforce_service_id_and_name_uniqueness
  -> repository upsert/update
```

### Bulk imports

```text
Router
  -> file size/type guard
  -> import service loads workbook
  -> parser returns normalized row DTOs + parse errors
  -> validator accumulates row/field errors
  -> if errors: return structured failure, no repository writes
  -> repository executes one write transaction
```

## Frontend design

### Navigation and naming

- Rename visible `ITSM Tickets` navigation/module label to `Service Management`.
- Keep routes under `/itsm/...` for the first slice unless product explicitly requests route changes.
- Rename catalog UI copy to a Service Management catalog label while keeping it distinct from inventory/CI catalog routes.

### Ticket create/edit UI

- Remove editable `Ticket ID` from create form.
- Display generated numeric ticket ID after creation and in tables.
- Use canonical type options: `incident`, `service_request`.
- Load active services and filter by selected type before showing service options.
- Replace free-text `Service Catalog ID` input with a select/search selector backed by active compatible services.
- Add an assignee selector backed by active users.
- Block submit when assignee is missing, service is incompatible, or required fields are blank.

### Catalog UI

- Add required `description`, `service_type`, and `value_stream` inputs.
- Load active value stream values from dictionary/list API.
- Prevent submit when required fields are blank, type is invalid, value stream is inactive, or `(service_type, name)` would conflict.
- Display inactive catalog rows as deactivated and unavailable for new ticket creation.

### Bulk import UX

Reuse CI import interaction patterns:

- template download button;
- upload control with `.xlsx` guard;
- progress/loading state;
- validation report area.

Change the report semantics:

- no partial success messaging;
- show `Workbook validation failed; no records were imported` on validation failure;
- render structured row/field error table;
- on success, reload the relevant list and show created/imported count.

## Request/response compatibility

| Contract | Decision |
|---|---|
| Ticket create `ticket_id` | Intentional breaking clean-slate contract: clients must omit. Backend rejects if present. |
| Ticket response `ticket_id` | Numeric value. Frontend types and tests must update. |
| Ticket type values | New contracts accept and emit only `incident` and `service_request`. |
| Catalog routes | Keep current routes and add template/import endpoints. |
| CI import behavior | Do not change CI import behavior in this slice; only reuse interaction and structural ideas. |

## Test seams and strict TDD plan

Strict TDD is active. Implementation must start by adding failing tests at these seams, then production code, then refactor.

### Backend tests

| Test file area | Coverage |
|---|---|
| `backend/tests/test_itsm_domain_contracts.py` | Ticket create payload rejects `ticket_id`; numeric response model; canonical type enum; required catalog fields. |
| `backend/tests/test_ticket_folio_service.py` | Generated ID path, supplied ID rejection, active assignee validation, incompatible service rejection, compatible success, and deterministic propagation of write-time validation errors. |
| `backend/tests/test_ticket_folio_repo.py` or equivalent | Sequence allocation occurs in the Neo4j ticket write transaction; missing sequence rejects allocation without creating a ticket; record contains numeric ID and assignee fields; PostgreSQL per-user lock is held through active-user validation and Neo4j commit; concurrent deactivation either waits until a successfully committed ticket was assigned while active or wins and causes no ticket to persist. |
| `backend/tests/test_itsm_service_catalog_service.py` | Required description/SLA/value stream, inactive value stream rejection, immutable service type, unique `(service_type, name)`. |
| `backend/tests/test_routers_itsm.py` | Route payload pass-through, permission checks, template/import route contracts. |
| New import tests | Catalog template emits `SLA`; catalog parser accepts `SLA` and maps it to `sla_target_minutes`; `sla_target_minutes` workbook headers are rejected; catalog/ticket parser row numbers, structured errors, no writes on invalid workbook, one transaction on valid workbook; ticket imports roll back the full workbook when transactional assignee/service revalidation fails. |
| User tests | Users with ticket references are logically deactivated; inactive users are rejected as new assignees. |

### Frontend tests

| Test file area | Coverage |
|---|---|
| `frontend/components/__tests__/TicketFolioPage.test.tsx` | No Ticket ID input on create, numeric ID displayed, type-filtered services, assignee required, create payload omits `ticket_id`. |
| Catalog page tests | Required new fields, value stream selector, invalid submit prevention, import error table, duplicate-name-within-type prevention where UI can precheck. |
| API/type tests where present | Import/template service calls, numeric ticket ID type, canonical `service_request`. |
| Route/navigation tests | Visible `Service Management` label and isolation from inventory catalog. |

### Manual evidence only if automation is infeasible

Manual evidence may only supplement automated tests for workbook visual formatting or browser-specific file-picker behavior. All validation, parser, transaction, API, and UI state behavior must have automated coverage.

### Acceptance tests for write-time invariants and workbook headers

- A single-ticket create whose assignee becomes inactive after preflight but before it acquires the shared PostgreSQL per-user lock fails with `assignee_username` / `assignee_inactive_at_write` and persists no ticket.
- An interleaving test where create obtains the shared lock first proves deactivation blocks until Neo4j commits, then verifies the ticket snapshot was assigned while active and deactivation remains logical; the inverse ordering proves create rejects and persists no ticket after deactivation commits.
- An import test with multiple assignees proves locks are acquired in normalized username order, held through the all-or-nothing Neo4j commit, and released on failure. Lock timeout, retryable deadlock/serialization, and Neo4j failure tests prove no ticket/user change is reported as success and retries never create a partial batch.
- A single-ticket create whose selected service becomes inactive or changes to an incompatible type after preflight but before Neo4j write revalidation fails with the corresponding deterministic `service_catalog_id` error and persists no ticket.
- A valid ticket import in which an assignee or service becomes invalid before locked validation/Neo4j revalidation returns the row/field error, persists zero tickets, and does not consume committed ticket IDs.
- Catalog template generation emits `SLA`, never `sla_target_minutes`; a workbook using `SLA` imports its value into `sla_target_minutes`, while a workbook replacing `SLA` with `sla_target_minutes` receives a deterministic header validation error.

## Natural PR boundaries and review workload forecast

Review workload forecast: **Chained PRs recommended: Yes**. Even in a clean-slate implementation, the full change touches backend contracts, XLSX parsing, user lifecycle, frontend forms, and tests. A single PR is likely above the 400-line review comfort budget.

Natural PR boundaries:

1. **Backend ticket identity core**
   - sequence bootstrap;
   - numeric ticket generation;
   - create contract rejection;
   - backend tests.
2. **Catalog governance and value streams**
   - catalog fields;
   - dictionary value-stream lookup;
   - service compatibility backend rules;
   - tests.
3. **Assignee and user lifecycle**
   - active-user validation;
   - assignee persistence/snapshots;
   - user logical deactivation behavior;
   - tests.
4. **XLSX import backend**
   - templates;
   - parser/validator architecture;
   - structured errors;
   - atomic repository writes;
   - tests.
5. **Frontend Service Management UI**
   - labels/navigation;
   - ticket/catalog forms;
   - selectors;
   - import UX;
   - frontend tests.

If delivery strategy requires a single PR, record a size exception and run full 4R review before PR.

## Risks

| Risk | Mitigation |
|---|---|
| Neo4j numeric sequence contention | Use one transaction and sequence-node write lock; test concurrent allocation behavior where feasible. |
| `request` vs `service_request` drift | Remove non-canonical values from new contracts and test every API/UI/template seam. |
| Dictionary model mismatch | Keep value-stream lookup behind a dedicated seam so the UI surface can evolve without leaking metric-dictionary assumptions. |
| XLSX parsing edge cases | Use `openpyxl`, explicit headers, visible row numbers, size limits, and parser unit tests. |
| Cross-store user/ticket consistency | Serialize ticket assignment and user deactivation on one PostgreSQL per-user lock held through Neo4j commit; preserve snapshots for later logical deactivation. Process failure between stores requires reconciliation rather than a claimed distributed transaction. |

## Rollout notes

1. Bootstrap initial constraints, value-stream dictionary rows, and the ticket sequence before enabling Service Management writes.
2. Update frontend and API clients together for create payload and numeric response type.
3. Enable catalog create/update validation and ticket compatibility validation from the first writable release.
4. Communicate that bulk imports are atomic: any error rejects the full workbook.
