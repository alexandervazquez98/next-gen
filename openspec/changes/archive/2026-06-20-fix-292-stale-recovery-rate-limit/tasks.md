# Tasks: Fix #292 Stale-Recovery Rate-Limit Counter

**Chain strategy**: `size-exception` (single PR; forecast well under 400 lines; user chose single-PR over chained in the cycle brief)
**Mode**: Strict TDD (`strict_tdd: true`)
**Change ID**: `fix-292-stale-recovery-rate-limit`

## T1 — Worktree + Branch Setup

- [x] Worktree: `/home/alex/dev/next-gen/worktrees/fix-292-stale-recovery-rate-limit`
- [x] Branch: `fix/292-stale-recovery-rate-limit` from `main@e9557e0823e4355b20e9b35b2d74b3ee5a8f73a1`
- [x] Branch linked to PR #293 (`alexandervazquez98/next-gen#293`)

## T2 — RED Router Tests (ROTATED_STALE_RECOVERABLE honoring)

- [x] Add `test_recoverable_stale_exhaustion_does_not_increment_rate_limit` in `backend/tests/test_auth_router_refresh.py`
- [x] Add `test_recoverable_stale_within_cap_does_not_increment_rate_limit` (wrong-reason guard: assert `increment_attempts.assert_not_called()` even when atomic returns `True`)
- [x] Add `test_recoverable_stale_token_id_none_does_not_increment_rate_limit`
- [x] Capture RED failure messages against `main@e9557e0` (tests #1 and #3 fail; #2 passes for the wrong reason)
- [x] Commit: `test(auth): add RED tests for ROTATED_STALE_RECOVERABLE rate-limit honoring` (`1c27f55`)

## T3 — Router Fix

- [x] Add inline `if verification.should_count_rate_limit:` guard around `backend/routers/auth.py:404` `increment_attempts` call only
- [x] Production change is exactly the surgical guard: 2 insertions, 1 deletion at lines 403-404
- [x] All T2 router tests now pass
- [x] Existing `test_stale_refresh_recoverable_does_not_increment_rate_limit` untouched (passes)
- [x] Commit: `fix(auth): honor should_count_rate_limit in ROTATED_STALE_RECOVERABLE branch` (`c1d4655`)

## T4 — Terminal Abuse Regression Tests

- [x] Add `test_terminal_abuse_statuses_still_increment_rate_limit_revoked` in `backend/tests/test_auth_router_refresh.py`
- [x] Add `test_terminal_abuse_statuses_still_increment_rate_limit_expired`
- [x] Add `test_missing_refresh_token_increments_rate_limit`
- [x] All three pass against current AND fixed main (regression guards)
- [x] Commit: `test(auth): add regression coverage for terminal abuse statuses` (`2a69b9e`)

## T5 — Service Tests

- [x] Add `test_all_rotated_stale_recoverable_paths_set_should_count_rate_limit_false` in `backend/tests/test_auth_service_refresh.py`
- [x] Add `test_rotated_token_beyond_grace_is_stale_rejected_not_recoverable` (complementary boundary test; `test_rotated_token_beyond_grace_is_rejected` already exists at line 276 — strict-TDD name uniqueness honored)
- [x] Add `test_try_increment_refresh_recovery_count_contract_unchanged` (regression guard for recovery atomic)
- [x] All three pass
- [x] Commit: `test(auth): cover service stale-recovery flag and atomic contract` (`462e321`)

## Acceptance Verification

- [x] Targeted suite: `uv run pytest backend/tests/test_auth_router_refresh.py backend/tests/test_auth_service_refresh.py -v` → `65 passed, 0 failed`
- [x] Individual 9 scenario tests → `9 passed, 0 failed`
- [x] Backend test tree: `uv run pytest backend/tests` → `1067 passed, 97 failed, 1 skipped` (97 pre-existing failures across 13 unrelated files; not introduced by this PR)
- [x] No source files outside `backend/routers/auth.py`, `backend/tests/test_auth_router_refresh.py`, `backend/tests/test_auth_service_refresh.py` modified
- [x] No frontend, schema, telemetry, dependency, or recovery-atomic files changed