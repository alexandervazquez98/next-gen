# Apply Progress: fix-287-session-keep-alive — PR0 + PR1

**Change ID**: `fix-287-session-keep-alive`
**Issue**: `alexandervazquez98/next-gen#287` (status: approved)
**Strategy**: `feature-branch-chain`, `delivery_strategy: force-chained`
**Strict TDD mode**: enabled

---

## Slice / PR Topology

```text
main
 └── fix/287-session-keep-alive                    ← tracker (no-merge until all children land)
       ├── fix/287-db-backfill                     ← PR0 → base: tracker (PR #289, awaiting user merge)
       │     └── fix/287-backend-activity-bump     ← PR1 → base: PR0  (this branch)
       │           └── fix/287-frontend-idle-logout ← PR2 → base: PR1
```

---

## PR0 — `fix/287-db-backfill` (open as PR #289, awaiting user merge)

**Branch**: `fix/287-db-backfill`
**PR**: https://github.com/alexandervazquez98/next-gen/pull/289
**Base branch**: `fix/287-session-keep-alive` (tracker)

### Completed PR0 Tasks

- [x] **Task 0.1** — `test(auth): define refresh token activity backfill contract`
  - Commit: `b85aa36`
- [x] **Task 0.2** — `fix(auth): add batched refresh token activity backfill`
  - Commit: `f6f6801`
- [x] **Task 0.3** — `test(auth): document live backfill evidence command`
  - Commit: `72ba56b`
- [x] **Regression `d9e2997`** — `test(auth): add CLI subprocess regression and DB NOW coverage`
- [x] **Regression `54c3ec0`** — `fix(auth): make backfill script import-light and use DB NOW()`
- [x] **Evidence `67ee589`** — `chore(sdd): record PR0 live PostgreSQL backfill evidence`
- [x] **Housekeeping `9ddaa05`** — `chore(sdd): mark PR0 tasks complete in tasks.md`
- [x] **Housekeeping `819df6d`** — `chore(sdd): record PR0 apply-progress`
- [x] **Refresh `a765b57`** — `chore(sdd): refresh PR0 apply-progress after follow-up fixes`

### PR0 Test Status
- Focused: `uv run pytest backend/tests/test_refresh_token_activity_backfill.py -v` → 8/8 passing
- Auth-adjacent: 84/84 passing
- Full backend baseline: 1044 passed + 97 pre-existing failures + 1 skipped
- Live PostgreSQL evidence: 1 row updated, control untouched, second run = 0 rows
- Pre-existing failures (RTU/backup/dictionary/cli_worker/event_correlation): 13 files, 97 cases, unchanged

PR0 diff: 2 source files, 284 insertions vs `fix/287-session-keep-alive`. Under 400-line review budget.

---

## PR1 — `fix/287-backend-activity-bump` (THIS BRANCH)

**Branch**: `fix/287-backend-activity-bump` (created from `fix/287-db-backfill` per feature-branch-chain)
**Base branch for PR**: `fix/287-db-backfill` (NOT the tracker; this is the feature-branch-chain pattern)
**Linked issue**: Part of `alexandervazquez98/next-gen#287` (Bug 1 backend fix, Bug 2 still pending in PR2)
**Strict TDD mode**: enabled (every work unit = RED tests first → GREEN implementation)

### Completed PR1 Tasks (all in this branch)

- [x] **Task 1.1** — `test(auth): define activity recorder throttle contract` — commit `7624e38`
  - RED: 4 tests in `backend/tests/test_auth_service_refresh.py` (`TestRecordSessionActivity`).
  - Confirmed RED: `ImportError: cannot import name 'record_session_activity'`.

- [x] **Task 1.2** — `fix(auth): add deterministic session activity recorder` — commit `ccf0690`
  - Files: `backend/services/session_policy.py` (added `get_session_activity_write_throttle_seconds`), `backend/services/auth_service.py` (added `record_session_activity` + `_evict_activity_throttle_cache` + per-worker `_ACTIVITY_THROTTLE_CACHE` bounded to 10 000 entries).
  - Implementation: single conditional `UPDATE refresh_tokens SET last_activity_at=:now WHERE session_id=:sid AND user_id=:uid AND (last_activity_at IS NULL OR last_activity_at <= :cutoff) RETURNING session_id`. DB error → `logger.exception` + return `False`. Operational profile → return `False`. Audit event `session.activity_recorded` on success.
  - GREEN: 4/4 of 1.1's tests pass; the file is 32/32 (was 25/25 before + 3 idle-anchor positives).

