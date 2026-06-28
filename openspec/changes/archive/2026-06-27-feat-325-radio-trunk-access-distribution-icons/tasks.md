# Tasks: Radio, Trunk, Access, and Distribution Icons

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 100-160 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | auto-forecast |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Extend frontend icon catalog with radio/trunk/access/distribution entries | PR 1 | Frontend-only, additive; tests + impl together; no migration/backfill. |

## Phase 1: Tests first (RED)

- [x] 1.1 RED: Extend `frontend/utils/categoryIcons.test.ts` with failing cases covering the four new keys, English aliases, Spanish aliases, name-inference defaults, and unchanged invalid-key fallback to `generic`.
  _Requirements: ADDED 1, ADDED 2, MODIFIED 1; Scenarios: 1, 2, 3, 4, 5, 6, 7, 8, 9_

## Phase 2: Types and catalog entries (GREEN)

- [x] 2.1 GREEN: Extend the `CategoryIconKey` union in `frontend/types.ts` with `radio_telecom`, `trunk_link`, `access_ci`, `distribution_ci`.
  _Requirements: ADDED 1; Scenarios: 1, 2_
- [x] 2.2 GREEN: Add the four entries to `CATEGORY_ICON_KEY_SET` and `CATEGORY_ICON_CATALOG` in `frontend/utils/categoryIcons.ts` with fixed symbols `settings_input_antenna`, `linear_scale`, `input`, `layers` and English/Spanish aliases; document any justified symbol deviation.
  _Requirements: ADDED 1, ADDED 2; Scenarios: 1, 4, 5_

## Phase 3: Name inference defaults (GREEN)

- [x] 3.1 GREEN: Extend `CATEGORY_NAME_TO_ICON` in `frontend/utils/categoryIcons.ts` with English and Spanish terms for radio, trunk, access, and distribution while preserving existing entries and `generic` fallback.
  _Requirements: MODIFIED 1; Scenarios: 6, 7, 8_

## Phase 4: Verification

- [x] 4.1 Run `cd frontend && corepack pnpm test:run`, confirm the new tests pass, and capture the command output as RED→GREEN evidence (no backend/service changes; no persisted backfill).
  _Requirements: ADDED 1, ADDED 2, MODIFIED 1; Scenarios: 1, 2, 3, 4, 5, 6, 7, 8, 9_

## Commit Boundaries

| Commit | Tasks | Purpose |
|--------|-------|---------|
| 1 | 1.1 | RED: failing tests committed first to record strict-TDD evidence. |
| 2 | 2.1, 2.2, 3.1, 4.1 | GREEN: types, catalog entries, defaults, aliases, and verification evidence in one reviewable work unit (tests + behavior together per `work-unit-commits`). |