# Archive Report: fix-416-event-amplification-p2

## Final Status

**BLOCKED — archive not performed.** The mandatory native review receipt gate is absent: no structured status with `reviewGate.result: allow` was supplied, and no review transaction, frozen ledger, approved terminal receipt, or post-apply gate context could be found for this change. Per the archive policy, no canonical-spec mutation or change-folder move was performed.

## Executive Summary

The implementation evidence reports 9/9 requirements, 10/10 scenarios, and 17/17 completed tasks. The delta and canonical specifications have semantic parity for REQ-001 through REQ-009 and SCN-001 through SCN-010; their differences are representational and editorial, including the delta title/section prefixes and the canonical full-spec framing. The branch contains 19 local commits: 12 original implementation/artifact commits and 7 remediation commits. Archiving remains blocked until the native review receipt gate is valid; `proposal.md` is also missing and requires explicit intentional-partial-archive approval. The requested `2026-07-30` archive prefix conflicts with the current date (`2026-08-01`) and the archive convention requiring today's ISO date.

## Commits Recorded

| Sequence | Hash | Subject |
|---|---|---|
| A | `beb01c7` | feat(api): expose affected_ci_ids and affected_count on EventFeedSummary |
| B | `5c0c304` | feat(api): filter get_events by include_children flag |
| C | `af70db2` | feat(api): add affected-CI drill-down endpoint |
| D | `92d6f80` | fix(ai-chat): preserve raw event rows in chat context |
| E | `18f4d23` | feat(queries): thread include_children through event query keys |
| F | `5ac6f3d` | feat(correlation): include CONNECTS_TO in upstream grouping |
| G | `e9add77` | feat(monitoring): surface root events and affecting-CIs count |
| H | `032ec0e` | test(monitoring): align smoke mocks with root-only api contract |
| I | `411d90a` | test(e2e): add monitoring KPI drill-down playwright spec |
| J | `f361ca4` | docs(changelog): note p2 event root exposure breaking default |
| K | `4feef87` | style(backend): apply black formatting |
| L | `06ca3af` | docs(apply): record p2 progress and budget state |
| R1 | `594f829` | fix(api): exclude none fields from /events response (REQ-001) |
| R2 | `f01a8e2` | test(events): strengthen scn-001 root-only filter fixture |
| R3 | `6d33440` | test(queries): assert simultaneous include_children cache isolation (scn-007) |
| R4 | `804dc11` | docs(tasks): reconcile p2 task checkboxes with apply progress |
| R5 | `32df8a8` | refactor(frontend): remove orphaned useAffectedCIsQuery hook |
| R6 | `6dabb4b` | test(correlation): fix ts errors in useEventCorrelation.test |
| R7 | `3a0563a` | fix(test): align sparse-event assertions with exclude_none contract |

The launch context describes the original commits as both “12 originals” and “A–M”; A–M would be 13 entries. Git history is authoritative: 12 original commits plus 7 remediation commits equals 19 total.

## Final Metrics

| Metric | Value |
|---|---:|
| Files changed | 24 |
| Insertions | 1580 |
| Deletions | 42 |
| Backend full-suite tests passed | 1779 |
| Backend full-suite tests failed | 6 (pre-existing on `main`) |
| Frontend tests passed | 575 |
| Frontend tests failed | 0 |
| Combined non-duplicated full-suite tests passed | 2354 |
| Combined full-suite tests failed | 6 |
| New failures attributable to P2 | 0 |
| Requirements covered | 9/9 |
| Scenarios covered | 10/10 |
| Tasks complete | 17/17 |

Focused backend evidence additionally reports 116 passing P2-surface tests; these are a subset of the backend full-suite total and are not double-counted above. The Playwright E2E spec was not executed locally because Docker was unavailable.

## Specification Sync Assessment

- Delta: `openspec/changes/fix-416-event-amplification-p2/specs/event-root-affected-exposure/spec.md`
- Canonical: `openspec/specs/event-root-affected-exposure/spec.md`
- Requirement parity: 9/9
- Scenario parity: 10/10
- Canonical mutation: none required and none performed
- Cosmetic/editorial differences: the delta uses `# Delta for ...`, `## ADDED Requirements`, and `### Requirement: REQ-... — ...`; the canonical uses a full-spec title, Purpose section, `## Requirements`, and `### REQ-...: ...`. The canonical also contains fuller wording and examples while preserving the same normative coverage.

## Breaking Change

`GET /api/events` now defaults to ROOT-only results (`include_children=false`). Consumers that require the previous raw ROOT + PROPAGATED set must opt in with `?include_children=true`; this mitigation is documented under `[Unreleased]` in `CHANGELOG.md`.

## Residual Limitations

- **P1**: legacy in-process collector parity remains out of scope.
- **P3**: leased queue writer parity, topology backfill, AP parent synthesis, and relationship remediation remain out of scope.

## Open Follow-ups

- Add a property-style idempotency test that performs two consecutive `get_affected_siblings` calls in the same deterministic mock Neo4j context.
- Re-run the focused backend suite in CI before merge to confirm the six infrastructure failures remain baseline-only.
- Consider a defensive `RemovedInV3` warning when `affected_ci_ids` appears on a non-ROOT response row.
- Run `frontend/test/e2e/monitoring-event-kpi.spec.ts` in CI where Docker is available.

## Archive Blockers

1. Missing structured `reviewGate.result: allow`.
2. Missing review transaction, frozen ledger, approved terminal receipt, and post-apply gate context.
3. Missing `proposal.md`; continuing requires explicit intentional partial-archive approval recorded in the final report.
4. Archive date conflict: requested path uses `2026-07-30`, while the current date and mandatory convention require `2026-08-01`.
5. The worktree was already dirty before this archive attempt (`frontend/test-results/` and untracked OpenSpec artifacts). A clean `git status --porcelain` cannot be guaranteed without cleanup and/or a commit, neither of which was authorized for unrelated paths.

## Operations Performed

- Created this blocked archive report in the active change folder.
- Did not modify application code.
- Did not alter the canonical spec.
- Did not move the change folder.
- Did not delete `apply-progress.md`.
- Did not create a PR, push, rewrite, or delete commits.
