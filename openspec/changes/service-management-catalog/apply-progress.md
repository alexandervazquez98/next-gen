# Apply Progress: service-management-catalog

## Status

- Slice: PR 1 backend ticket identity/core contract (`feature-branch-chain`, child targets tracker `feat/service-management-catalog`, issue #401)
- Workload boundary: ~76 production changed lines plus focused tests; intentionally excludes catalog governance, compatibility enforcement beyond existing lookup, assignee locking/lifecycle, XLSX, and frontend work.
- Structured status consumed: `change=service-management-catalog`, `artifactStore=openspec`, `apply=ready`, `nextRecommended=apply`, `allowedEditRoots` limited to this worktree, 5 tasks pending.
- Action-context warning: native status was supplied by the parent; all operations were executed from the isolated worktree.

## Completed tasks

- [x] Work Unit 1 — backend ticket domain contracts and clean-slate identity model. Persisted checkbox updated in `tasks.md`.
- [x] Work Unit 2 — backend sequence allocator and single-ticket generated-ID persistence. Persisted checkbox updated in `tasks.md`.

## Files changed

- `backend/models/itsm.py`
- `backend/repositories/ticket_folio_repo.py`
- `backend/services/ticket_folio_service.py`
- `backend/routers/ticket_folios.py`
- `backend/migrations/itsm_service_catalog.cypher`
- `backend/tests/test_service_management_pr1.py`
- `openspec/changes/service-management-catalog/tasks.md`

## TDD Cycle Evidence

| Task | Test file | Layer | Safety net | RED | GREEN | TRIANGULATE | REFACTOR |
|---|---|---|---|---|---|---|---|
| Work Unit 1 | `backend/tests/test_service_management_pr1.py` | Unit | Not executable: `python` unavailable; `python3` has no pytest | Written first; initially referenced missing response/allocator contracts | Not executable: `python3 -m pytest ...` failed with `No module named pytest` | Added canonical enum negative case and numeric response case | `python3 -m compileall` passed; no behavior refactor run |
| Work Unit 2 | `backend/tests/test_service_management_pr1.py` | Unit/repository seam | Not executable: `python` unavailable; `python3` has no pytest | Written first for generated allocation and missing sequence | Not executable: `python3 -m pytest ...` failed with `No module named pytest` | Covered successful allocation and missing-sequence rollback guard | `python3 -m compileall` and `git diff --check` passed |

## Verification evidence

- `python -m pytest ...`: blocked by environment (`python: command not found`).
- `python3 -m pytest tests/test_service_management_pr1.py -q`: blocked by environment (`No module named pytest`).
- `python3 -m compileall -q ...`: passed.
- `git diff --check`: passed.

## Deviations

- The repository did not provide the configured Python test runtime, so GREEN test execution could not be demonstrated. No dependency installation was performed.
- The focused RED tests were added as a new PR1 test module rather than rewriting the broader legacy lifecycle tests, which remain outside this slice and require contract migration in a later compatibility/test cleanup pass.

## Remaining tasks

- [ ] Work Unit 3 — backend shared active-user locking and logical deactivation.
- [ ] Work Unit 4 — catalog governance and value streams.
- [ ] Work Unit 5 — compatibility enforcement in single-ticket flows.
- [ ] Work Unit 6 — atomic XLSX catalog import stack.
- [ ] Work Unit 7 — atomic XLSX ticket import.
- [ ] Work Unit 8 — frontend Service Management UI.
- [ ] Work Unit 9 — end-to-end compatibility checks and release verification.

## Next recommendation

`verify` after the backend test environment is available. Then continue PR 2 (catalog/value-stream domain) on the tracker chain.

## Environment blocker resolution (continuation)

- Created the ignored local virtual environment `.venv/` with Python 3.11.15; no tracked source files were changed.
- Installed `backend/requirements.txt` and `backend/requirements-dev.txt` successfully into `.venv/`.
- Python 3.9.6 is insufficient for the current backend model annotations: focused collection failed with `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'` for `str | None` in `backend/models/itsm.py`. The repository Dockerfile specifies Python 3.11, which is the minimum runtime used here.
- RED evidence: prior focused run was blocked before collection because the test environment lacked pytest; after environment setup, the Python 3.9 compatibility attempt still failed during collection.
- GREEN evidence: `cd backend && ../.venv/bin/python -m pytest tests/test_service_management_pr1.py -q` passed: 5 tests passed in 3.45s.
- No implementation scope was added, and no commit, push, or PR was created.

## Continuation status

- Persisted task checkboxes unchanged: Work Units 1–2 remain `[x]`; Work Units 3–9 remain `[ ]`.
- Files changed by this continuation: `openspec/changes/service-management-catalog/apply-progress.md` only; ignored `.venv/` is a local environment artifact.
- Remaining tasks are the exact unchecked Work Unit lines listed above.
- Workload / PR boundary: PR1 backend ticket identity/core contract only; this continuation resolved test-environment setup and did not expand the slice.
- Structured status consumed: `changeName=service-management-catalog`, `artifactStore=openspec`, `applyState=ready`, `nextRecommended=apply`, `actionContext.mode=repo-local`, workspace is the isolated PR1 worktree, with no edit-root warning.
- `skill_resolution=paths-injected` (`work-unit-commits` loaded from the parent-provided path).

## PR1 review remediation

- **JD-PR1-001 fixed:** moved `FOR_SERVICE` relation synchronization into the same Neo4j `execute_write` query as sequence allocation and ticket creation. A relation-write exception now rolls back the ticket and sequence increment; no separate post-create synchronization call remains.
- **JD-PR1-002 fixed:** migrated the current PR1 domain, service, and router consumers/tests to numeric response IDs and canonical `incident`/`service_request` values. Client-supplied ticket IDs remain forbidden; deprecated `REQUEST` is not restored.
- Persisted task checkboxes: Work Units 1–2 remain `[x]`; no later catalog, assignment, XLSX, or frontend task was marked complete.

## TDD Cycle Evidence — review remediation

| Finding | RED | GREEN | TRIANGULATE | REFACTOR |
|---|---|---|---|---|
| JD-PR1-001 | Added failure test asserting transactional rollback and relation query participation; it failed because the create query lacked `FOR_SERVICE`. | Added relation merge inside `_CREATE_TICKET_FOLIO_QUERY`; focused failure test passed. | Confirmed sequence/ticket/relation are inside one repository `execute_write`; service no longer invokes a second create-time sync. | Added repository docstring and clarified service transaction comment. |
| JD-PR1-002 | Existing focused consumer/contract suites exposed stale `REQUEST` and client-ID assumptions. | Updated only PR1 ticket consumers/tests/contracts; focused suite passed. | Verified route IDs and response fixtures are numeric and create model fields exclude `ticket_id`. | Kept later catalog/assignment/import/frontend slices untouched. |

## Verification evidence — review remediation

- RED: `cd backend && ../.venv/bin/python3.11 -m pytest tests/test_service_management_pr1.py -q` — 1 failed, 5 passed (expected missing atomic relation assertion).
- GREEN/triangulation: `cd backend && ../.venv/bin/python3.11 -m pytest tests/test_service_management_pr1.py tests/test_itsm_domain_contracts.py tests/test_ticket_folio_service.py tests/test_routers_itsm.py -q` — **43 passed**, 1 deprecation warning.
- Review ledger statuses updated: `JD-PR1-001=fixed`, `JD-PR1-002=fixed` after the passing focused suite.

## Current status after remediation

- Structured status consumed: `schemaName=spec-driven`, `changeName=service-management-catalog`, `artifactStore=openspec`, `applyState=ready`, `dependencies.apply=ready`, `nextRecommended=verify`, `actionContext.mode=repo-local`, workspace is the isolated PR1 worktree, and allowed edit scope is this worktree only.
- Remaining tasks (exact unchecked lines):
  - [ ] Work Unit 3 — backend shared active-user locking and logical deactivation.
  - [ ] Work Unit 4 — catalog governance and value streams.
  - [ ] Work Unit 5 — compatibility enforcement in single-ticket flows.
  - [ ] Work Unit 6 — atomic XLSX catalog import stack.
  - [ ] Work Unit 7 — atomic XLSX ticket import.
  - [ ] Work Unit 8 — frontend Service Management UI.
  - [ ] Work Unit 9 — end-to-end compatibility checks and release verification.
- No commit, push, or PR was created.

## Defensive fix — JD-PR1-001

- **Completed:** Required the referenced `ServiceCatalog` via `MATCH` inside `_CREATE_TICKET_FOLIO_QUERY` before sequence allocation and `TicketFolio` creation; `FOR_SERVICE` is merged in that same Neo4j write transaction.
- **Test added:** `backend/tests/test_service_management_pr1.py::test_repository_rejects_missing_catalog_in_write_transaction_without_persisting_ticket` covers the no-match/race-equivalent path and asserts the query does not use `OPTIONAL MATCH`.
- **TDD evidence:** RED failed against the prior optional-match/error behavior; GREEN passed after the query guard; TRIANGULATE passed with the existing relation-failure rollback test and the full focused PR1 consumer suite; REFACTOR limited to the deterministic combined missing-sequence/catalog error.
- **Persisted task checkboxes:** Work Units 1–2 remain `[x]`; no later work unit is complete or marked.
- **Files changed for this fix:** `backend/repositories/ticket_folio_repo.py`, `backend/tests/test_service_management_pr1.py`, `openspec/changes/service-management-catalog/review-ledger.md`, this file.
- **Verification:** `cd backend && ../.venv/bin/python -m pytest tests/test_service_management_pr1.py tests/test_itsm_domain_contracts.py tests/test_ticket_folio_service.py tests/test_routers_itsm.py -q` — **44 passed**, 1 deprecation warning; `git diff --check` passed.
- **Ledger update:** `JD-PR1-001` updated from `open` to `fixed` only after the passing focused evidence.


## Confirmed product decision — PR1 contract remediation

- **Decision applied:** every ticket must reference an existing active compatible service catalog record; omitted `service_catalog_id` is invalid.
- **Completed implementation:** made `service_catalog_id` required in `TicketFolioCreate`; service validation now rejects missing/inactive/incompatible records; repository matching requires active compatible catalog in the same write transaction before sequence/ticket persistence and relation linking.
- **Tests added/updated:** omitted service ID rejection, missing catalog rejection with no repository call/persistence, valid compatible service creation, same-transaction active/type match assertion, and stale PR1 consumer fixtures.
- **Persisted task checkboxes:** Work Units 1–2 remain `[x]`; no later work unit marked complete.

### TDD Cycle Evidence

| Cycle | RED | GREEN | TRIANGULATE | REFACTOR |
|---|---|---|---|---|
| Required catalog create contract | `backend/tests/test_service_management_pr1.py` failed: omitted `service_catalog_id` did not raise (`1 failed, 8 passed`). | `.venv/bin/python -m pytest backend/tests/test_service_management_pr1.py -q` — 9 passed. | Full focused backend suite — 46 passed; query assertions verify active/type match and no optional catalog match. | Updated domain/router/service fixtures and rejected clearing the required catalog reference on update. |

### Verification evidence

- `cd backend && ../.venv/bin/python -m pytest tests/test_service_management_pr1.py -q` — **9 passed**.
- `cd backend && ../.venv/bin/python -m pytest tests/test_service_management_pr1.py tests/test_itsm_domain_contracts.py tests/test_ticket_folio_service.py tests/test_routers_itsm.py -q` — **46 passed**, 1 deprecation warning.
- `cd backend && ../.venv/bin/python -m compileall -q models repositories services routers tests/test_service_management_pr1.py` — passed.
- `git diff --check` — passed.

### Files changed in this continuation

- `backend/models/itsm.py`
- `backend/services/ticket_folio_service.py`
- `backend/repositories/ticket_folio_repo.py`
- `backend/tests/test_service_management_pr1.py`
- `backend/tests/test_itsm_domain_contracts.py`
- `backend/tests/test_ticket_folio_service.py`
- `backend/tests/test_routers_itsm.py`
- `openspec/changes/service-management-catalog/specs/service-management-catalog/spec.md`
- `openspec/changes/service-management-catalog/design.md`
- `openspec/changes/service-management-catalog/tasks.md`
- `openspec/changes/service-management-catalog/review-ledger.md`

### Scope and remaining work

- Workload / PR boundary remains PR1 backend contract and persistence guard only; no later scope was started.
- Remaining exact unchecked tasks are unchanged: Work Units 3, 4, 5, 6, 7, 8, and 9 in `tasks.md`.
- No commit, push, or PR was created.
- Structured status consumed/produced: `schemaName=spec-driven`, `changeName=service-management-catalog`, `artifactStore=openspec`, `applyState=ready`, `dependencies.apply=ready`, `nextRecommended=verify`, `actionContext.mode=repo-local`, workspace is the isolated PR1 worktree, allowed edit scope is this worktree, warnings none.
- `skill_resolution=paths-injected` (`work-unit-commits` loaded from the parent-provided path).

## Approved PR1 boundary adjustment — completed

- **Boundary:** PR1 now includes only the minimum catalog backend contract required for independently usable compatible ticket creation: persisted/returned immutable `service_type` (`incident` or `service_request`) and `active` status. No value streams, catalog UI, XLSX import, user locking/lifecycle, or frontend work was added.
- **Completed implementation tasks and persisted checkboxes:**
  - [x] PR1 boundary extension — minimum persisted catalog compatibility contract (added to `tasks.md`).
  - Work Units 1–2 remain [x]. Work Units 3–9 remain unchecked.
- **Files changed:** `backend/models/itsm.py`, `backend/repositories/itsm_service_catalog_repo.py`, `backend/services/itsm_service_catalog_service.py`, `backend/tests/test_service_management_pr1.py`, `backend/tests/test_itsm_domain_contracts.py`, `backend/tests/test_itsm_service_catalog_service.py`, `backend/tests/test_routers_itsm.py`, `openspec/changes/service-management-catalog/tasks.md`, `openspec/changes/service-management-catalog/design.md`.
- **Behavior:** catalog create/read/update contracts carry `service_type`; only canonical values validate; update attempts cannot mutate it; catalog `active` is persisted and returned; ticket preflight and same-transaction Neo4j `MATCH` require active compatible persisted catalog data.

### TDD Cycle Evidence

| Boundary task | RED | GREEN | TRIANGULATE | REFACTOR |
|---|---|---|---|---|
| Minimum catalog compatibility contract | Added service/API flow test for catalog creation followed by same-type ticket creation, plus incompatible-type and immutable-type negatives; focused run failed 2 tests before implementation. | Implemented model validation, repository persistence/return fields, immutable update guard, and retained active/type write query; boundary tests passed. | Focused backend suites passed with catalog consumers, ticket service, router contracts, and same-transaction query assertions. | Kept later value-stream, import, locking, and frontend seams untouched; updated existing contract fixtures to canonical service types. |

### Verification evidence

- RED: `cd backend && ../.venv/bin/python3.11 -m pytest tests/test_service_management_pr1.py -q` — **10 passed, 2 failed** before implementation.
- GREEN/triangulation: `cd backend && ../.venv/bin/python3.11 -m pytest tests/test_service_management_pr1.py tests/test_itsm_domain_contracts.py tests/test_itsm_service_catalog_service.py tests/test_ticket_folio_service.py tests/test_routers_itsm.py -q` — **59 passed**, 1 deprecation warning.
- No commit, push, or PR was created.

### Structured status consumed/produced

- `schemaName=spec-driven`; `changeName=service-management-catalog`; `artifactStore=openspec`; authoritative workspace is isolated worktree `/Users/macbook/Library/CloudStorage/OneDrive-SharedLibraries-Onedrive/PROGRAMMING/next-gen/.worktrees/service-management-catalog-pr1`; `actionContext.mode=repo-local`; allowed edit root is this worktree; warnings none.
- `applyState=ready`; `dependencies.apply=ready`; `nextRecommended=verify`.
- Workload boundary is the approved feature-branch-chain PR1 extension; the overall change remains high-risk and later tasks remain separate PR slices.

## Remaining tasks

- [ ] Work Unit 3 — backend shared active-user locking and logical deactivation.
- [ ] Work Unit 4 — catalog governance and value streams.
- [ ] Work Unit 5 — compatibility enforcement in single-ticket flows beyond this minimum contract.
- [ ] Work Unit 6 — atomic XLSX catalog import stack.
- [ ] Work Unit 7 — atomic XLSX ticket import.
- [ ] Work Unit 8 — frontend Service Management UI.
- [ ] Work Unit 9 — end-to-end compatibility checks and release verification.

## PR1 review remediation — JD-PR1-003

- **Completed:** Catalog updates now accept an unchanged immutable `service_type` alongside mutable fields by removing it before repository mutation. Changed `service_type` values still return the existing controlled HTTP 400 validation error.
- **Tests added:** Service-layer positive/negative tests and router-level positive/negative tests cover unchanged and changed values.
- **Files changed:** `backend/services/itsm_service_catalog_service.py`, `backend/tests/test_itsm_service_catalog_service.py`, `backend/tests/test_routers_itsm.py`, `openspec/changes/service-management-catalog/review-ledger.md`, this file.

### TDD Cycle Evidence

| Finding | RED | GREEN | TRIANGULATE | REFACTOR |
|---|---|---|---|---|
| JD-PR1-003 | New service test failed with the uncaught immutable-field rejection for unchanged `service_type`; router test initially exposed missing controlled-error test import. | Implemented unchanged-field stripping; focused service/router tests passed. | Full PR1 focused backend suite passed with changed-type rejection preserved and no repository call for the changed case. | Kept the fix in the service boundary; repository guard remains defensive and later catalog scope is untouched. |

### Verification evidence

- RED: focused service/router tests — 2 failed, 2 passed before implementation/import correction.
- GREEN: focused service/router tests — **4 passed**, 1 deprecation warning.
- TRIANGULATE: `cd backend && ../.venv/bin/python -m pytest tests/test_service_management_pr1.py tests/test_itsm_service_catalog_service.py tests/test_itsm_domain_contracts.py tests/test_ticket_folio_service.py tests/test_routers_itsm.py -q` — **63 passed**, 1 deprecation warning.
- Review ledger `JD-PR1-003` updated from `open` to `fixed` after passing evidence.
- No commit, push, or PR was created.
