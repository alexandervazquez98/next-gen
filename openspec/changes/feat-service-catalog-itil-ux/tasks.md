# Tasks: feat(service-catalog) ITIL-aligned UX for creation/edit form (#480)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | Actual: ~5,173 authored changed lines across three work-unit commits |
| 400-line budget risk | High — maintainer explicitly approved a single-PR size exception |
| Chained PRs recommended | No — cohesive feature; exception accepted instead |
| Suggested split | single PR with three coherent work-unit commits |
| Delivery strategy | single-pr |
| Files changed | 34 tracked + 8 new (excluding the untracked ODD document) |

```text
Decision needed before apply: no — decisions resolved and single-PR size exception explicitly approved
Chained PRs recommended: no (override accepted by maintainer)
Chain strategy: not applicable
400-line budget risk: high (~5,173 vs 400; size exception approved)
```

## Suggested Work Units

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|----------------------|-----------------|-------------------|
| W1 | All six field UX changes + backend dictionary endpoints + seed + docs | `cd frontend && npx vitest run __tests__/ItsmServiceCatalogPage.test.tsx __tests__/ItsmServiceCatalogPage.itil.test.tsx` `pytest backend/tests/test_dictionaries.py backend/tests/test_itsm_service_catalog_create.py -q` | manual: open service catalog create form, verify each field UX | revert frontend form, backend endpoints, seed, docs |

## Phase 1: Pre-flight

- [x] 1.1 ~~Confirm canonical category list with maintainer~~ — **resolved**: 8 ServiceNow-aligned categories (see proposal)
- [x] 1.2 Confirm `service_id` auto-gen format — `sc-{value_stream_slug|name_slug}-{nanoid}`, maximum 20 characters
- [x] 1.3 Confirm `tier`/`criticality` relationship approach — independent dropdowns with a recommended-pairing matrix; no server-side derivation

## Phase 2: Backend changes (RED-GREEN-REFACTOR)

- [x] 2.1 RED tests in `backend/tests/test_dictionaries.py`: `GET /api/dictionaries?key=value_stream&active=true`, `?key=tier`, `?key=criticality` return expected shapes
- [x] 2.2 RED tests across service/repository/router suites: `POST /api/itsm/service-catalog` without `service_id` returns 201 with assigned ID; with `service_id` still works
- [x] 2.3 `backend/routers/dictionaries.py` (or extend): dictionary endpoints
- [x] 2.4 `backend/services/itsm_imports/value_stream_lookup.py` HTTP wrapper (or extend)
- [x] 2.5 Modify `POST /api/itsm/service-catalog` to make `service_id` optional; auto-gen using `sc-{slug}-{nanoid}`
- [x] 2.6 `backend/services/itsm_imports/seed_data.py`: seed `tier` (`bronze|silver|gold|platinum`) and `criticality` (`low|medium|high|critical`) entries
- [x] 2.7 GREEN tests; full backend suite: 2,595 passed, 2 skipped, 4 Docker-only writer-advisory-lock failures

## Phase 3: Frontend form refactor (RED-GREEN-REFACTOR)

- [x] 3.1 RED tests in `frontend/components/__tests__/ItsmServiceCatalogPage.itil.test.tsx`:
  - `service_id` input absent in create form; read-only after save
  - `value_stream` is `<select>` populated from `/api/dictionaries?key=value_stream&active=true`
  - `owner_team` is `<select>` populated from `/api/owners`
  - `category` is `<select>` populated from `/api/categories` with 8 ServiceNow-aligned categories
  - `tier` and `criticality` are `<select>` populated from `/api/dictionaries?key=tier` / `?key=criticality`
  - SLA control is `[number][unit-select]`; default unit is `hours`; converts to minutes on submit
- [x] 3.2 Extend `frontend/components/__tests__/ItsmServiceCatalogPage.test.tsx`: no regression for existing tests
- [x] 3.3 `frontend/components/ItsmServiceCatalogPage.tsx`: refactor the create/edit form with the six field changes
- [x] 3.4 Keep the cohesive form in one component; no split was needed
- [x] 3.5 Helper text citations for ITIL guidance per field
- [x] 3.6 GREEN tests; full frontend suite green (101 files, 905 tests)

## Phase 4: Docs + cleanup

- [x] 4.1 `docs/itsm/service-catalog.md`: ITIL guidance, canonical category list, field-to-dictionary mapping, HTTP contract, SLA conversion, and import behavior
- [x] 4.2 Verify XLSX import path still validates against the same dictionary sources (regression tests cover missing optional columns plus valid/invalid tier and criticality)
- [x] 4.3 Confirm `service_id` PUT path still treats it as the path identifier (unchanged)

## Implementation Evidence

- W1 — `0efd8b4 feat(backend): govern Service Catalog vocabularies (#480)`: managed dictionary endpoint, canonical category seed, tier/criticality startup seed, and XLSX dictionary validation with tests. Isolated commit check: 116 focused tests passed.
- W2 — `a24907f feat(backend): mint Service Catalog IDs on create (#480)`: optional create ID, server minting, create-only collision safety, HTTP 201, and compatibility regressions. Isolated commit check: 282 focused tests passed.
- W3 — `c828799 feat(frontend): apply ITIL Service Catalog controls (#480)`: controlled inputs, assigned-ID display, SLA unit conversion, Dictionary deep link, tests, docs, and changelog. Isolated commit check: 44 focused tests passed.
- Full frontend suite: 101 files, 905 tests passed.
- Full backend suite: 2,595 passed, 2 skipped; 4 writer-advisory-lock tests require an unavailable Docker daemon and are unrelated to this change.
- Base-vs-candidate differential verification: PASS; all semantic differences map to S1-S6, with no unrequested regression found.
- Review workload: ~5,173 authored changed lines. The maintainer explicitly approved the single-PR size exception.

## Critical sequencing

- Phase 2 backend changes must precede Phase 3 frontend changes (frontend fetches new endpoints)
- Phase 4 docs can land in same PR or follow-up (low priority)

## Cross-references

- Source proposal: `openspec/changes/feat-service-catalog-itil-ux/proposal.md`
- Backend lookup seam: `backend/services/itsm_imports/value_stream_lookup.py`
- Dictionary endpoints pattern: `backend/routers/dictionaries.py`
- ITIL guidance: documented in Phase 4