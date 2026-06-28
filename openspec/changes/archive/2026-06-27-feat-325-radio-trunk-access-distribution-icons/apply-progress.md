# Apply Progress: feat-325-radio-trunk-access-distribution-icons

## Change summary

Extends the controlled frontend category icon catalog with four new entries — `radio_telecom`, `trunk_link`, `access_ci`, `distribution_ci` — so operators can distinguish telecom radios, trunk links, access CIs, and distribution CIs across existing shared icon consumers. Spanish and English aliases are added; category-name inference defaults resolve to the new keys; the `generic` fallback for unknown keys is preserved unchanged. No backend, schema, API, or persisted-data changes; no automatic backfill.

## Workload / PR Boundary

- Mode: **single PR** (auto-forecast, 100–160 lines, budget risk Low)
- Chain strategy: not applicable
- Size exception: not needed

## Commit shape (work-unit-commits)

| # | SHA       | Subject |
|---|-----------|---------|
| 1 (RED)   | `7b92df308034c006c9a6715377045424bcc26090` | `test(icons): RED add failing cases for radio/trunk/access/distribution keys` |
| 2 (GREEN) | `f511e76f1301c819de456708a64c1669a4cf8adb` | `feat(icons): add radio/trunk/access/distribution entries with bilingual defaults` |

Commit 1 contains only the failing tests (no implementation). Commit 2 contains the implementation plus the now-passing test run captured in this artifact, per `work-unit-commits` discipline.

## Files changed

| Path | Action | What changed |
|------|--------|--------------|
| `frontend/types.ts` | Modified | Extended `CategoryIconKey` union with `radio_telecom`, `trunk_link`, `access_ci`, `distribution_ci`. |
| `frontend/utils/categoryIcons.ts` | Modified | Added 4 entries to `CATEGORY_ICON_KEY_SET`, `CATEGORY_ICON_CATALOG` (with bilingual aliases) and 12 entries to `CATEGORY_NAME_TO_ICON`. Extended `normalizeCategoryName` to strip combining diacritics (NFD) so accented Spanish input matches its ASCII dictionary form. |
| `frontend/utils/categoryIcons.test.ts` | Modified | Added 8 tests in a new `describe` block covering scenarios 1–9 from `specs/category-technology-icons/spec.md`. |

No other files modified. Consumers (`NetworkVisualizer`, `VisualRelationshipEditor`, `GlobalInventory`, `HardwareCatalog`, `MonitoringConsole`, `CIDetailModal`, `CatalogManager`) were NOT touched because the new entries are picked up through the shared `CATEGORY_ICON_CATALOG` without any consumer-specific change.

## TDD Cycle Evidence

Per `openspec/config.yaml` (`sdd.strict_tdd.test_first_required: true`) the project enforces strict TDD. Test command: `cd frontend && corepack pnpm test:run`.

### Task 1.1 — RED

- [x] 1.1 RED: Extend `frontend/utils/categoryIcons.test.ts` with failing cases covering the four new keys, English aliases, Spanish aliases, name-inference defaults, and unchanged invalid-key fallback to `generic`.

**Command**: `cd frontend && corepack pnpm test:run`

**Outcome**: 1 test file failed, 56 passed (57 total). 6 tests failed, 481 passed (487 total).

The 6 new tests that failed (in `categoryIcons.test.ts > categoryIcons — radio/trunk/access/distribution entries`):

1. `exposes the four new keys in the catalog with non-empty fixed Material Symbols` — `expected undefined to be defined` (catalog does not yet contain `radio_telecom` etc.).
2. `accepts the four new keys as controlled category icon keys` — `expected false to be true` (`isCategoryIconKey("radio_telecom")` returned false).
3. `finds each new entry by English search terms` — `expected [] to include 'radio_telecom'` for query `"radio"`.
4. `finds each new entry by Spanish search terms` — same shape with `"distribución"` query.
5. `infers default icon key from English category names` — `expected 'generic' to be 'radio_telecom'` for `categoryName: "Radio"`.
6. `infers default icon key from Spanish category names` — `expected 'generic' to be 'distribution_ci'` for `categoryName: "Distribución"`.

The 2 new tests that PASSED in the RED state (proving the fallback contract is preserved):

7. `falls back to generic for invalid icon keys even after the new entries exist` — pre-existing fallback behavior, unchanged.
8. `keeps unsupported names falling back to generic` — pre-existing fallback behavior, unchanged.

Final tail of RED run:

```
Test Files  1 failed | 56 passed (57)
     Tests  6 failed | 481 passed (487)
```

Captured in `/tmp/red_output.txt` (full output retained for the verify phase).

### Tasks 2.1, 2.2, 3.1 — GREEN

- [x] 2.1 GREEN: Extended `CategoryIconKey` in `frontend/types.ts` with the four new keys.
- [x] 2.2 GREEN: Added entries to `CATEGORY_ICON_KEY_SET` and `CATEGORY_ICON_CATALOG` with the fixed symbols `settings_input_antenna`, `linear_scale`, `input`, `layers` and bilingual aliases; no symbol deviation to document.
- [x] 3.1 GREEN: Extended `CATEGORY_NAME_TO_ICON` with English and Spanish terms for radio, trunk, access, and distribution while preserving existing entries and `generic` fallback.

