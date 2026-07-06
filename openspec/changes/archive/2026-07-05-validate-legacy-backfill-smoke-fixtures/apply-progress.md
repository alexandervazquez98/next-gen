# Apply Progress: Validate Legacy Backfill Smoke Fixtures

## Workload Boundary

- Delivery strategy: ask-on-risk
- Chain strategy: stacked-to-main
- Current slice: PR 3 / Work Unit 3 final evidence and verification
- Base: `origin/main` after PR #366 (`dbd4aad`)
- Branch: `feat/issue-155-smoke-fixtures-pr3`
- Boundary: final OpenSpec evidence docs and verification only; no production code changes, no Docker/new environment, no migration/backfill run, and no `--apply`.
- Explicitly not implemented: none for this slice; PR3 completes remaining Phase 3 and Phase 4 evidence tasks.

## Completed Tasks

- [x] 1.1 Created `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/validate_smoke_fixtures.py` as a local-only runner with run-id generation, seeded fixture plan, and `finally` cleanup.
- [x] 1.2 Seeded marker-scoped `Event` fixtures only in shared local Neo4j using `issue155_smoke=true` and `issue155_smoke_run_id`.
- [x] 1.3 Added post-cleanup verification query proving `MATCH (e:Event {issue155_smoke:true, issue155_smoke_run_id:$run_id}) RETURN count(e)=0`.
- [x] 2.1 Ran `backend/scripts/audit_legacy_event_discriminators.py --report audit --format json` through the harness with explicit local Neo4j environment overrides, kept broad CLI output temporary, and persisted only sanitized smoke-scoped audit JSON evidence.
- [x] 2.2 Validated expected vs actual buckets for safe, ambiguous, and no-touch fixtures by parsing persisted smoke-scoped audit evidence for ambiguous/no-touch findings and directly reusing the read-only classifier for the safe fixture.
- [x] 2.3 Recorded the aggregate recommendation JSON per-fixture isolation gap explicitly in validation evidence.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/test_validate_smoke_fixtures.py` | Unit | N/A (new files) | ✅ Test referenced missing runner first; failed with `FileNotFoundError` | ✅ `python3 .../test_validate_smoke_fixtures.py` passed 4/4 after runner creation | ✅ Added URI and fixture-plan cases | ✅ Reworked Python 3.9-compatible UTC handling |
| 1.2 | `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/test_validate_smoke_fixtures.py` | Unit + local runtime evidence | N/A (new files) | ✅ Fixture plan test required marker/run-id fields before implementation | ✅ Unit tests passed 5/5 and live helper seeded 3 local fixtures | ✅ Fake driver verified seed query receives marked fixtures and live run seeded all three buckets | ✅ Kept seed scope in one query and local URI guard |
| 1.3 | `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/test_validate_smoke_fixtures.py` | Unit + local runtime evidence | N/A (new files) | ✅ Cleanup query test required exact marker/run-id zero-count proof | ✅ Unit tests passed 5/5 and live helper cleanup returned `cleanup_verified=true` | ✅ Fake driver verified cleanup and post-cleanup query order | ✅ Cleanup proof is returned and persisted in JSON evidence |
| 2.1 | `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/test_validate_smoke_fixtures.py` | Unit + local runtime evidence | ✅ 16/16 baseline | ✅ Added tests requiring smoke-scoped audit persistence and no absolute output paths in metadata; failed before implementation | ✅ 24/24 unit tests passed and live helper persisted `pr2-smoke-audit.json` | ✅ Test covers broad temporary CLI output, smoke-only persisted findings, omitted non-smoke count, and sanitized command metadata | ✅ Broad audit output is temporary/non-committed; persisted evidence is smoke-scoped only |
| 2.2 | `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/test_validate_smoke_fixtures.py` | Unit + local runtime evidence | ✅ 16/16 baseline | ✅ Added validation tests requiring persisted audit evidence for ambiguous/no-touch fixtures; failed before implementation | ✅ 24/24 unit tests passed and live validation matched safe/ambiguous/no-touch counts 1/1/1 | ✅ Covered all three buckets plus missing audit-finding invalidation | ✅ Validation summary now separates audit evidence inspection from safe fixture direct-classifier validation |
| 2.3 | `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/test_validate_smoke_fixtures.py` | Unit + local runtime evidence | ✅ 16/16 baseline | ✅ Added cleanup-on-audit-failure and cleanup-on-classifier-failure tests; failed before implementation | ✅ 24/24 unit tests passed and live manifest records `recommendation_gap.status=gap_recorded` | ✅ Failure-path tests prove cleanup still runs after audit generation or classifier validation errors | ✅ Gap wording is centralized in validation summary evidence |

## Test Summary

- Total tests written: 24 cumulative (`+12` in PR2)
- Total tests passing: 24
- Layers used: Unit (24), local shared Neo4j runtime evidence (1 regenerated PR2 run)
- Approval tests: None — no refactoring tasks
- Pure functions created in PR2: `classify_fixture_buckets`, `build_smoke_scoped_audit_evidence`, `build_validation_summary`
- Side-effectful helper added in PR2: `run_audit_json_report` runs the read-only CLI subprocess with the same validated local Neo4j target used by seed/cleanup, parses temporary broad output, and writes sanitized smoke-scoped audit evidence without persisting Neo4j credentials or broad raw-audit counts.

## Runtime Evidence

- Command: `python3 openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/validate_smoke_fixtures.py --output pr2-validation-smoke-<fresh-run-id>.json --audit-json-output pr2-smoke-audit-<fresh-run-id>.json` (use fresh output filenames for every runtime run; existing evidence files are rejected to prevent accidental overwrite).
- Environment source: approved `config/test-env/worktree-host.sample` export path from the root checkout; no denied `.env` file was read.
- Sanitized smoke-scoped audit JSON evidence: `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/pr2-smoke-audit.json`
- Validation manifest: `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/pr2-validation-smoke.json`
- Seeded count: 3 marker-scoped `Event` nodes
- Expected counts: safe candidates = 1, ambiguous records = 1, no-touch records = 1
- Actual direct-classifier counts: safe candidates = 1, ambiguous records = 1, no-touch records = 1
- Validation status: `valid_for_planning=true`, `mismatches=[]`
- Gap recorded: existing aggregate recommendation JSON does not expose per-record smoke fixture IDs; smoke-only validation parses persisted sanitized audit evidence for ambiguous/no-touch fixtures and uses direct classifier reuse for the safe fixture, which has no finding by design.
- Cleanup proof: `cleanup_verified=true`, `remaining_count=0`
- Scope statement: local shared Neo4j only; no production mutation, no production conclusion, no `--apply`, no migration path, and no new Docker/test environment.

## PR3 Final Evidence / Verification

- Completed 3.1 with final Markdown evidence `evidence/pr3-final-evidence-issue155-smoke-pr3-20260705T211426Z.md`, validation manifest `evidence/pr3-validation-smoke-issue155-smoke-pr3-20260705T211426Z.json`, sanitized audit evidence `evidence/pr3-smoke-audit-issue155-smoke-pr3-20260705T211426Z.json`, and failure-safe JSON `evidence/pr3-failure-safe-verification-issue155-smoke-pr3-20260705T211426Z.json`.
- Completed 3.2 with cleanup proof in `evidence/pr3-validation-smoke-issue155-smoke-pr3-20260705T211426Z.json`: `cleanup_verified=true`, `deleted_count=3`, `remaining_count=0`.
- Completed 3.3 with local-only/no-production/no-apply scope statements in the final Markdown and failure-safe JSON evidence.
- Completed 4.1 with focused failure-path unit evidence: audit/report error and classifier/validation error tests prove cleanup and post-cleanup verification execute after failures.
- Completed 4.2 by tying PR3 runtime evidence artifacts to run id `issue155-smoke-pr3-20260705T211426Z` and confirming they are readable JSON/Markdown files.
- Completed 4.3 without production code changes, Docker changes, new test environment files, migration/backfill execution, or `--apply` usage.

### PR3 Runtime Evidence

- Command: `python3 openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/validate_smoke_fixtures.py --run-id issue155-smoke-pr3-20260705T211426Z --output pr3-validation-smoke-issue155-smoke-pr3-20260705T211426Z.json --audit-json-output pr3-smoke-audit-issue155-smoke-pr3-20260705T211426Z.json`
- Environment source: approved root checkout `config/test-env/worktree-host.sample`; no denied `.env` file was read.
- Status: `validation_complete_cleanup_verified`
- Seeded count: 3 marker-scoped `Event` nodes
- Classification result: safe=1, ambiguous=1, no-touch=1, mismatches=[]
- Sanitized audit findings persisted: 6 smoke-scoped findings only
- Cleanup proof: `cleanup_verified=true`, `deleted_count=3`, `remaining_count=0`

### PR3 Verification Commands

- `python3 openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/test_validate_smoke_fixtures.py` → 24 tests passed.
- `python3 -m py_compile openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/validate_smoke_fixtures.py openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/test_validate_smoke_fixtures.py` → passed.
- `git diff --check` → passed.
- Leak grep over PR3 JSON/Markdown evidence for configured absolute-path and credential-token patterns → passed, no matches.

## Remaining Tasks

- None for PR3.

## Deviations

- The sanitized audit JSON contains smoke fixture findings for ambiguous and no-touch fixtures only; safe fixtures naturally have no finding rows. Per-fixture safe validation therefore comes from direct classifier reuse, matching the design's fallback.
- PR2 did not generate Markdown recommendation evidence because Phase 3 evidence/wiring tasks are intentionally out of scope for this work unit.

## Issues

- `config/test-env/worktree-host.sample` was available from the root checkout path, not inside this PR2 worktree.
- The existing audit CLI emits a masked Neo4j debug connection line to stdout; the harness records only `stdout_captured=true`, keeps broad audit output in a temporary file, passes explicit local Neo4j env overrides to the subprocess, and persists sanitized smoke-scoped findings in `pr2-smoke-audit.json`.

## Final PR2 Review Fixes

- Bound the read-only audit subprocess to the same validated local `NEO4J_URI` used by seed/cleanup by passing explicit subprocess environment overrides for the local URI, user, and password values without persisting credentials.
- Kept credentials out of persisted evidence metadata; evidence records only sanitized command/output metadata.
- Removed `raw_total_findings` and broad non-smoke aggregate counts from persisted sanitized audit evidence.
- Updated task/help/progress wording to consistently describe sanitized smoke-scoped audit JSON evidence.
- Surfaced cleanup verification failure (`cleanup_verified=false` / remaining fixtures) ahead of prior audit/classifier errors so leftover local smoke fixtures cannot be hidden by an earlier exception.

## PR1 Review Warning Cleanup

- Restricted `--output` to paths resolving under the change evidence directory and made evidence writes exclusive so existing local files are not overwritten.
- Switched seed/cleanup operations to Neo4j managed write transactions when the installed driver exposes `execute_write`/`write_transaction`, preserving the marker/run-id scoped cleanup query and post-cleanup ordering.
- Converted expected local runtime failures, including missing `neo4j` package, missing password, unsafe output path, and local driver/run failures, into concise `ERROR:` CLI exits instead of tracebacks.

### Warning Cleanup TDD Evidence

| Warning | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|---------|-----------|-------|------------|-----|-------|-------------|----------|
| Evidence output safety | `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/test_validate_smoke_fixtures.py` | Unit | ✅ 7/7 baseline | ✅ Added missing `resolve_evidence_output_path` / `write_json_exclusive` coverage; failed before implementation | ✅ 12/12 passing after implementation | ✅ Covered accepted relative path, traversal/absolute outside rejection, accepted write, and overwrite rejection | ✅ Extracted pure path resolver and exclusive writer |
| Managed cleanup transaction compatibility | `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/test_validate_smoke_fixtures.py` | Unit | ✅ 7/7 baseline | ✅ Fake session exposes managed transaction path while preserving query-order assertions | ✅ 12/12 passing | ✅ Existing seed, cleanup, post-cleanup ordering assertions still prove the transaction path | ✅ Added driver-version fallback helper |
| Concise CLI dependency errors | `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/test_validate_smoke_fixtures.py` | Unit | ✅ 7/7 baseline | ✅ Missing `neo4j` import test required a CLI-oriented error type | ✅ 12/12 passing | ✅ Main now also wraps local driver/run failures into concise `CliError` messages | ✅ Kept direct `run_seed_cleanup` behavior testable without CLI wrapping |
