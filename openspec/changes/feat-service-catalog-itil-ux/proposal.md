# Proposal: feat(service-catalog) ITIL-aligned UX for creation/edit form (#480)

## Problem

The Service Catalog create/edit form (`frontend/components/ItsmServiceCatalogPage.tsx`, lines 311-426) treats every catalog field except `service_type` and `value_stream` server-validation as **free-text input**. This is misaligned with ITIL Service Portfolio Management guidance (controlled vocabularies, defined ownership, stable identifiers, SLA units that match service hours) and produces inconsistent data that the backend then has to reject with 400s.

The form needs to **guide** the operator into producing valid, ITIL-aligned catalog rows on the first attempt.

## Scope

### Owns

Six field-level changes to the form, all touching the same component and sharing the same fetch-on-mount + render-as-select pattern:

1. **`service_id` auto-generated** — backend mints ID on `POST`; form displays it read-only after creation
2. **`value_stream` dropdown** — sourced from `MetricDictionary {dictionary_key:'value_stream', active:true}`
3. **`owner_team` dropdown** — sourced from `GET /api/owners`
4. **`category` dropdown** — sourced from `GET /api/categories` with canonical ITIL taxonomy
5. **`tier` + `criticality` defined together** — sourced from new `MetricDictionary` entries (`bronze|silver|gold|platinum` and `low|medium|high|critical`); optional derivation logic
6. **SLA unit selector** — segmented control or `<select>` for `minutes | hours | days`; default hours; convert to minutes internally before sending

### Does not own

- Changing the wire format (`sla_target_minutes` stays int; UI converts)
- Bulk XLSX import path (already validates against the same backend dictionaries; inherits changes automatically)
- Migrating existing rows with legacy tier/criticality strings (separate workflow)
- Permission changes (existing catalog permissions apply)
- Server-side validation logic for tier/criticality combinations (optional, deferred)

## Approach

Single PR (estimated ~300-450 LOC, within 400-line budget). Backend adds two thin dictionary endpoints and makes `service_id` optional in the create payload. Frontend refactors the form to render all six fields as constrained controls.

Splitting into six PRs of 20-40 LOC each would multiply review burden for a cohesive UI change.

## Requirements

### From #480

1. `POST /api/itsm/service-catalog` accepts a payload without `service_id` and returns the assigned ID
2. All six fields render as constrained controls (auto-generated read-only, dropdowns, or unit-aware composite)
3. No regression in `tests/components/__tests__/ItsmServiceCatalogPage.test.tsx`
4. XLSX import path still validates against the same dictionary sources
5. Helper text on the form cites the ITIL guidance each control implements

### Functional sub-requirements

- `service_id` auto-gen pattern: `sc-{slug}-{short-uuid}` or `sc-{value_stream}-{nanoid}` (confirm at PR time)
- `value_stream` dropdown pulls from existing `MetricDictionaryValueStreamLookup` via new HTTP wrapper
- `owner_team` dropdown pulls from `GET /api/owners`; empty state surfaces hint to create the group first
- `category` dropdown uses canonical ServiceNow Service Catalog ITIL-aligned taxonomy: `Infrastructure & Platform`, `Application Services`, `End User Computing`, `IT Security`, `Telecommunications`, `Business Services`, `Workspace`, `Consulting & Advisory`; document in helper text and `docs/itsm/service-catalog.md`
- `tier` and `criticality` dropdowns with optional derivation (gold/platinum ⇒ high/critical) or independent dropdowns with a pairing hint
- SLA unit selector: `[number][unit-select]` composite; converts to minutes internally

## Hard constraints

- Wire format `sla_target_minutes: int` unchanged (UI converts)
- XLSX import path unchanged in interface (validates against same backend dictionaries; inherits sources)
- No regression in existing `ItsmServiceCatalogPage.test.tsx`
- Existing permission gates apply (no new permissions required)
- No migration of legacy tier/criticality strings (out of scope)

## Non-goals

- New catalog field types (this is UX, not data model)
- Catalog row versioning (separate workflow)
- Bulk-edit via the form (separate workflow)
- Audit trail enhancements for catalog changes (existing audit surface unchanged)
- SLA escalation policy (separate workflow)

## Affected files (rough)

- modify: `frontend/components/ItsmServiceCatalogPage.tsx` (lines 311-426)
- new: `frontend/components/ItsmServiceCatalogPage.fields.tsx` (sub-components for clarity, optional)
- new: `frontend/__tests__/ItsmServiceCatalogPage.itil.test.tsx`
- modify: `frontend/__tests__/ItsmServiceCatalogPage.test.tsx` (extend existing)
- modify: `backend/routers/itsm_service_catalog.py` (or equivalent) — make `service_id` optional in POST
- new: `backend/routers/dictionaries.py` (or extend existing) — `GET /api/dictionaries?key=value_stream&active=true`, `?key=tier`, `?key=criticality`
- new: `backend/services/itsm_imports/value_stream_lookup.py` HTTP wrapper (or extend existing)
- modify: `backend/seed_data/metric_dictionary.py` (or equivalent) — seed `tier` and `criticality` entries
- new: `docs/itsm/service-catalog.md` (or extend existing) — ITIL guidance citations

## Estimated footprint

| Area | LOC estimate |
|---|---|
| Frontend form refactor | ~250 |
| Frontend tests | ~50 (new) + ~30 (extension) |
| Backend endpoint additions | ~80 |
| Backend seed extensions | ~30 |
| Docs | ~20 |
| **Total** | **~460** |

Single PR, within 400-line review budget (with size exception justification if needed).

## Open decisions for the maintainer

1. ~~Canonical category list~~ — **resolved**: 8 ServiceNow-aligned categories: `Infrastructure & Platform`, `Application Services`, `End User Computing`, `IT Security`, `Telecommunications`, `Business Services`, `Workspace`, `Consulting & Advisory`. Seed in `backend/seed_data/itsm_categories.py` (or extend existing seed) and expose via `GET /api/categories`.
2. **`service_id` format** — `sc-{slug}-{short-uuid}` vs `sc-{value_stream}-{nanoid}` vs other pattern. Confirm at PR time.
3. **`tier`/`criticality` relationship** — derivation (gold/platinum ⇒ high/critical) vs independent dropdowns with hint. Recommend independent dropdowns with hint (less opinionated, easier to evolve).
4. **Validation for contradictory combinations** — add server-side validation that warns on `tier='Gold'` + `criticality='Low'`? Recommend deferring (out of scope per issue body).