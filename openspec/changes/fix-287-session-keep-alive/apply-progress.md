# Apply Progress: fix-287-session-keep-alive — PR0 (`fix/287-db-backfill`)

**Branch**: `fix/287-db-backfill`
**PR**: https://github.com/alexandervazquez98/next-gen/pull/289
**Base branch**: `fix/287-session-keep-alive` (tracker, `feature-branch-chain`)
**Strict TDD mode**: enabled
**Linked issue**: Part of `alexandervazquez98/next-gen#287` (Bug 1 + Bug 2 stay open for PR1/PR2)

---

## Slice Status

**PR0 (`fix/287-db-backfill`) — COMPLETE**

### Completed Tasks

- [x] **Task 0.1** — `test(auth): define refresh token activity backfill contract`
  - Commit: `b85aa36`
  - Files: `backend/tests/test_refresh_token_activity_backfill.py` (new, 75 LOC)
  - RED: 2 tests failed with `ImportError` for missing `backfill_refresh_token_activity` (confirmed via `uv run pytest`).

- [x] **Task 0.2** — `fix(auth): add batched refresh token activity backfill`
  - Commit: `f6f6801`
  - Files: `backend/scripts/backfill_refresh_token_activity.py` (new, 149 LOC)
  - GREEN: 2 baseline tests pass.
  - Implementation: bounded `UPDATE refresh_tokens SET last_activity_at = now() WHERE id IN (SELECT id FROM refresh_tokens WHERE last_activity_at IS NULL LIMIT batch_size)`; loop with `time.sleep(sleep_seconds)` between batches; `main()` opens `SessionLocal`, runs helper, prints count.

- [x] **Task 0.3** — `test(auth): document live backfill evidence command`
  - Commit: `72ba56b`
  - Files: `backend/scripts/backfill_refresh_token_activity.py` (tweaked to use `RawDescriptionHelpFormatter`), `backend/tests/test_refresh_token_activity_backfill.py` (+54 LOC for 2 help tests).
  - GREEN: 2 help tests pass.
  - Added explicit `--help` epilog with the live-evidence SQL operators run before/after.

### Follow-up commits (post-PR0-verify, after `verify-report-pr0.md` flagged regressions)

- [x] **Regression d9e2997** — `test(auth): add CLI subprocess regression and DB NOW coverage`
  - Adds 3 tests in `backend/tests/test_refresh_token_activity_backfill.py`:
    - `test_help_works_without_postgres_db_import` (subprocess; RED against the original `f6f6801` script because of the eager `models.refresh_token` import chain).
    - `test_update_uses_database_now_not_python_clock` (RED against the original `datetime.utcnow()` UPDATE).
    - `test_invalid_batch_size_rejected` and `test_invalid_sleep_seconds_rejected` (validation tests, GREEN already).
  - RED state (script reverted via `git stash`): 2 of the 4 new tests fail with the exact errors the verify agent caught (`ModuleNotFoundError: psycopg2`; assertion error on rendered SQL).

- [x] **Regression 54c3ec0** — `fix(auth): make backfill script import-light and use DB NOW()`
  - Rewrites the backfill SQL as a single `text("UPDATE refresh_tokens SET last_activity_at = NOW() WHERE id IN (SELECT id FROM refresh_tokens WHERE last_activity_at IS NULL LIMIT :batch_size)")`.
  - Drops `from sqlalchemy import select, update` and `from models.refresh_token import RefreshToken` at module level; the script no longer pulls `postgres_db` at import time.
  - `Session` only imported under `TYPE_CHECKING` for type hints.
  - GREEN: 8/8 tests pass; `python backend/scripts/backfill_refresh_token_activity.py --help` succeeds on hosts without `psycopg2`.

- [x] **Evidence 67ee589** — `chore(sdd): record PR0 live PostgreSQL backfill evidence`
  - Adds `openspec/changes/fix-287-session-keep-alive/live-evidence-pr0.md` with BEFORE / RUN / AFTER output from a live `timescale/timescaledb:2.15.0-pg16` Docker container. Legacy row id=1 was updated to `NOW()`; control row id=2 was untouched; second run = 0 rows (idempotent).

