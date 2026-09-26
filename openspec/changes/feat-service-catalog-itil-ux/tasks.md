# Tasks: feat(service-catalog) ITIL-aligned UX for creation/edit form (#480)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~460 |
| 400-line budget risk | Marginal (slightly over; size exception justification recommended) |
| Chained PRs recommended | No (cohesive UI change) |
| Suggested split | single PR with size exception if needed |
| Delivery strategy | single-pr |
| Files changed | ~7 modified + ~5 new |

```text
Decision needed before apply: yes (canonical category list, service_id format, tier/criticality relationship)
Chained PRs recommended: no
Chain strategy: single-pr
400-line budget risk: marginal (~460 vs 400)
```

## Suggested Work Units

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|----------------------|-----------------|-------------------|
| W1 | All six field UX changes + backend dictionary endpoints + seed + docs | `cd frontend && npx vitest run __tests__/ItsmServiceCatalogPage.test.tsx __tests__/ItsmServiceCatalogPage.itil.test.tsx` `pytest backend/tests/test_dictionaries.py backend/tests/test_itsm_service_catalog_create.py -q` | manual: open service catalog create form, verify each field UX | revert frontend form, backend endpoints, seed, docs |

## Phase 1: Pre-flight

- [x] 1.1 ~~Confirm canonical category list with maintainer~~ — **resolved**: 8 ServiceNow-aligned categories (see proposal)
- [ ] 1.2 Confirm `service_id` auto-gen format
- [ ] 1.3 Confirm `tier`/`criticality` relationship approach (recommend: independent dropdowns with hint)

## Phase 2: Backend changes (RED-GREEN-REFACTOR)

- [ ] 2.1 RED tests in `backend/tests/test_dictionaries.py`: `GET /api/dictionaries?key=value_stream&active=true`, `?key=tier`, `?key=criticality` return expected shapes
- [ ] 2.2 RED tests in `backend/tests/test_itsm_service_catalog_create.py`: `POST /api/itsm/service-catalog` without `service_id` returns 201 with assigned ID; with `service_id` still works
- [ ] 2.3 `backend/routers/dictionaries.py` (or extend): dictionary endpoints
- [ ] 2.4 `backend/services/itsm_imports/value_stream_lookup.py` HTTP wrapper (or extend)
- [ ] 2.5 Modify `POST /api/itsm/service-catalog` to make `service_id` optional; auto-gen using `sc-{slug}-{short-uuid}` or agreed pattern
- [ ] 2.6 `backend/seed_data/metric_dictionary.py` (or equivalent): seed `tier` (`bronze|silver|gold|platinum`) and `criticality` (`low|medium|high|critical`) entries
- [ ] 2.7 GREEN tests; full backend suite green

## Phase 3: Frontend form refactor (RED-GREEN-REFACTOR)

- [ ] 3.1 RED tests in `frontend/__tests__/ItsmServiceCatalogPage.itil.test.tsx`:
  - `service_id` input absent in create form; read-only after save
  - `value_stream` is `<select>` populated from `/api/dictionaries?key=value_stream&active=true`
  - `owner_team` is `<select>` populated from `/api/owners`
  - `category` is `<select>` populated from `/api/categories` with 8 ServiceNow-aligned categories
  - `tier` and `criticality` are `<select>` populated from `/api/dictionaries?key=tier` / `?key=criticality`
  - SLA control is `[number][unit-select]`; default unit is `hours`; converts to minutes on submit
- [ ] 3.2 Extend `frontend/__tests__/ItsmServiceCatalogPage.test.tsx`: no regression for existing tests
- [ ] 3.3 `frontend/components/ItsmServiceCatalogPage.tsx`: refactor lines 311-426 with the six field changes
- [ ] 3.4 Optionally split into `frontend/components/ItsmServiceCatalogPage.fields.tsx` for clarity
- [ ] 3.5 Helper text citations for ITIL guidance per field
- [ ] 3.6 GREEN tests; full frontend suite green

## Phase 4: Docs + cleanup

- [ ] 4.1 `docs/itsm/service-catalog.md` (or extend): ITIL guidance citations, canonical category list, field-to-dictionary mapping
- [ ] 4.2 Verify XLSX import path still validates against the same dictionary sources (regression test or manual)
- [ ] 4.3 Confirm `service_id` PUT path still treats it as the path identifier (unchanged)

## Critical sequencing

- Phase 2 backend changes must precede Phase 3 frontend changes (frontend fetches new endpoints)
- Phase 4 docs can land in same PR or follow-up (low priority)

## Cross-references

- Source proposal: `openspec/changes/feat-service-catalog-itil-ux/proposal.md`
- Backend lookup seam: `backend/services/itsm_imports/value_stream_lookup.py`
- Dictionary endpoints pattern: `backend/routers/dictionaries.py`
- ITIL guidance: documented in Phase 4