# Design: Fix #292 Stale-Recovery Rate-Limit Counter

## Approach Summary

Apply a surgical router fix on `main@e9557e0`: keep the `ROTATED_STALE_RECOVERABLE` control flow at `backend/routers/auth.py:398-408` and guard only the exhausted-recovery counter write at `:404` with `if verification.should_count_rate_limit:`. No schema, policy, telemetry, frontend, or recovery-atomic changes. Verified main evidence: `verify_refresh_token` starts at `backend/services/auth_service.py:261`; recoverable stale sets `should_count_rate_limit=False` at `:339-344`; VALID sets it at `:360-368`/`:367`; `try_increment_refresh_recovery_count` is `:378-397`; the model default is `backend/models/refresh_token.py:77`.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|---|---|---|---|
| Fix shape | Inline guard around `backend/routers/auth.py:404` | Remove the write; refactor all router counter calls | Minimal change honors the service flag while preserving existing 401 behavior and recovery reservation flow. |
| Scope | Production change only in `backend/routers/auth.py:398-408` | Router-wide "flag as source of truth" refactor | Revised spec explicitly defers the broad invariant and asks for ROTATED_STALE_RECOVERABLE only. |
| Test split | RED stale-recovery tests before fix, regression guards after | One mixed test commit | Separates failing bug proof from green-now abuse regressions and service contracts. |

## Implementation: Router Fix

BEFORE (`backend/routers/auth.py:398-408`):

```python
if verification.status == RefreshVerificationStatus.ROTATED_STALE_RECOVERABLE:
    if verification.token_id is None or not try_increment_refresh_recovery_count(...):
        increment_attempts(rate_limit_key, identity_type="refresh_token")  # :404
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session expired")
```

AFTER:

```python
if verification.status == RefreshVerificationStatus.ROTATED_STALE_RECOVERABLE:
    if verification.token_id is None or not try_increment_refresh_recovery_count(...):
        if verification.should_count_rate_limit:
            increment_attempts(rate_limit_key, identity_type="refresh_token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session expired")
```

Scenario fit: Req 1 scenarios (exhausted, within-cap, token_id_none) skip increments when the recoverable flag is False. Req 3 terminal-abuse scenarios (REVOKED, EXPIRED, MISSING) keep their existing default-True count behavior as regression guards. Req 4 and Req 5 remain service-only contract verification. The broader "flag is source of truth for every router status" invariant is explicitly deferred per the revised spec.

Terminal regression evidence on `main@e9557e0`: MISSING `backend/routers/auth.py:298`, EXPIRED `:307`, REVOKED `:314`, IDLE_EXPIRED `:321`, USER_INACTIVE `:370`, ROTATED_STALE_REJECTED `:377`, no-user `:386`, no-db-user `:394`.

## Data Flow

`/api/auth/refresh` → `verify_refresh_token` → `RefreshVerificationResult.should_count_rate_limit` → `ROTATED_STALE_RECOVERABLE` exhausted branch → optional `increment_attempts` → 401, or successful rotation.

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/routers/auth.py` | Modify | Add inline `should_count_rate_limit` guard around the stale-recovery exhausted counter write only (`:404`). |
| `backend/tests/test_auth_router_refresh.py` | Modify | Add router tests for scenarios 1-6. |
| `backend/tests/test_auth_service_refresh.py` | Modify | Add/confirm service tests for scenarios 7-9. |

## Implementation: Test Additions

| # | Test | File | Fixtures / patches / mock shape |
|---:|---|---|---|
| 1 | `test_recoverable_stale_exhaustion_does_not_increment_rate_limit` | router | `rate_limit_db`; patch `verify_refresh_token` → `ROTATED_STALE_RECOVERABLE`, `token_id=99`, `should_count_rate_limit=False`; patch `try_increment_refresh_recovery_count=False`; patch `increment_attempts`; assert 401, `increment_attempts.assert_not_called()`, no `RateLimitAttempt` row. |
| 2 | `test_recoverable_stale_within_cap_does_not_increment_rate_limit` | router | Same, but atomic `True`; patch `create_refresh_token` / `create_access_token`; assert 200 and `increment_attempts.assert_not_called()` even though atomic returned True. |
| 3 | `test_recoverable_stale_token_id_none_does_not_increment_rate_limit` | router | Result has `token_id=None`, flag False; patch atomic and assert it is not called; assert 401, no increment. |
| 4 | `test_terminal_abuse_statuses_still_increment_rate_limit_revoked` | router | `rate_limit_db`; result `REVOKED` default flag True; assert exactly one `RateLimitAttempt` row. |
| 5 | `test_terminal_abuse_statuses_still_increment_rate_limit_expired` | router | Result `EXPIRED` default flag; assert one row. |
| 6 | `test_missing_refresh_token_increments_rate_limit` | router | No cookie/body or mocked `MISSING` path per current pattern; assert one row. |
| 7 | `test_all_rotated_stale_recoverable_paths_set_should_count_rate_limit_false` | service | Reuse `TestVerifyRefreshToken._mock_rt`; rotated token within grace and below cap; assert status `ROTATED_STALE_RECOVERABLE` and `should_count_rate_limit is False`. |
| 8 | `test_rotated_token_beyond_grace_is_rejected` | service | Existing helper with `rotated_at` older than grace; assert `ROTATED_STALE_REJECTED`, NOT `ROTATED_STALE_RECOVERABLE`. |
| 9 | `test_try_increment_refresh_recovery_count_contract_unchanged` | service | Reuse `MagicMock`; `update.return_value=1` then `0`; assert `True`/`False` and `commit.assert_called()`. |

Key review point: existing `test_stale_refresh_recoverable_does_not_increment_rate_limit` passes today for the wrong reason because atomic `True` short-circuits before the buggy line. Test #2 must explicitly patch `routers.auth.increment_attempts` and assert `assert_not_called()` even when atomic returns `True`.

## Worktree, Branch, PR, Commits

| Commit | Message | Content |
|---|---|---|
| 1 | `test(auth): add RED tests for ROTATED_STALE_RECOVERABLE rate-limit honoring` | Router tests #1-#3 (RED-first; fail against current main). |
| 2 | `fix(auth): honor should_count_rate_limit in ROTATED_STALE_RECOVERABLE branch` | Inline guard in `backend/routers/auth.py:398-408`; router tests #1-#3 now pass. |
| 3 | `test(auth): add regression coverage for terminal abuse statuses` | Router tests #4-#6 (regression guards; pass against current AND fixed main). |
| 4 | `test(auth): cover service stale-recovery flag and atomic contract` | Service tests #7-#9. |

Commit splitting rationale: scenarios 1-3 are strictly RED-first. Scenarios 4-6 are GREEN-now-and-after regression guards, so commit 3 keeps the fix commit minimal. Service tests stay in commit 4 because they are contract-level, not router behavior.

## Testing / Verification

- Targeted: `uv run pytest backend/tests/test_auth_router_refresh.py backend/tests/test_auth_service_refresh.py -v`
- Full backend: `uv run pytest` from repo root.
- No frontend changes; do not run frontend tests.
- Keep existing wrong-reason test; do not delete it in this PR.
- Confirm `git diff main -- backend/routers/auth.py` shows only the surgical guard.

## Migration / Rollout / Rollback

No migration required. Roll back by reverting the implementation PR; no data, API, schema, or frontend state to undo.

## Out of Scope

No router-wide flag-source-of-truth refactor, stale-rotation telemetry, `stale_rotation_max_recoveries` change, recovery atomic change, or frontend work.

## Open Questions

None. The spec revision resolved the overreach; the surgical ROTATED_STALE_RECOVERABLE-only fix is final.