### Housekeeping commit

- [x] `chore(sdd): mark PR0 tasks complete in tasks.md` — commit `9ddaa05`. Adds the OpenSpec `tasks.md` artifact to the branch so reviewers see the marked checkboxes.

---

## TDD Cycle Evidence (Strict TDD)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 0.1 | `backend/tests/test_refresh_token_activity_backfill.py` | Unit | N/A (new) | ✅ `ImportError` (helper missing) | n/a (test-only commit) | ✅ 2 cases (NULL row + empty batch) | ➖ None needed |
| 0.2 | `backend/tests/test_refresh_token_activity_backfill.py` | Unit | n/a (helper doesn't exist) | ✅ 0.1's RED | ✅ 2/2 passed | ➖ Same 2 baseline cases | ✅ Switched to `LIMIT` subquery for true bounded batching |
| 0.3 | `backend/tests/test_refresh_token_activity_backfill.py` | Unit | ✅ 2/2 (from 0.2) | ✅ Help SQL assertion failed (wrapped description) | ✅ 2/2 passed | ✅ 2 help cases (count + row-id SQL) | ✅ Used `RawDescriptionHelpFormatter` so SQL is not wrapped |

### Test Summary
- **Total tests written in PR0**: 8 (4 initial + 4 regression tests)
- **Total tests passing**: 8 (PR0 file) / 84 (auth-adjacent files) / 1044 (full backend)
- **Layers used**: Unit (7) + subprocess CLI regression (1)
- **Approval tests**: None (no existing-code refactor in PR0)
- **Pure functions created**: 1 (`backfill_refresh_token_activity`)

---

## Files Changed

| File | Action | What was done |
|------|--------|---------------|
| `backend/scripts/backfill_refresh_token_activity.py` | Created | Batched UPDATE helper + argparse CLI with live-evidence epilog. |
| `backend/tests/test_refresh_token_activity_backfill.py` | Created | Strict-TDD RED/GREEN coverage (4 tests). |
| `openspec/changes/fix-287-session-keep-alive/tasks.md` | Created in branch | Marks PR0 tasks complete; first commit of OpenSpec artifacts in this branch so the PR shows the updated checkboxes. |

**PR diff**: 2 source files, 284 insertions vs `fix/287-session-keep-alive`. Under the 400-line review budget.

---

## Test Status

| Scope | Command | Result |
|-------|---------|--------|
| Focused (PR0) | `uv run pytest backend/tests/test_refresh_token_activity_backfill.py -v` | 8 passed |
| Auth-adjacent | `uv run pytest tests/test_auth_service_refresh.py tests/test_auth_router_refresh.py tests/test_auth_service.py tests/test_audit_service.py tests/test_refresh_token_activity_backfill.py -q` | 84 passed |
| Full backend | `uv run pytest backend/tests -q` | **1044 passed, 97 pre-existing failures, 1 skipped** (baseline pre-PR0 was 1036 passed + 97 pre-existing failures; +8 new tests, no new failures) |
| CLI `--help` (no DB driver installed) | `uv run python backend/scripts/backfill_refresh_token_activity.py --help` | exit 0, evidence SQL present |
| Live PostgreSQL evidence | `RUNNING_LOCALLY=true POSTGRES_HOST=localhost uv run python backend/scripts/backfill_refresh_token_activity.py` against `timescale/timescaledb:2.15.0-pg16` container with 1 legacy NULL + 1 control row | updated 1 row; control untouched; second run = 0 rows (idempotent). Full output in `live-evidence-pr0.md`. |
| Pre-existing failures | RTU/backup/dictionary/cli_worker/event_correlation tests | **Unchanged** — same 13 files, 97 cases as before PR0; no regressions introduced by PR0. |

---

## Deviations from the Plan

- **Live PostgreSQL evidence**: Initially not collected by the apply agent because the local dev environment had no Postgres. The orchestrator raised `nexgen_postgres` (`timescale/timescaledb:2.15.0-pg16`), seeded one legacy NULL row + one control row, ran the script, and committed the BEFORE / RUN / AFTER output as `openspec/changes/fix-287-session-keep-alive/live-evidence-pr0.md` (commit `67ee589`). This satisfies the PR0 acceptance criterion that required live PostgreSQL evidence with at least one exercised row.
- **Three follow-up commits after the verify agent flagged regressions** (`d9e2997`, `54c3ec0`, `67ee589`): these are RED-then-GREEN pairs addressing the verify agent's three findings (live evidence, CLI `--help` import chain, `datetime.utcnow` vs DB `NOW()`). They were not in the original `tasks.md` PR0 plan but are necessary follow-ups.
- **`RawDescriptionHelpFormatter` added in 0.3 instead of 0.2**: Task 0.2 already included a brief description mentioning the SQL, but argparse was wrapping it across two lines and breaking the test substring search. The minor help refactor (`description` → `description + epilog + RawDescriptionHelpFormatter`) and the 2 help tests landed together in commit `72ba56b` because splitting them would have left a RED test in the 0.2 GREEN commit. This is a non-substantive split.
- **Housekeeping commits `9ddaa05`, `819df6d`**: The OpenSpec `tasks.md` and `apply-progress.md` were untracked in the worktree when PR0 started, so they were committed as `chore(sdd)` commits to surface the `[x]` marks and the progress report to reviewers. This is consistent with the project's "ship the SDD artifacts in the PR" convention.
- **Commit title format**: All work-unit commit titles match the exact strings from `tasks.md` plus the regression-fix follow-ups (`test(auth): …`, `fix(auth): …`, `chore(sdd): …`). No `Co-Authored-By` trailer, no AI attribution.

---

## Risks

- **PR body wording**: The PR body says `Closes #287`. With this wording GitHub will auto-close the parent issue when PR0 merges, but PR1 and PR2 are still pending. The orchestrator will fix this to `Part of #287 (PR0 of 3 in the feature-branch chain)` before merge.
- **Pre-existing 97 backend test failures (RTU/backup/dictionary/cli_worker)**: Unrelated to auth/session. Not addressed by PR0 by design (no scope creep). Listed in PR body under verification so reviewers know they are pre-existing.
- **No `ci-cd-pipeline` lint gate yet**: This PR will not be auto-validated by the new lint lane from PR1 of the ci-cd-pipeline change because that workflow is still in draft. PR0 does not add lint config or break any existing one.

---

## Open Items for PR1 (`fix/287-backend-activity-bump`)

- Open branch `fix/287-backend-activity-bump` from `fix/287-db-backfill` (after this PR merges) — but with `feature-branch-chain` the PR1 base is `fix/287-db-backfill`, so PR1 should branch from `fix/287-db-backfill` immediately after PR0 opens (even before merge) to keep the diff minimal and avoid the tracker accumulating backend changes.
- Tasks 1.1 through 1.8 from `tasks.md` are all still pending. None of them depend on PR0 for compilation (PR1 still reads `COALESCE(last_activity_at, created_at)` defensively).
- The per-worker throttle cache size (10,000 entries with TTL eviction) from the design open question is still to be decided.
- Audit event allow-list keys (`session_id`, `user_id`, `policy_profile`, `throttle_seconds`, `activity_anchor`) are confirmed in `tasks.md` and `design.md`.

---

## Verification Recommendation

`next_recommended`: `sdd-verify-minimax` for this slice — the orchestrator should:
1. Confirm `uv run pytest backend/tests/test_refresh_token_activity_backfill.py -v` is still 8/8 passing.
2. Confirm full backend suite still shows **1044 passed / 97 pre-existing failures** (no new regressions).
3. Confirm PR #289 is the only one in the chain that is `OPEN`.
4. Confirm live-evidence captured in `live-evidence-pr0.md` is met (legacy row updated, control row untouched, idempotent on second run).