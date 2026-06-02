# Apply Progress — fix-multi-window-session-timeout

Scope: `fix-multi-window-session-timeout` (Issue #188).

## Chain status

- PR1: `fix/session-policy-foundation` -> `main`, opened as PR #245, accepted for review.
- PR2: `fix/session-refresh-stale-recovery` -> `fix/session-policy-foundation`, backend-only stale refresh/rate-limit slice in progress.
- PR3/PR4: not started.

## PR1 summary

PR1 completed backend session-policy foundation:

- `backend/services/session_policy.py`
- `backend/tests/test_session_policy.py`
- policy metadata on refresh tokens
- startup migration/backfill for refresh token metadata
- policy-aware cookie max-age
- JWT `sid`/`profile` claims
- refresh `session_id` continuity

PR1 verify accepted the slice for review.

## PR2 summary

PR2 implements backend stale refresh-token recovery and contention handling:

- structured `RefreshVerificationStatus` / `RefreshVerificationResult`
- terminal statuses for missing/expired/revoked/idle-expired/stale-rejected states
- recoverable stale-rotation status for short concurrent-tab grace window
- bounded stale recovery count based on session policy
- rotated token metadata (`rotated_at`, `replaced_by_token_id`, `revoked_reason`)
- refresh endpoint branches by structured status
- recoverable stale refresh does not add rate-limit failures
- stale recovery count reservation uses an atomic conditional update before issuing recovered tokens
- valid refresh still rotates old token using single-use semantics
- tests for service-level status handling, atomic recovery reservation, and router/rate-limit behavior

## PR2 incident note

Initial PR2 `sdd-apply` failed due an ambiguous edit in `backend/tests/test_auth_router_refresh.py`, leaving a partial but coherent backend diff. A fresh incident audit found no conflict markers or syntax failures and recommended continuing manually. The only blocker was a test patch returning a non-JWT `access_token` while decoding it. That test was corrected by letting the real `create_access_token` run.

## Strict-TDD — TDD Cycle Evidence

### PR1

| Phase | Evidence |
| --- | --- |
| RED | Added/updated PR1 tests first in `backend/tests/test_session_policy.py`, `backend/tests/test_auth_service.py`, `backend/tests/test_auth_service_refresh.py`, and `backend/tests/test_auth_router_refresh.py`. |
| GREEN | Implemented session policy foundation, refresh token metadata, cookie policy wiring, and JWT `sid`/`profile` claims. |
| TRIANGULATE | Focused backend tests passed: `47 passed` for session/auth refresh tests and `26 passed` for auth service tests. |
| REFACTOR | Kept PR1 backend-only and preserved existing `sub`/`role` access token claims. |

### PR2

| Phase | Evidence |
| --- | --- |
| RED | Added stale-rotation, idle-expiry, terminal status, recoverable stale refresh, and rate-limit non-increment tests in `backend/tests/test_auth_service_refresh.py` and `backend/tests/test_auth_router_refresh.py`. |
| GREEN | Implemented structured refresh verification result/status, rotation metadata, recoverable stale refresh handling, and router branching. |
| TRIANGULATE | Ran focused PR2 backend matrix: `cd backend && python -m pytest tests/test_auth_service_refresh.py tests/test_auth_router_refresh.py tests/test_session_policy.py tests/test_auth_service.py tests/test_rate_limit.py` — **97 passed**. |
| REFACTOR | Kept PR2 backend-only; did not implement frontend singleflight/cross-tab or inactivity UX. |

## Verification commands

### PR1 accepted evidence

- `cd backend && python -m pytest tests/test_session_policy.py tests/test_auth_service_refresh.py tests/test_auth_router_refresh.py`
  - **47 passed**
- `cd backend && python -m pytest tests/test_auth_service.py`
  - **26 passed**

### PR2 current evidence

- `cd backend && python -m pytest tests/test_auth_service_refresh.py tests/test_auth_router_refresh.py tests/test_session_policy.py tests/test_auth_service.py tests/test_rate_limit.py`
  - **97 passed**

## Remaining work

- PR2 still needs fresh review and SDD verify before commit/PR.
- PR3: API contract bridge for frontend policy visibility if required.
- PR4: frontend singleflight, cross-tab coordination, and inactivity UX.

## Known risks

- Stale-token recovery must remain tightly bounded to prevent replay abuse.
- Browser cross-tab coordination is still not implemented; backend tolerance is PR2's focus.
- PostgreSQL startup migration/backfill still needs validation against a real PostgreSQL instance.
- `open-issues-triage.md` remains untracked and outside PR2 scope.