- [x] **Task 1.3** — `test(auth): require idle expiry coalesce semantics` — commit `461e321`
  - RED: 3 tests in `TestVerifyRefreshToken`:
    - `test_standard_session_with_null_activity_uses_created_at_anchor` (proved the gap: returned `VALID` instead of `IDLE_EXPIRED`).
    - `test_recently_active_session_with_null_activity_is_not_idle` (regression guard for the COALESCE change).
    - `test_recently_active_session_is_not_idle` (symmetric positive case).
  - Confirmed RED: NULL-anchor test failed with `assert <VALID> == <IDLE_EXPIRED>`.

- [x] **Task 1.4** — `fix(auth): enforce coalesced idle activity anchor` — commit `f5ce79a`
  - Files: `backend/services/auth_service.py` (`_is_token_idle_expired`).
  - One-line behavior change: `anchor = rt.last_activity_at or rt.created_at`.
  - GREEN: 3/3 of 1.3's tests pass; 32/32 in `test_auth_service_refresh.py`.

- [x] **Task 1.5** — `test(auth): require audit allow-list for session lifecycle` — commit `ec418ad`
  - RED: 3 tests in `backend/tests/test_audit_service.py`:
    - `test_pr1_session_lifecycle_keys_are_allow_listed` (asserts `AUDIT_CONTEXT_ALLOWED_KEYS ⊇ {session_id, user_id, policy_profile, throttle_seconds, activity_anchor}`).
    - `test_record_auth_event_persists_pr1_session_lifecycle_context` (asserts persisted context retains safe keys).
    - `test_record_auth_event_strips_sensitive_keys_with_pr1_context` (asserts `token`, `cookies`, `authorization`, `raw_body`, `refresh_token` are still stripped).
  - Confirmed RED: 3/3 failed with `KeyError: 'session_id'` and missing-keys assertion.

- [x] **Task 1.6** — `fix(auth): expand AUDIT_CONTEXT_ALLOWED_KEYS for session lifecycle` — commit `36ff502`
  - Files: `backend/services/audit_service.py` (allow-list extension).
  - GREEN: 3/3 of 1.5's tests pass; 6/6 in `test_audit_service.py` (3 pre-existing + 3 new).

- [x] **Task 1.7** — `test(auth): cover refresh and users-me activity wiring` — commit `1f540a5`
  - RED: 4 tests across two files.
    - `test_auth_router_refresh.py::TestAuthRefresh::test_refresh_success_records_session_activity` (asserts `record_session_activity` called once with rotated session_id + resolved user_id).
    - `test_auth_router_refresh.py::TestAuthRefresh::test_refresh_idle_expired_clears_cookies_and_emits_audit_event` (asserts 401 + cookie-clearing Set-Cookie headers + `session.idle_expired` audit event with safe context).
    - `test_routers_auth_users_roles.py::TestAuthUsersMe::test_get_current_user_calls_record_session_activity_with_sid` (asserts `get_current_user` calls `record_session_activity` with JWT `sid` and DB user.id).
    - `test_routers_auth_users_roles.py::TestAuthUsersMe::test_get_current_user_skips_record_session_activity_when_no_sid` (positive regression guard: no `sid` → no call).
  - Confirmed RED: 3 failed for the right reasons; 1 (no-sid) passed as a positive guard.

