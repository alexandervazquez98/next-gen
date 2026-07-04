# Archive Report — feat-325-radio-trunk-access-distribution-icons

## Status

PASS

## Archive date

2026-06-27

## Issue

`alexandervazquez98/next-gen#325` — radio/trunk/access/distribution icon entries for the category technology icon catalog

## Change ID

`feat-325-radio-trunk-access-distribution-icons`

## Modified capability

`category-technology-icons` — `openspec/specs/category-technology-icons/spec.md` (source of truth going forward)

- Modified Requirement: `Initial Technology Defaults` — expanded the default-technologies list from 8 to 12 (added telecom radio, trunk link, access CI, distribution CI); added the constraint that defaults apply via frontend name inference only and MUST NOT require backend/API/schema changes, automatic migration, or persisted category backfill; added an `Existing persisted categories are not backfilled` scenario.
- Added Requirement: `Radio and Network Role Catalog Entries` — three scenarios covering catalog exposure, controlled-key acceptance, and preserved generic fallback.
- Added Requirement: `Bilingual Catalog Discovery` — three scenarios covering English aliases, Spanish aliases, and category-name inference defaults.

All 5 prior requirements are preserved unchanged.

## New capability created

None.

## Out-of-scope items deferred

- Backend/API/schema changes (out of scope per proposal; no migration/backfill).
- Consumer changes (`NetworkVisualizer`, `VisualRelationshipEditor`, `GlobalInventory`, `HardwareCatalog`, `MonitoringConsole`, `CIDetailModal`, `CatalogManager`) — picked up through the shared `CATEGORY_ICON_CATALOG` without consumer-specific changes.
- New CatalogManager sectioning or selector redesign.
- Hardware model, vendor, or instance-level icon overrides.
- Operational status icons, severity indicators, or status color replacement.

## Commits

1. `7b92df308034c006c9a6715377045424bcc26090` — `test(icons): RED add failing cases for radio/trunk/access/distribution keys` (TDD RED, tests-only diff: +94 lines in `frontend/utils/categoryIcons.test.ts`).
2. `f511e76f1301c819de456708a64c1669a4cf8adb` — `feat(icons): add radio/trunk/access/distribution entries with bilingual defaults` (GREEN: 4 entries to `CATEGORY_ICON_CATALOG` + 12 entries to `CATEGORY_NAME_TO_ICON` + extended `normalizeCategoryName` to strip combining diacritics; 52 net lines in `frontend/utils/categoryIcons.ts`, 6 lines in `frontend/types.ts`).
3. (this archive commit) — moves the change folder to `openspec/changes/archive/2026-06-27-feat-325-radio-trunk-access-distribution-icons/`, merges the delta spec into `openspec/specs/category-technology-icons/spec.md`, and includes the 5 checked task checkboxes that were unstaged during verify.

Total implementation diff (HEAD~2..HEAD~1, excluding this archive commit):

```text
frontend/types.ts                    |  6 ++-
frontend/utils/categoryIcons.test.ts | 94 ++++++++++++++++++++++++++++++++++++
frontend/utils/categoryIcons.ts      | 52 ++++++++++++++++++++
3 files changed, 151 insertions(+), 1 deletion(-)
```

Within the forecasted 100–160 changed lines; budget risk Low confirmed.

## Justified implementation deviation (documented)

`normalizeCategoryName` in `frontend/utils/categoryIcons.ts` now strips combining diacritics via Unicode `NFD` + combining-marks removal (`/[\u0300-\u036f]/g`) BEFORE the existing `[^a-z0-9]+` normalization step. Without this change, the spec scenarios for Spanish aliases and Spanish category-name inference did not work for accented input like `Distribución` (the prior code collapsed the accent to a space, producing `"distribuci n"` instead of `"distribucion"`). The change is additive and idempotent — it removes characters that the next step would have replaced with a space anyway, so every existing test still passes (no existing fixture uses accented characters). This is the smallest change that satisfies the spec's literal Spanish examples and is documented in `apply-progress.md` per the proposal's "document any justified deviation" instruction.

Material Symbols match the proposal verbatim — no symbol deviation:

