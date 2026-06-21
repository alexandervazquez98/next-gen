# Auth Rate Limit Flag Honoring Specification

## Purpose

The router MUST honor `RefreshVerificationResult.should_count_rate_limit` in the `ROTATED_STALE_RECOVERABLE` branch only. This surgical fix prevents legitimate stale-rotation races from counting toward `rate_limit_attempts` without broadening #292 into a router-wide rate-limit refactor.

## Requirements

### Requirement: Router honors should_count_rate_limit flag for ROTATED_STALE_RECOVERABLE

WHY: `backend/routers/auth.py:398-408` currently reaches `increment_attempts` at `:404` when recovery is unavailable. SHALL: `ROTATED_STALE_RECOVERABLE` with `should_count_rate_limit=False` MUST NOT increment refresh-token rate limits. Verified in `backend/tests/test_auth_router_refresh.py`.

#### Scenario: test_recoverable_stale_within_cap_does_not_increment_rate_limit

- Given `verify_refresh_token` returns `ROTATED_STALE_RECOVERABLE`, `token_id`, and `should_count_rate_limit=False`
- When `try_increment_refresh_recovery_count` returns `True`
- Then `increment_attempts` is not called and no `RateLimitAttempt` row exists.

#### Scenario: test_recoverable_stale_exhaustion_does_not_increment_rate_limit

- Given `verify_refresh_token` returns `ROTATED_STALE_RECOVERABLE`, `token_id`, and `should_count_rate_limit=False`
- When `try_increment_refresh_recovery_count` returns `False`
- Then the response is 401 and no `RateLimitAttempt` row exists.

#### Scenario: test_recoverable_stale_token_id_none_does_not_increment_rate_limit

- Given `verify_refresh_token` returns `ROTATED_STALE_RECOVERABLE`, `token_id=None`, and `should_count_rate_limit=False`
- When the router skips recovery reservation
- Then `increment_attempts` is not called and no `RateLimitAttempt` row exists.

> Note: Deferred to follow-up. The "flag is source of truth for every router status" invariant is out of scope for #292. The current spec restricts to the ROTATED_STALE_RECOVERABLE branch per the issue's "surgical fix" framing. A future change may add the flag guard at every `increment_attempts` call site.

### Requirement: Terminal abuse statuses still count toward rate limits

WHY: terminal abuse call sites in `backend/routers/auth.py` include `MISSING` at `:298`, `EXPIRED` at `:307`, and `REVOKED` at `:314`. SHALL: statuses without an explicit `False` flag MUST increment. Verified in `backend/tests/test_auth_router_refresh.py`.

#### Scenario: test_terminal_abuse_statuses_still_increment_rate_limit_revoked

- Given `verify_refresh_token` returns `REVOKED` with the model default flag
- When `/auth/refresh` is requested
- Then one refresh-token rate-limit attempt is recorded.

#### Scenario: test_terminal_abuse_statuses_still_increment_rate_limit_expired

- Given `verify_refresh_token` returns `EXPIRED` with the model default flag
- When `/auth/refresh` is requested
- Then one refresh-token rate-limit attempt is recorded.

#### Scenario: test_missing_refresh_token_increments_rate_limit

- Given no refresh token is provided
- When `/auth/refresh` is requested
- Then one refresh-token rate-limit attempt is recorded.

### Requirement: Service-level guarantee: every ROTATED_STALE_RECOVERABLE result has should_count_rate_limit=False

WHY: `verify_refresh_token` starts at `backend/services/auth_service.py:261`; the recoverable stale result sets `should_count_rate_limit=False` at `:339-344`, while `VALID` sets it at `:360-368`. SHALL: every recoverable stale service result MUST carry the false flag. Verified in `backend/tests/test_auth_service_refresh.py`.

#### Scenario: test_all_rotated_stale_recoverable_paths_set_should_count_rate_limit_false

- Given a rotated refresh token is within stale grace and recovery policy permits recovery
- When `verify_refresh_token` evaluates it
- Then status is `ROTATED_STALE_RECOVERABLE` and `should_count_rate_limit is False`.

#### Scenario: test_rotated_token_beyond_grace_is_rejected

- Given a rotated refresh token is past stale grace
- When `verify_refresh_token` evaluates it
- Then status is `ROTATED_STALE_REJECTED`, not `ROTATED_STALE_RECOVERABLE`.

### Requirement: Recovery atomic unchanged

WHY: `try_increment_refresh_recovery_count` is `backend/services/auth_service.py:378-397`. SHALL: this change MUST NOT alter the atomic reservation contract or `stale_rotation_max_recoveries`; only router counter honoring changes. Existing coverage remains in `backend/tests/test_auth_service_refresh.py`.

#### Scenario: test_try_increment_refresh_recovery_count_contract_unchanged

- Given the atomic update affects one row, it returns `True`
- When the atomic update affects zero rows because the cap is exhausted
- Then it returns `False` and commits using the existing contract.

## Out of Scope

This capability does NOT cover the following. They are deferred follow-up work for separate SDD cycles:

- Changing the value of `stale_rotation_max_recoveries`.
- Adding new telemetry or logging for stale-rotation races.
- Changing the recovery atomic implementation in `try_increment_refresh_recovery_count`.
- A router-wide "flag is source of truth" refactor that guards every `increment_attempts` call site (Req 1's deferred note). The current spec restricts the flag guard to the `ROTATED_STALE_RECOVERABLE` branch only.
- Any frontend work (the bug is server-only).