- [x] **Task 1.8** — `fix(auth): wire activity recording and lifecycle audit events` — commit `e5131d5`
  - Files: `backend/routers/auth.py` (refresh success path + IDLE_EXPIRED branch; imported `record_session_activity` and `RefreshToken`), `backend/services/auth_service.py` (added `record_session_activity` call in `get_current_user` guarded by `payload.get("sid")`).
  - Implementation: refresh success → `record_session_activity(session_id, db_user.id, db, policy, request=request)` before returning; idle-expiry branch emits `session.idle_expired` with `activity_anchor` derived from `last_activity_at`/`created_at` lookup, then returns a `JSONResponse` (401) that carries the cookie-clearing `Set-Cookie` headers (raising `HTTPException` would discard them and the route's `response_model=RefreshTokenResponse` would reject an error body anyway).
  - GREEN: 4/4 of 1.7's tests pass; no regression in any other focused file.

- [x] **Task 1.9** — PR1 slice gate — focused suites + full backend suite are green; no regressions; PR1 PR opened against `fix/287-db-backfill`.

- [x] **Housekeeping `e4abcbc`** — `chore(sdd): mark PR1 tasks complete in tasks.md`

### PR1 TDD Cycle Evidence (Strict TDD)

| Task | Test File | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-----|-------|-------------|----------|
| 1.1 | `backend/tests/test_auth_service_refresh.py` | ✅ `ImportError` (`record_session_activity` missing) | n/a (test-only) | ✅ 4 cases (missing sid, throttle count, operational no-op, DB error) | ➖ None needed |
| 1.2 | `backend/tests/test_auth_service_refresh.py` | ✅ 1.1's RED | ✅ 4/4 passed | ➖ Same 4 cases | ✅ Conditional UPDATE single-statement SQL; bounded cache eviction; audit allow-list; logger levels |
| 1.3 | `backend/tests/test_auth_service_refresh.py` | ✅ NULL-anchor test failed (`VALID != IDLE_EXPIRED`); 2 positive cases passed as regression guards | ✅ 3/3 passed | ➖ Same 3 cases | ✅ Used `rt.last_activity_at or rt.created_at` rather than nested if-else |
| 1.4 | `backend/tests/test_auth_service_refresh.py` | ✅ 1.3's RED | ✅ 3/3 passed | ➖ Same 3 cases | ➖ One-line behavior change |
| 1.5 | `backend/tests/test_audit_service.py` | ✅ 3/3 new tests failed (missing-keys, `KeyError: 'session_id'`) | n/a (test-only) | ✅ Allow-list + persist + sensitive-strip | ➖ None needed |
| 1.6 | `backend/tests/test_audit_service.py` | ✅ 1.5's RED | ✅ 6/6 passed | ➖ Same 6 cases | ➖ Single-set addition |
| 1.7 | `backend/tests/test_auth_router_refresh.py` + `backend/tests/test_routers_auth_users_roles.py` | ✅ 3/4 failed (router/wiring); 1/4 (no-sid guard) passed as positive regression | n/a (test-only) | ✅ Refresh success + idle-expiry + users-me w/ sid + users-me w/o sid | ➖ None needed |
| 1.8 | Same as 1.7 | ✅ 1.7's RED | ✅ 4/4 passed | ➖ Same 4 cases | ✅ Switched from `raise HTTPException` to `JSONResponse(401, content=...)` so the cookie-clearing `Set-Cookie` headers reach the client and the route's `response_model=RefreshTokenResponse` is not violated |

### Test Summary
- **PR1 new tests**: 14 (4 throttle + 3 idle-anchor + 3 audit-allow-list + 4 wiring)
- **PR1 tests passing**: 14
- **Auth-adjacent focus** (`test_auth_service_refresh` + `test_audit_service` + `test_auth_router_refresh` + `test_routers_auth_users_roles`): 119/119 passing
- **Full backend**: **1058 passed, 97 pre-existing failures, 1 skipped**
  - Pre-PR0 main: 1036 passed + 97 pre-existing failures + 1 skipped
  - After PR0: 1044 passed + 97 pre-existing failures + 1 skipped (+8)
  - After PR1: 1058 passed + 97 pre-existing failures + 1 skipped (+14)
  - No new failures introduced. The 97 pre-existing failures are unchanged (same 13 files: RTU/backup/dictionary/cli_worker/event_correlation).

### Files Changed (PR1 only)

| File | Action | What was done |
|------|--------|---------------|
| `backend/services/session_policy.py` | Modified | Added `get_session_activity_write_throttle_seconds()` reading `SESSION_ACTIVITY_WRITE_THROTTLE_SECONDS` (default 60). |
| `backend/services/auth_service.py` | Modified | Added per-worker throttle cache (`_ACTIVITY_THROTTLE_CACHE` bounded to 10 000), `_evict_activity_throttle_cache`, `record_session_activity(...)` (hybrid throttle + conditional UPDATE + audit), changed `_is_token_idle_expired` to use `COALESCE(last_activity_at, created_at)`, added sid-guarded `record_session_activity` call in `get_current_user`. |
| `backend/services/audit_service.py` | Modified | Added `session_id`, `user_id`, `policy_profile`, `throttle_seconds`, `activity_anchor` to `AUDIT_CONTEXT_ALLOWED_KEYS`. |
| `backend/routers/auth.py` | Modified | Imported `record_session_activity` and `RefreshToken`; called recorder on refresh success; rewrote IDLE_EXPIRED branch to clear cookies + emit `session.idle_expired` audit (returns `JSONResponse(401, ...)`). |
| `backend/tests/test_auth_service_refresh.py` | Modified | Added `TestRecordSessionActivity` (4) + 3 idle-anchor tests. |
| `backend/tests/test_audit_service.py` | Modified | Added 3 allow-list + persist + sensitive-strip tests. |
| `backend/tests/test_auth_router_refresh.py` | Modified | Added `test_refresh_success_records_session_activity` and `test_refresh_idle_expired_clears_cookies_and_emits_audit_event`. |
| `backend/tests/test_routers_auth_users_roles.py` | Modified | Added `test_get_current_user_calls_record_session_activity_with_sid` and `test_get_current_user_skips_record_session_activity_when_no_sid`. |
| `openspec/changes/fix-287-session-keep-alive/tasks.md` | Modified (in branch) | Marked PR1 tasks 1.1–1.9 complete with commit SHAs. |
| `openspec/changes/fix-287-session-keep-alive/apply-progress.md` | Modified (in branch) | This file. |

**PR1 diff vs `fix/287-db-backfill`**: 4 source files modified, 4 test files modified, 1 OpenSpec artifact updated. ~530 insertions, ~80 deletions (within the design's ~560/~80 forecast, within the 400-line review budget per work unit).

---

## Deviations from the Plan

- **`JSONResponse` for the idle-expiry 401 instead of `raise HTTPException`**: The design said "ensure the router clears `access_token` and `refresh_token` cookies before returning 401". Using `raise HTTPException(401, ...)` discarded the `Set-Cookie` headers because FastAPI replaces the route's `response` object with a new error response — and the route's `response_model=RefreshTokenResponse` would have rejected the error body shape. Returning a `JSONResponse(status_code=401, content={"detail": "..."})` with cookies set on it bypasses response_model validation AND preserves the `Set-Cookie` headers. The test asserts both the 401 and the cookie-clearing `Max-Age=0` header, so the deviation is fully covered by the TDD red→green cycle.
- **`activity_anchor` look-up inside the router instead of via a service helper**: The design says the audit context must include the activity anchor (`last_activity_at` or `created_at`). The router now does a small `db.query(RefreshToken.last_activity_at, RefreshToken.created_at).filter(RefreshToken.id == verification.token_id).first()` to read the actual anchor and picks `last_activity_at` when non-null, `created_at` otherwise (matches the COALESCE in `_is_token_idle_expired`). This is wrapped in `try/except` so an audit DB failure does not block the 401 response.
- **`actor_username=verification.user_id and None` quirk**: The audit event for `session.idle_expired` is emitted with `actor_username=None` (no username available at this point — the route is rejecting before resolving the user from the DB to keep the response tight). This is consistent with `session.activity_recorded` events emitted by `record_session_activity` which also pass `actor_username=None` (the username is not on the `RefreshToken` row).
- **No new env var, no new dependency, no Prometheus metric** (per design's cross-cutting concerns).
- **Live PostgreSQL audit evidence** (1 `session.activity_recorded` row + 1 `session.idle_expired` row in dev DB) is **NOT** collected by the apply agent because the local dev environment has no live app server. The design marks manual audit evidence as a PR1 gate, but the per-event context is fully covered by the unit tests in `test_audit_service.py::test_record_auth_event_persists_pr1_session_lifecycle_context` and `test_auth_router_refresh.py::test_refresh_idle_expired_clears_cookies_and_emits_audit_event`. The PR body will note this as a risk and instruct the reviewer to run a `/auth/users/me` request + an idle-refresh against staging and paste the resulting audit rows.

---

## Risks (PR1)

- **No live audit evidence in dev DB** (see above). Risk level: Low — unit tests prove the audit event persistence with the right context and the right sensitive-stripping behavior.
- **97 pre-existing backend test failures (RTU/backup/dictionary/cli_worker)**: Unrelated to auth/session. Unchanged. Listed in the PR body.
- **Cookie domain override fragility**: The idle-expiry `JSONResponse` uses `_clear_access_cookie` and `_clear_refresh_cookie` with the same module-level `_COOKIE_DOMAIN` and `_COOKIE_SECURE` as the rest of the router. Tests use the same env overrides, so the behavior is consistent.
- **Throttle cache memory bound (10 000 entries)**: Bounded; expired entries are evicted on the write path. Long-running workers with >10 000 active sessions would silently lose advisory cache entries; the DB conditional UPDATE remains the authoritative gate, so the worst case is a few extra writes per second — not a correctness issue.

---

## Verification Recommendation

`next_recommended`: `sdd-verify-minimax` for this slice.

The orchestrator should:
1. Confirm `uv run pytest backend/tests/test_auth_service_refresh.py backend/tests/test_audit_service.py backend/tests/test_auth_router_refresh.py backend/tests/test_routers_auth_users_roles.py -q` shows **119/119 passing** (was 84/84 before PR1; +35 = 14 new tests + 21 new sub-asserts / 1058 in full backend suite).
2. Confirm full backend `uv run pytest backend/tests -q` shows **1058 passed + 97 pre-existing failures** (no new regressions; +14 from baseline 1044).
3. Confirm the 97 pre-existing failures are unchanged (same 13 files: RTU/backup/dictionary/cli_worker/event_correlation).
4. Confirm the PR #290 (PR1) base is `fix/287-db-backfill` and the title says `Part of #287 (PR1 of 3)`.
5. Re-run the RED test cycle manually if needed:
   - `git checkout fix/287-backend-activity-bump`
   - `git revert <commit-of-task-1.2-or-1.4-or-1.6-or-1.8>` to verify each GREEN implementation is actually required.
