# Tasks: Validate Legacy Backfill Smoke Fixtures

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 500-800 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 evidence helper + seed/cleanup, PR 2 validation reports + evidence, PR 3 docs/cleanup |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Local-only seed/cleanup harness | PR 1 | Base from main; isolates marker-scoped fixtures and trap cleanup. |
| 2 | Per-fixture validation and evidence output | PR 2 | Base on PR 1; uses audit JSON/direct classifier reuse for smoke IDs. |
| 3 | Final evidence docs and verification | PR 3 | Base on PR 2; captures zero-marked-record proof and run summary. |

## Phase 1: Foundation / Harness

- [x] 1.1 Create `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/validate_smoke_fixtures.py` as a local-only runner with run-id generation, seeded fixture plan, and cleanup trap/finally.
- [x] 1.2 Seed marker-scoped `Event` fixtures only in shared local Neo4j using `issue155_smoke=true` and `issue155_smoke_run_id`.
- [x] 1.3 Add a post-cleanup query that proves `MATCH (e:Event {issue155_smoke:true, issue155_smoke_run_id:$run_id}) RETURN count(e)=0`.

## Phase 2: Validation Logic

- [x] 2.1 Run `backend/scripts/audit_legacy_event_discriminators.py --report audit --format json` and persist sanitized smoke-scoped audit JSON evidence.
- [x] 2.2 Validate expected vs actual buckets for safe, ambiguous, and no-touch fixtures using audit JSON/direct classifier reuse when CLI lacks per-fixture marker filtering.
- [x] 2.3 Record the validation gap explicitly if smoke IDs cannot be isolated from aggregate recommendation JSON.

## Phase 3: Evidence / Wiring

- [x] 3.1 Persist Markdown and JSON evidence under `openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/` for seeded plan, report output, and classification comparison.
- [x] 3.2 Capture cleanup evidence showing deleted marker-scoped records and zero remaining marked nodes.
- [x] 3.3 Ensure the run summary states local-only validation, no production mutation, and no `--apply`/migration path.

## Phase 4: Verification / Cleanup

- [x] 4.1 Re-run the helper in failure-safe mode to verify `finally`/trap cleanup still executes after a report or validation error.
- [x] 4.2 Confirm evidence artifacts are complete, readable, and tied to one unique run id.
- [x] 4.3 Keep the tasks scoped to local/shared Neo4j only; do not add Docker, new test env, or production-write paths.
