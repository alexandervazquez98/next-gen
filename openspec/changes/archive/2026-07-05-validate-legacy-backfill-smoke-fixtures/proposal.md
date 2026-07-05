# Proposal: Validate Legacy Backfill Smoke Fixtures

## Intent

Create a controlled local evidence slice that proves the existing read-only legacy Event backfill recommendation pipeline can inspect known marker-scoped fixtures and classify them into expected buckets before Slice 4 dry-run/apply design.

## Scope

### In Scope
- Seed uniquely marked smoke fixture `Event` records in the existing local/shared Neo4j environment.
- Run the existing read-only recommendation report against those fixtures.
- Validate expected safe, ambiguous, and no-touch classifications across Markdown/JSON evidence.
- Clean up all seeded data, including failure-path cleanup verification.

### Out of Scope
- Production data mutation or production risk conclusions.
- New Docker, test, or isolated Neo4j environments.
- Backfill `--apply`, migrations, or write-capable production code changes.
- Proving scale/performance risk for production.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `legacy-event-backfill-local-evidence`: adds controlled smoke-fixture validation around the existing local read-only evidence report.

## Approach

Use the shared local environment only. Insert marker-scoped fixtures with `issue155_smoke=true` and a unique run id, execute the existing read-only recommendation report, compare actual classifications with expected buckets, persist evidence, and run cleanup in `finally`/trap-style flow. Verify no marked records remain before accepting the slice.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `openspec/specs/legacy-event-backfill-local-evidence/spec.md` | Modified | Add smoke-fixture validation requirements. |
| `openspec/changes/validate-legacy-backfill-smoke-fixtures/` | New | Store proposal, delta spec, design, tasks, and evidence references. |
| Local/shared Neo4j data | Temporary | Seed and remove marker-scoped fixture `Event` records only. |
| Evidence artifacts | New | Record report outputs, expected-vs-actual validation, and cleanup verification. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Seeded data leaks in local DB | Medium | Unique marker/run id plus mandatory cleanup verification. |
| Evidence overstates production confidence | Medium | State explicitly that results validate classifier behavior only. |
| Failure interrupts cleanup | Medium | Require failure-path cleanup and post-cleanup query evidence. |

## Rollback Plan

Delete all records marked with `issue155_smoke=true` and the run id; rerun cleanup verification query. Revert only this change folder if planning artifacts are wrong.

## Dependencies

- Existing shared local Neo4j environment.
- Existing Slice 2/Slice 3 read-only recommendation report.
- No denied secret path reads; configuration must come from already-supported local execution paths.

## Success Criteria

- [ ] Smoke fixtures are seeded with marker and unique run id only in local/shared DB.
- [ ] Read-only report classifies known fixtures into expected buckets.
- [ ] Markdown/JSON evidence records counts, reasons, and validation status.
- [ ] Cleanup verification proves no marked fixture records remain.
- [ ] Output states no production mutation or production-scale conclusion was made.
