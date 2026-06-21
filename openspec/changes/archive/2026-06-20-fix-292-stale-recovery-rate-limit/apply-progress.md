# Apply Progress: fix-292-stale-recovery-rate-limit

**Branch**: `fix/292-stale-recovery-rate-limit`
**Base SHA**: `e9557e0823e4355b20e9b35b2d74b3ee5a8f73a1` (matches main exactly)
**Worktree**: `/home/alex/dev/next-gen/worktrees/fix-292-stale-recovery-rate-limit`
**PR**: https://github.com/alexandervazquez98/next-gen/pull/293
**Mode**: Strict TDD

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| T2 | `backend/tests/test_auth_router_refresh.py` | Router (integration) | ✅ 56/56 | ✅ 2 RED + 1 GREEN-for-wrong-reason | ✅ All 3 GREEN after T3 | ✅ 3 cases (exhausted/within-cap/token_id=None) | ➖ None needed |
| T3 | `backend/routers/auth.py` (production) | N/A | ✅ 56/56 | N/A | ✅ 1-line guard (2 insertions, 1 deletion) | ➖ Surgical | ➖ None needed |
| T4 | `backend/tests/test_auth_router_refresh.py` | Router (integration) | ✅ 30/30 | N/A (regression) | ✅ 3 GREEN | ➖ Regression-only | ➖ None needed |
| T5 | `backend/tests/test_auth_service_refresh.py` | Service (unit) | ✅ 35/35 | N/A (contract) | ✅ 3 GREEN | ➖ Contract-only | ➖ None needed |

### Test Summary
- **Total tests written**: 9 (6 router + 3 service)
- **Total tests passing**: 9/9
- **Layers used**: Router integration (6), Service unit (3)
- **Approval tests (refactoring)**: None — no refactoring tasks
- **Pure functions created**: None

## Commits

1. **`1c27f55`** — `test(auth): add RED tests for ROTATED_STALE_RECOVERABLE rate-limit honoring` (T2)
2. **`c1d4655`** — `fix(auth): honor should_count_rate_limit in ROTATED_STALE_RECOVERABLE branch` (T3)
3. **`2a69b9e`** — `test(auth): add regression coverage for terminal abuse statuses` (T4)
4. **`462e321`** — `test(auth): cover service stale-recovery flag and atomic contract` (T5)

## Test outcomes

- **T2**: 2 RED (`test_recoverable_stale_exhaustion_does_not_increment_rate_limit`, `test_recoverable_stale_token_id_none_does_not_increment_rate_limit`) + 1 GREEN-for-wrong-reason (`test_recoverable_stale_within_cap_does_not_increment_rate_limit`)
- **T3**: All 3 T2 tests GREEN for right reason; full router file (30 tests) GREEN; existing `test_stale_refresh_recoverable_does_not_increment_rate_limit` still passes (unmodified)
- **T4**: 3 regression tests GREEN; full router file still GREEN
- **T5**: 3 service tests GREEN; full service file (35 tests) GREEN
- **T6**: Full backend suite — 1067 passed (+9), 97 failed (pre-existing, unchanged), 1 skipped. Targeted files (auth_router_refresh + auth_service_refresh): 65/65 GREEN.

## Deviations from Design

1. **`test_rotated_token_beyond_grace_is_rejected` already existed** at `backend/tests/test_auth_service_refresh.py:276`. Per strict-TDD rules against duplicate test names, the orchestrator's exact name couldn't be reused. I added a complementary boundary test `test_rotated_token_beyond_grace_is_stale_rejected_not_recoverable` with an explicit `status != ROTATED_STALE_RECOVERABLE` assertion. The boundary is now pinned twice (positively + explicitly negated). Net new service tests: 3 (matching the plan).

2. **Orchestrator line citations for `auth_service.py` were stale** (~140 lines off): `verify_refresh_token` starts at `:134`, ROTATED_STALE_RECOVERABLE flag block at `:210-220`, VALID flag block at `:233-243`, `try_increment_refresh_recovery_count` at `:251`. The bug-site line numbers for `routers/auth.py` (398-408, buggy call at 404) and the model default at `models/refresh_token.py:77` were exact. The shape of the fix in `design.md` matched the actual code perfectly, so I proceeded.

## Issues Found

1. **Full-suite baseline mismatch**: Orchestrator claimed "1134 baseline → 1143 after". Actual baseline on `main@e9557e0` in this worktree: **1058 passing, 97 failed, 1 skipped**. After this PR: **1067 passing, 97 failed, 1 skipped** (+9 from this PR). The 97 failures are pre-existing on `main@e9557e0` across 13 unrelated test files (test_auth_extended, test_backup_service, test_cli_worker, test_dictionary_service, test_event_correlation, test_routers_dictionaries, test_routers_events, test_routers_links, test_routers_metrics_events, test_routers_nodes, test_rtu_integration, test_rtu_sensor_repo, test_rtus_router). They are NOT introduced by this PR and are NOT in scope for #292.

2. **`backend/scripts/test_single_ci_reconcile.py`** has a pre-existing import error (`from database import get_db` — no `database` module exists, only `postgres_db`). Triggered only when running pytest from the repo root. Workaround: run from `backend/`. Not modified in this PR.

## Files Touched

| File | Action | Lines | Commits |
|---|---|---|---|
| `backend/routers/auth.py` | Modify (inline guard at `:403-404`) | +2/-1 | T3 |
| `backend/tests/test_auth_router_refresh.py` | Extend | +326 | T2, T4 |
| `backend/tests/test_auth_service_refresh.py` | Extend | +91 | T5 |

Total: 3 files, 419 insertions, 1 deletion. Production change is 3 lines (the inline guard); the rest is test code.

## Status

**READY FOR VERIFY**

- 4/4 commits on branch
- All 9 new tests pass
- Targeted files (auth/refresh): 65/65 GREEN
- Full backend suite: 1067 passed (+9 from this PR); 97 pre-existing failures unchanged (unrelated to auth/refresh)
- PR opened: https://github.com/alexandervazquez98/next-gen/pull/293
- Label `type:bug` applied
- Conventional commits only; no `Co-Authored-By` trailers
- No production change beyond the surgical inline guard