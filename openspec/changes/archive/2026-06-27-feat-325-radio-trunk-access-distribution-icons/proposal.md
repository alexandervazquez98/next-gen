# Proposal: Radio, Trunk, Access, and Distribution Icons

## Intent

Extend the existing category technology icon catalog so operators can distinguish telecom radios, trunk links, access CIs, and distribution CIs across existing icon consumers. This is frontend-only, preserves current metadata, and avoids automatic backfill.

## Scope

### In Scope
- Add `radio_telecom`, `trunk_link`, `access_ci`, `distribution_ci` to the catalog and `CategoryIconKey`.
- Use fixed symbols: `settings_input_antenna`, `linear_scale`, `input`, `layers`; justify any documented deviation.
- Add Spanish/English aliases and default name matching.
- Add tests first in `frontend/utils/categoryIcons.test.ts`.

### Out of Scope
- Backend/API/schema changes or automatic migration/backfill.
- New CatalogManager sectioning or selector redesign.
- Consumer changes unless tests reveal a regression.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `category-technology-icons`: expand the controlled frontend icon catalog while preserving fallback, search, and shared rendering.

## Approach

Follow the archived `category-technology-icons` pattern: update types and catalog only; existing `CategoryIcon` consumers pick up entries. Required test command: `cd frontend && corepack pnpm test:run`. Later phases must record tests-first evidence: failing tests → implementation → passing command.

Add test cases for:
- catalog has all four keys with non-empty fixed symbols;
- `isCategoryIconKey` accepts them;
- `resolveCategoryIconKey` maps Spanish/English radio, trunk, access, distribution names;
- `findCategoryIcons` finds each by key, label, Spanish alias, English alias;
- invalid keys still fall back to `generic` or name inference.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `frontend/types.ts` | Modified | Extend `CategoryIconKey`. |
| `frontend/utils/categoryIcons.ts` | Modified | Add entries, aliases, key set, defaults. |
| `frontend/utils/categoryIcons.test.ts` | Modified | Tests-first coverage. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Broad aliases select wrong icon | Med | Add explicit bilingual tests and keep terms role-specific. |
| Material Symbol name mismatch | Low | Verify rendered catalog symbols during implementation; document any justified deviation. |
| Existing categories change icon | Low | No migration/backfill; only new/admin-edited categories use new keys. |

## Rollback Plan

Revert the three frontend file changes. Existing `icon_key` values remain untouched; unknown keys fall back to `generic`.

## Dependencies

- GitHub issue #325.
- Existing `category-technology-icons` capability.
- Strict TDD: `sdd.strict_tdd.test_first_required: true`.

## Success Criteria

- [ ] Four new icon keys are available in the selector flat list.
- [ ] Spanish and English searches/default mappings resolve the expected entries.
- [ ] Existing shared icon consumers render without regression.
- [ ] `cd frontend && corepack pnpm test:run` passes with tests-first evidence.