### Task 4.1 — Verify

- [x] 4.1 Run `cd frontend && corepack pnpm test:run`, confirm GREEN, capture command output.

**Command**: `cd frontend && corepack pnpm test:run`

**Outcome**: 0 failed. 57 test files passed, 487 tests passed (479 original + 8 new).

Final tail of GREEN run:

```
Test Files  57 passed (57)
     Tests  487 passed (487)
```

`frontend/utils/categoryIcons.test.ts` itself: 1 file passed, 14 tests passed (6 original + 8 new).

**Other quality gates**:

- `corepack pnpm exec eslint frontend/types.ts frontend/utils/categoryIcons.ts` — 0 errors, 1 warning. The warning is the pre-existing `metadata: Record<string, any>` in `frontend/types.ts:53` (out of scope for this change).
- `corepack pnpm exec tsc --noEmit` — pre-existing TS errors only (`BroadcastChannel`, `Response`, `Location` in `services/api.test.ts` and `app.test.ts`; unrelated to this change). The only TS error mentioning `categoryIcons` is the pre-existing `CatalogManager.tsx:5` importing `CategoryIconKey` from `../utils/categoryIcons` (should be `../types`) — not introduced by this change.

## Deviations from task list

The proposal mandates fixed Material Symbols exactly:

| Key | Required symbol | Used | Deviation? |
|-----|-----------------|------|------------|
| `radio_telecom` | `settings_input_antenna` | `settings_input_antenna` | None |
| `trunk_link` | `linear_scale` | `linear_scale` | None |
| `access_ci` | `input` | `input` | None |
| `distribution_ci` | `layers` | `layers` | None |

**One justified implementation change** beyond the literal task list, documented per the proposal's "document any justified deviation" instruction:

- `normalizeCategoryName` now strips combining diacritics via Unicode `NFD` + combining-marks removal (`/[\u0300-\u036f]/g`) BEFORE the existing `[^a-z0-9]+` regex. Without this, the spec scenario "Spanish aliases find each new entry" and "Category names infer new defaults" do not work for accented Spanish input like `Distribución` (the previous code dropped the accent to a space, producing `"distribuci n"` instead of `"distribucion"`). The change is additive: it removes characters that the next step would have replaced with a space anyway, so every existing test still passes (no existing fixture uses accented characters). This is the smallest change that satisfies the spec's literal Spanish examples.

## Spec coverage

| Scenario | Spec wording | Covered by |
|----------|--------------|------------|
| 1 | Catalog exposes the four new keys (non-empty Material Symbol) | `exposes the four new keys in the catalog with non-empty fixed Material Symbols` |
| 2 | New keys are accepted as controlled keys | `accepts the four new keys as controlled category icon keys` |
| 3 | Existing invalid-key fallback remains unchanged | `falls back to generic for invalid icon keys even after the new entries exist` |
| 4 | English aliases find each new entry | `finds each new entry by English search terms` |
| 5 | Spanish aliases find each new entry | `finds each new entry by Spanish search terms` |
| 6 | Category names infer new defaults | `infers default icon key from English category names` + `infers default icon key from Spanish category names` |
| 7 | Known technology receives default icon (existing entries preserved) | `keeps unsupported names falling back to generic` (negative case) + pre-existing tests still pass |
| 8 | Existing category without mapping uses generic icon | `keeps unsupported names falling back to generic` |
| 9 | Existing persisted categories are not backfilled (constraint) | Verified structurally: there is no migration/backfill code path. `resolveCategoryIconKey` only INFERs from names; it never persists. |

## Outstanding risks for the verify phase

1. **Pre-existing frontend flakiness** — `components/MetricsManager.test.tsx` had a flaky test (`apiGet` called 2 times instead of 1) when running the full suite, but passes in isolation and passes when the full suite is rerun. This is pre-existing and unrelated to this change; do not fail the verify phase on it.
2. **Pre-existing TS/lint noise** — there are 279 pre-existing lint errors and several pre-existing `tsc --noEmit` errors in `services/api.test.ts`, `app.test.ts`, etc. None are caused by this change. `CatalogManager.tsx:5` imports `CategoryIconKey` from the wrong module — pre-existing.
3. **Consumer smoke check** — although the task says not to touch consumers unless a test reveals a regression, the verify phase should still run the existing `CategoryIcon.test.tsx`, `NetworkVisualizer.test.tsx`, `CIDetailModal.test.tsx`, `DependencyMiniMap.test.tsx` and confirm no regression in shared-icon rendering. They all PASS in the captured GREEN run.
4. **Material Symbol name verification** — proposal risk row "Material Symbol name mismatch" should be verified by rendering each new icon in a browser (out of scope for the verify test command). The symbol names used (`settings_input_antenna`, `linear_scale`, `input`, `layers`) are all standard Material Symbols and match the proposal verbatim.

## Test command outputs (full)

- RED: `/tmp/red_output.txt`
- GREEN: `/tmp/green_final3.txt`
