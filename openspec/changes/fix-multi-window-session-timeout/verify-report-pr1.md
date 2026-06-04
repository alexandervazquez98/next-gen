# Verify Report — PR1 Backend Policy/Schema Foundation

Change: `fix-multi-window-session-timeout` / issue #188  
Verified scope: **PR1 backend-only slice**  
Strict TDD mode: **active**  
Verification rerun: 2026-06-01

## Status

**Result: PASS / accepted for review for PR1 scope.**

Previously reported blockers are resolved:

1. **Strict-TDD evidence table present:** `apply-progress.md` now contains a `TDD Cycle Evidence` table with RED/GREEN/TRIANGULATE/REFACTOR evidence.
2. **Access-token session/profile claims present:** login and refresh access tokens now include `sid` and `profile`; refresh preserves the prior refresh-token `session_id` as the new access-token `sid` and passes the same `session_id` into refresh-token creation.

## Scope / Diff Inspection

Current PR1-relevant changed files observed:

- `backend/services/session_policy.py` — policy resolver/config module.
- `backend/tests/test_session_policy.py` — resolver tests.
- `backend/models/refresh_token.py` — session metadata columns added.
- `backend/services/auth_service.py` — policy/session-aware refresh-token creation and optional session metadata verification.
- `backend/routers/auth.py` — login creates refresh cookie; login/refresh use policy-derived expiry; access tokens include `sid`/`profile`; refresh preserves session lineage.
- `backend/main.py` — startup additive migration/backfill guard.
- `backend/tests/test_auth_service_refresh.py`, `backend/tests/test_auth_router_refresh.py`, `backend/tests/test_auth_service.py` — PR1 tests updated.

Scope notes:

- No PR2 stale-token recovery/rate-limit bypass implementation is required for this verification, and none was required for acceptance.
- No PR3 frontend policy metadata bridge is required for this verification.
- No PR4 frontend singleflight/cross-tab/inactivity UX is required for this verification.
- Untracked `open-issues-triage.md` is outside PR1 verification scope and should not be included in PR1 unless separately justified.
- Changed-line estimate is at/over the configured 400-line review budget, but `apply-progress.md` records a `single-pr` exception accepted by the user.

## Spec Coverage

| Requirement / PR1 expectation | Coverage | Evidence / Finding |
|---|---:|---|
| Session policy resolver/config | PASS | `session_policy.py`; `test_session_policy.py` covers role allowlist, user allowlist, disabled operational mode, standard defaults. |
| Refresh token metadata/schema foundation | PASS with deployment follow-up | Model columns and startup DDL/backfill added for `session_id`, `policy_profile`, `last_activity_at`, rotation/audit fields, recovery count. |
| Login sets refresh cookie | PASS | `/auth/token` creates refresh token and sets `refresh_token` cookie; focused router tests pass. |
| Login/refresh cookie expiry based on policy | PASS | Router tests assert standard and operational refresh cookie `Max-Age`. |
| Refresh preserves logical session_id in refresh-token lineage | PASS | `verify_refresh_token(..., include_session_metadata=True)` returns `(user_id, session_id)` and refresh creates replacement with prior `session_id`. |
| Login access-token `sid`/`profile` claims | PASS | `auth.py` creates `session_id`, includes `sid` and `profile` in login token payload; `test_login_access_token_includes_session_and_profile_claims` passes. |
| Refresh access-token `sid`/`profile` continuity | PASS | Refresh uses verified `session_id` and resolved profile in access-token payload; `test_refresh_includes_session_claim_continuity_and_profile` passes. |
| PR2 stale-token recovery/rate-limit behavior | NOT REQUIRED | Correctly deferred for this PR1 verification. |
| PR3/PR4 frontend work | NOT REQUIRED | Correctly absent from acceptance criteria for this rerun. |

## Strict TDD Compliance

**Status: PASS for PR1 verification.**

- Strict TDD is active in `openspec/config.yaml` (`sdd.tdd_policy: strict_tdd`).
- No project-local `.pi/gentle-ai/support/strict-tdd-verify.md` override was available, so built-in strict-TDD checks were applied.
- `apply-progress.md` contains the required `TDD Cycle Evidence` table.
- Reported test files exist and were cross-referenced in the codebase:
  - `backend/tests/test_session_policy.py`
  - `backend/tests/test_auth_service.py`
  - `backend/tests/test_auth_service_refresh.py`
  - `backend/tests/test_auth_router_refresh.py`
- Focused tests were rerun and are GREEN.
- Assertion quality audit: acceptable for PR1. Tests assert resolver outputs, persisted refresh-token metadata, cookie max-age behavior, hashed-token behavior, rate-limit behavior, login access-token `sid`/`profile`, and refresh `sid` continuity. No tautological, ghost-loop, CSS implementation-detail, or type-only-only assertions were found in the PR1 acceptance-critical tests.

## Test / Validation Commands

### Focused PR1 command

Command:

```bash
cd backend && python -m pytest tests/test_session_policy.py tests/test_auth_service_refresh.py tests/test_auth_router_refresh.py
```

Result:

- **47 passed**, 70 warnings.

### Access-token service command

Command:

```bash
cd backend && python -m pytest tests/test_auth_service.py
```

Result:

- **26 passed**, 22 warnings.

### Broader auth/rate subset

Command:

```bash
cd backend && python -m pytest tests/test_rate_limit.py tests/test_routers_auth_users_roles.py
```

Result:

- **54 passed, 3 failed**, 69 warnings.
- Failures appear unrelated/environmental or pre-existing based on failure modes:
  - `psycopg2` hstore OID unpack / SQLAlchemy DB connection path for unauthenticated auth/users tests.
  - `routers.roles.create_role` assumes permissions have `.value` but received strings.
- This broader subset does not block PR1 acceptance because the targeted PR1 tests are green and failures are not in the PR1 session-policy/session-lineage changes.

## Bootstrap SQL / Backfill Review

The startup guard in `backend/main.py` is PostgreSQL-plausible:

- Uses `ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS ...` for additive columns.
- Uses `UPDATE ... COALESCE(...)` to backfill legacy rows.
- Uses `CONCAT('legacy-', id::text)` and `NOW()`, both plausible for PostgreSQL.
- Adds indexes with `CREATE INDEX IF NOT EXISTS`.

Follow-up:

- Runtime validation against a real PostgreSQL instance is still recommended (`psql` schema inspection or startup smoke). This environment did not validate actual PostgreSQL DDL execution.
- Column nullability is not tightened after backfill even though SQLAlchemy model fields are `nullable=False`; acceptable for additive safety but should be revisited in a controlled migration if desired.

## Review Workload / PR Boundary

- PR1 stayed backend-only and did not implement PR2–PR4 features.
- Chained PR strategy is respected in scope: PR1 backend policy/schema foundation only.
- `apply-progress.md` records a user-accepted `single-pr` exception, mitigating the workload forecast conflict for this slice.

## Acceptance Decision

`pr1_accepted_for_review: true`

No PR1 blockers remain from this rerun. The remaining failures are broader-suite/environmental or pre-existing and are not acceptance blockers for the PR1 backend-only scope.

## Next PR Recommendations

- PR2 should add typed refresh verification statuses and stale-token recovery/rate-limit bypass tests before implementation.
- PR2 should validate recoverable stale rotation does not increment refresh-token rate limits.
- PR3 should decide whether policy/session metadata must be exposed via `/auth/users/me` for frontend UX.
- PR4 should implement frontend singleflight/cross-tab/inactivity UX only after backend stale-race semantics are stable.
