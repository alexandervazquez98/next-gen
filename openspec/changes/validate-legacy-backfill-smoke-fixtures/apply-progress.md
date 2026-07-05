# Apply Progress: Validate Legacy Backfill Smoke Fixtures

## Workload Boundary

- Delivery strategy: ask-on-risk
- Chain strategy: stacked-to-main
- Current slice: PR 1 / Work Unit 1 only
- Boundary: local-only seed/cleanup harness from updated `origin/main` / `v1.13.9+`
- Explicitly not implemented: validation/reporting tasks 2.x, 3.x, and 4.x

## Completed Tasks

- [x] 1.1 Created `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/validate_smoke_fixtures.py` as a local-only runner with run-id generation, seeded fixture plan, and `finally` cleanup.
- [x] 1.2 Seeded marker-scoped `Event` fixtures only in shared local Neo4j using `issue155_smoke=true` and `issue155_smoke_run_id`.
- [x] 1.3 Added post-cleanup verification query proving `MATCH (e:Event {issue155_smoke:true, issue155_smoke_run_id:$run_id}) RETURN count(e)=0`.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/test_validate_smoke_fixtures.py` | Unit | N/A (new files) | ✅ Test referenced missing runner first; failed with `FileNotFoundError` | ✅ `python3 .../test_validate_smoke_fixtures.py` passed 4/4 after runner creation | ✅ Added URI and fixture-plan cases | ✅ Reworked Python 3.9-compatible UTC handling |
| 1.2 | `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/test_validate_smoke_fixtures.py` | Unit + local runtime evidence | N/A (new files) | ✅ Fixture plan test required marker/run-id fields before implementation | ✅ Unit tests passed 5/5 and live helper seeded 3 local fixtures | ✅ Fake driver verified seed query receives marked fixtures and live run seeded all three buckets | ✅ Kept seed scope in one query and local URI guard |
| 1.3 | `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/test_validate_smoke_fixtures.py` | Unit + local runtime evidence | N/A (new files) | ✅ Cleanup query test required exact marker/run-id zero-count proof | ✅ Unit tests passed 5/5 and live helper cleanup returned `cleanup_verified=true` | ✅ Fake driver verified cleanup and post-cleanup query order | ✅ Cleanup proof is returned and persisted in JSON evidence |

## Test Summary

- Total tests written: 5
- Total tests passing: 5
- Layers used: Unit (5), local shared Neo4j runtime evidence (1 run)
- Approval tests: None — no refactoring tasks
- Pure functions created: `generate_run_id`, `validate_local_neo4j_uri`, `build_fixture_plan`

## Runtime Evidence

- Command: `python3 openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/validate_smoke_fixtures.py --output openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/pr1-seed-cleanup-smoke.json`
- Environment source: approved `config/test-env/worktree-host.sample` export path from the existing root checkout; no denied `.env` file was read.
- Evidence file: `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/pr1-seed-cleanup-smoke.json`
- Seeded count: 3 marker-scoped `Event` nodes
- Cleanup proof: `cleanup_verified=true`, `remaining_count=0`
- Scope statement: local shared Neo4j only; no production mutation or production conclusion.

## Remaining Tasks

- [ ] 2.1 Run `backend/scripts/audit_legacy_event_discriminators.py --report audit --format json` and persist raw JSON evidence.
- [ ] 2.2 Validate expected vs actual buckets for safe, ambiguous, and no-touch fixtures using audit JSON/direct classifier reuse when CLI lacks per-fixture marker filtering.
- [ ] 2.3 Record the validation gap explicitly if smoke IDs cannot be isolated from aggregate recommendation JSON.
- [ ] 3.1 Persist Markdown and JSON evidence under `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/` for seeded plan, report output, and classification comparison.
- [ ] 3.2 Capture cleanup evidence showing deleted marker-scoped records and zero remaining marked nodes.
- [ ] 3.3 Ensure the run summary states local-only validation, no production mutation, and no `--apply`/migration path.
- [ ] 4.1 Re-run the helper in failure-safe mode to verify `finally`/trap cleanup still executes after a report or validation error.
- [ ] 4.2 Confirm evidence artifacts are complete, readable, and tied to one unique run id.
- [ ] 4.3 Keep the tasks scoped to local/shared Neo4j only; do not add Docker, new test env, or production-write paths.

## Deviations

None — PR1 stayed within the design boundary for seed/cleanup harness safety.

## Issues

- `python` is unavailable in this shell; commands used `python3`.
- `python3 -m pytest` is unavailable because pytest is not installed for the system Python. The committed helper tests use stdlib `unittest` and run directly with `python3`.

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