| Key | Required | Implemented | Status |
|-----|----------|-------------|--------|
| `radio_telecom` | `settings_input_antenna` | `settings_input_antenna` | OK |
| `trunk_link` | `linear_scale` | `linear_scale` | OK |
| `access_ci` | `input` | `input` | OK |
| `distribution_ci` | `layers` | `layers` | OK |

## Verification summary

- Apply phase: PASS (RED → GREEN; 57/57 test files, 487/487 tests after GREEN; RED had 6 expected failures in the new `describe` block).
- Verify phase: PASS on second attempt after a corrective documentation-only fix to mark the 5 task checkboxes checked.
- Strict TDD discipline: confirmed via RED commit + GREEN commit split, evidence captured in `apply-progress.md`.
- Spec coverage: all 9 delta scenarios covered by tests in `frontend/utils/categoryIcons.test.ts`.
- Scope discipline: `git diff --name-only HEAD~2..HEAD` shows only `frontend/types.ts`, `frontend/utils/categoryIcons.test.ts`, `frontend/utils/categoryIcons.ts`. No backend, API, schema, migration, or persisted-state file was modified.

## Lessons learned

- **Pre-existing frontend noise is the rule, not the exception.** Both the apply and verify phases had to navigate pre-existing frontend test noise (React `act(...)` warnings, chart sizing, intentionally thrown errors, mocked API error logs) and pre-existing TS errors in `services/api.test.ts`, `app.test.ts`, and `CatalogManager.tsx` (`CategoryIconKey` imported from `../utils/categoryIcons` instead of `../types`). None are caused by this change. **Discipline for future frontend-only changes: capture the baseline once (pre-change full-suite output), then assert "no new noise" rather than "clean output".**
- **Unchecked task checkboxes vs implementation truth.** After GREEN landed, `tasks.md` still showed `- [ ]` for all 5 tasks (sdd-apply had not been re-run to update the persisted artifact, only the code had landed). sdd-verify initially flagged this as CRITICAL. Resolution was a documentation-only checkbox update backed by apply-progress and verify-report proof. **Discipline for sdd-apply: after GREEN, update the persisted `tasks.md` checkboxes as part of the same work-unit commit (or a follow-up chore commit), so verify does not block on stale checkboxes.**
- **`git mv` on an untracked change folder requires `git add` first.** The change folder was untracked when archive started; `git mv` failed with "source directory is empty". Workaround: `git add` the source first to make it tracked, then `git mv` to the archive path. The end state is identical (tracked files at the archive location) but the intermediate step is required.
- **Diacritic normalization is a recurring gotcha for bilingual catalogs.** The `normalizeCategoryName` NFD-strip change is small and obvious in retrospect, but the spec scenarios literally demanded it (Spanish examples `distribución`, `troncal`, `acceso`). **For future bilingual catalog work, treat NFD normalization as table stakes for any catalog that promises Spanish support — and call it out in the proposal as a known normalization step rather than discovering it during apply.**

## Relevant files

- `openspec/specs/category-technology-icons/spec.md` — merged canonical spec (7 requirements; prior 5 preserved + 1 modified + 2 new).
- `openspec/changes/archive/2026-06-27-feat-325-radio-trunk-access-distribution-icons/` — full audit trail (proposal, delta spec, tasks, apply-progress, verify-report, archive-report).
- `frontend/types.ts` — `CategoryIconKey` union extended with the 4 new keys.
- `frontend/utils/categoryIcons.ts` — 4 catalog entries, 12 name-inference defaults, NFD diacritic strip.
- `frontend/utils/categoryIcons.test.ts` — 8 new tests in a dedicated `describe` block covering all 9 delta scenarios.

## Cycle stats

- 8 SDD phases (explore → propose → spec → design → tasks → apply → verify → archive).
- 1 re-run (verify blocked once on stale unchecked task checkboxes, resolved by documentation-only fix).
- 3 commits on the feature branch (2 implementation + 1 archive).
- Total implementation diff (excluding archive): 151 insertions, 1 deletion across 3 files (within the 100–160 forecast).
