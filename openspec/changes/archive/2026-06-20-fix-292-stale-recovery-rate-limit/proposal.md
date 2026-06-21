# Proposal: Fix #292 Stale-Recovery Rate-Limit Counter

Status: Draft  
Change ID: `fix-292-stale-recovery-rate-limit`  
GitHub Issue: `alexandervazquez98/next-gen#292` (`OPEN`, `type:bug`)  
Extends: `#188` stale refresh-token recovery; follows #287 deferral of Bug 3.

## Intent

Fix a server-only auth bug where legitimate stale refresh-token rotation races can increment `rate_limit_attempts` after the recovery counter is exhausted. `ROTATED_STALE_RECOVERABLE` already means `should_count_rate_limit=False`; the router must honor that flag regardless of whether the recovery atomic returns within-cap or exhausted.

## Scope

### Single PR — backend auth bugfix (~180-250 changed lines)
- Remove or guard the stale-recovery `increment_attempts` call in `backend/routers/auth.py`.
- Add strict-TDD backend coverage for exhausted recovery, within-cap recovery, and router-level `should_count_rate_limit=False` honoring.
- Add/confirm service coverage that every `ROTATED_STALE_RECOVERABLE` result sets `should_count_rate_limit=False`.

Single PR is intentional: one router fix, backend-only tests, no DB migration, no API surface change, no frontend work, and well under the 400-line review budget.

## Out of Scope

- Changing the value of `stale_rotation_max_recoveries`.
- Adding new telemetry for stale-rotation races.
- Changing the recovery atomic implementation.
- Any frontend work (the bug is server-only).

## Capabilities

### New Capabilities
- `auth-rate-limit-flag-honoring`: router honors `RefreshVerificationResult.should_count_rate_limit` for every refresh verification status, including `ROTATED_STALE_RECOVERABLE`.

### Modified Capabilities
- None.

## Verified Current Evidence

Verified against `main@e9557e0823e4355b20e9b35b2d74b3ee5a8f73a1`.

`backend/routers/auth.py:398-408` currently ignores the flag in the exhausted recovery branch:

```python
398:    if verification.status == RefreshVerificationStatus.ROTATED_STALE_RECOVERABLE:
399:        if verification.token_id is None or not try_increment_refresh_recovery_count(
400:            db,
401:            verification.token_id,
402:            policy.stale_rotation_max_recoveries,
403:        ):
404:            increment_attempts(rate_limit_key, identity_type="refresh_token")
405:            raise HTTPException(
406:                status_code=status.HTTP_401_UNAUTHORIZED,
407:                detail="session expired",
408:            )
```

- `verify_refresh_token` starts at `backend/services/auth_service.py:261`.
- `ROTATED_STALE_RECOVERABLE` sets `should_count_rate_limit=False` at `backend/services/auth_service.py:337-345`.
- `VALID` also sets `should_count_rate_limit=False` at `backend/services/auth_service.py:360-368`.
- `try_increment_refresh_recovery_count` is `backend/services/auth_service.py:378-397`.
- `RefreshVerificationResult.should_count_rate_limit` defaults to `True` at `backend/models/refresh_token.py:77`.

## Acceptance Criteria

1. Backend: when `verify_refresh_token` returns `ROTATED_STALE_RECOVERABLE` with `should_count_rate_limit=False`, the router does NOT call `increment_attempts` for that request, regardless of recovery counter state.
2. Backend test: `test_recoverable_stale_exhaustion_does_not_increment_rate_limit` covers exhausted recovery and asserts no `rate_limit_attempts` row is added.
3. Backend test: `test_recoverable_stale_within_cap_does_not_increment_rate_limit` covers within-cap recovery and asserts no row is added.
4. Backend test: `test_should_count_rate_limit_false_honored_by_router` patches `verify_refresh_token` with `should_count_rate_limit=False` and asserts `increment_attempts` is never called.
5. Full backend suite still green (`uv run pytest`; no new regressions).
6. Actual refresh-token abuses (`REVOKED`, `EXPIRED`, `MISSING`) still count toward rate limits.
7. No new telemetry/logging for stale-rotation races.

## Risks

| Risk | Likelihood | Mitigation |
|---|---:|---|
| Existing within-cap router test passes for the wrong reason: recovery atomic returns `True` and short-circuits before the buggy line. | High | New tests must explicitly set `should_count_rate_limit=False`, patch `routers.auth.increment_attempts`, and assert `increment_attempts.assert_not_called()` even when the recovery atomic returns `True`. |
| Surgical fix could accidentally weaken abuse counting for terminal statuses. | Medium | Limit code change to `ROTATED_STALE_RECOVERABLE`; add regression assertions that `REVOKED`, `EXPIRED`, and `MISSING` still count. |
| Spec could over-expand into recovery policy or telemetry. | Low | Keep scope bound to router flag honoring; out-of-scope items are firm. |

## Rollback Plan

Revert the single backend PR. This restores previous behavior without data migration or API rollback. Tests added for this change can be reverted with the code if emergency rollback is needed.

## Dependencies

- Existing `RefreshVerificationResult.should_count_rate_limit` contract.
- Existing backend test runner: `uv run pytest`.

## Open Questions Before Spec

None. The issue, exploration, and verified current code agree on the bug, scope, and out-of-scope boundaries.