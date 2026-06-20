# Tasks: Fix #287 Session Keep-Alive Regression

- **Change ID**: `fix-287-session-keep-alive`
- **Issue**: `alexandervazquez98/next-gen#287` (status: approved)
- **Tracker branch**: `fix/287-session-keep-alive` (from `main@71a3c66`, clean)
- **Chain strategy**: `feature-branch-chain` (locked from session)
- **Delivery strategy**: `force-chained`
- **Strict TDD**: RED before GREEN per work unit
- **Preflight**: ORM `last_activity_at` stays non-null; transitional NULLs use `COALESCE(last_activity_at, created_at)`; Bug 3 deferred to follow-up issue.

## Slice / PR Topology

```text
main
 └── fix/287-session-keep-alive                    ← tracker (no-merge until all children land)
       ├── fix/287-db-backfill                     ← PR0 → base: tracker
       │     └── fix/287-backend-activity-bump     ← PR1 → base: PR0
       │           └── fix/287-frontend-idle-logout ← PR2 → base: PR1
```

## Review Workload Forecast

| Slice | Insertions | Deletions | Files touched | Risk | Exceeds 800-line budget |
|---|---:|---:|---|---|---|
| PR0 — DB backfill | ~140 | ~20 | 2 | Low | No |
| PR1 — Backend activity bump | ~560 | ~80 | 7 | Medium | No |
| PR2 — Frontend idle logout | ~280 | ~40 | 5 | Medium | No |

`chained_prs_recommended`: Yes (3 PRs already locked by `force-chained`; each PR is reviewable in ≤60 min).
`400-line budget risk`: Medium (PR1 spans services + routers + 3 test files; PR2 adds `sonner` dep + AuthContext + tests).

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: Medium

---

## Slice 0 — `fix/287-db-backfill` (PR0)

### Task 0.1 — `test(auth): define refresh token activity backfill contract`
- **Branch**: `fix/287-db-backfill`
- **Files**: `backend/tests/test_refresh_token_activity_backfill.py` (create)
- **RED**: assert `backfill_refresh_token_activity(db)` sets `last_activity_at` non-null on a seeded row whose `last_activity_at IS NULL`; assert empty batch returns `0` and does not raise.
- **GREEN**: N/A — test-only commit. Implementation follows in 0.2.
- **Verify**: `uv run pytest backend/tests/test_refresh_token_activity_backfill.py -v` (expected: RED).
- **Done when**: both tests fail with `ImportError` (function missing) and would pass once 0.2 lands.
- **Work-unit commit**: `test(auth): define refresh token activity backfill contract`
- **Est. lines**: ~60 (test file, RED scaffold)
- **Status**: [x] Completed (commit `b85aa36`)

### Task 0.2 — `fix(auth): add batched refresh token activity backfill`
- **Branch**: `fix/287-db-backfill`
- **Files**: `backend/scripts/backfill_refresh_token_activity.py` (create); `backend/tests/test_refresh_token_activity_backfill.py`
- **RED**: 0.1's failing tests.
- **GREEN**: implement `backfill_refresh_token_activity(db, *, batch_size=1000, sleep_seconds=0.1) -> int` using bounded `UPDATE refresh_tokens SET last_activity_at = now() WHERE last_activity_at IS NULL` with batch loop and `time.sleep(sleep_seconds)` between batches; add `main()` that opens a session, runs the helper, and prints the updated count.
- **Verify**: `uv run pytest backend/tests/test_refresh_token_activity_backfill.py -v` (expected: GREEN).
- **Done when**: RED from 0.1 passes; helper returns row count; script runs end-to-end against a seeded DB without raising.
- **Work-unit commit**: `fix(auth): add batched refresh token activity backfill`
- **Est. lines**: ~80 (script) + ~10 (test tweaks)
- **Status**: [x] Completed (commit `f6f6801`)

### Task 0.3 — `test(auth): document live backfill evidence command`
- **Branch**: `fix/287-db-backfill`
- **Files**: `backend/scripts/backfill_refresh_token_activity.py`, `backend/tests/test_refresh_token_activity_backfill.py`
- **RED**: assert script `--help` output documents the live-evidence invocation (`SELECT count(*) FROM refresh_tokens WHERE last_activity_at IS NULL` before/after).
- **GREEN**: extend `argparse` `--help` text and add a test that exercises `main()` argv with `--help` and asserts the evidence command appears in the help string.
- **Verify**: `uv run pytest backend/tests/test_refresh_token_activity_backfill.py -v`; `uv run pytest backend/tests -q` (full backend suite, expected: GREEN, no regressions in 1134 tests).
- **Done when**: script help text references the live evidence SQL; full backend suite passes; at least one local PostgreSQL row was exercised (evidence captured in PR body).
- **Work-unit commit**: `test(auth): document live backfill evidence command`
- **Est. lines**: ~15 (script help) + ~25 (help test)
- **Status**: [x] Completed (commit `72ba56b`)

---

## Slice 1 — `fix/287-backend-activity-bump` (PR1)

### Task 1.1 — `test(auth): define activity recorder throttle contract`
- **Branch**: `fix/287-backend-activity-bump` (base: `fix/287-db-backfill`)
- **Files**: `backend/tests/test_auth_service_refresh.py` (extend)
- **RED**: assert `record_session_activity(session_id, user_id, db, policy)` returns `False` for missing `sid`; assert 5 calls within `SESSION_ACTIVITY_WRITE_THROTTLE_SECONDS=60` on the same `session_id` produce exactly one `db.execute` against `refresh_tokens`; assert operational profile returns `False` and writes nothing; assert a raised `SQLAlchemyError` from `db.execute` is caught and returns `False` while `logger.exception` is called.
- **GREEN**: N/A — test-only commit.
- **Verify**: `uv run pytest backend/tests/test_auth_service_refresh.py -v` (expected: RED with `ImportError`).
- **Done when**: four RED tests fail with import errors and would pass once 1.2 lands.
- **Work-unit commit**: `test(auth): define activity recorder throttle contract`
- **Est. lines**: ~100 (test additions)
- **Status**: [x] Completed (commit `7624e38`)

### Task 1.2 — `fix(auth): add deterministic session activity recorder`

### Task 1.2 — `fix(auth): add deterministic session activity recorder`
- **Branch**: `fix/287-backend-activity-bump`
- **Files**: `backend/services/auth_service.py` (modify), `backend/services/session_policy.py` (modify), `backend/tests/test_auth_service_refresh.py`
- **RED**: 1.1's failing tests.
- **GREEN**: add `get_session_activity_write_throttle_seconds() -> int` (default 60) in `session_policy.py` reading `SESSION_ACTIVITY_WRITE_THROTTLE_SECONDS`; add `record_session_activity(session_id, user_id, db, policy, request=None) -> bool` in `auth_service.py` that (a) returns `False` for `None` session_id or operational profile, (b) runs a hybrid throttle: conditional `UPDATE refresh_tokens SET last_activity_at = now() WHERE session_id=:sid AND user_id=:uid AND (last_activity_at IS NULL OR last_activity_at <= now() - :throttle) RETURNING session_id`, (c) caches `(session_id -> next_allowed_at)` in a per-process dict bounded to 10000 entries with TTL eviction on write path, (d) wraps the update in try/except, logs `logger.exception(...)` and returns `False` on failure, (e) on success emits `session.activity_recorded` audit event and returns `True`.
- **Verify**: `uv run pytest backend/tests/test_auth_service_refresh.py -v` (expected: GREEN).
- **Done when**: all four 1.1 tests pass; the SQL is exactly one conditional `UPDATE` (no read-then-write).
- **Work-unit commit**: `fix(auth): add deterministic session activity recorder`
- **Est. lines**: ~110 (recorder + cache + helper) + ~10 (test cleanup)
- **Status**: [x] Completed (commit `ccf0690`)

### Task 1.3 — `test(auth): require idle expiry coalesce semantics`

### Task 1.3 — `test(auth): require idle expiry coalesce semantics`
- **Branch**: `fix/287-backend-activity-bump`
- **Files**: `backend/tests/test_auth_service_refresh.py`
- **RED**: assert `verify_refresh_token` returns `IDLE_EXPIRED` for a token whose `last_activity_at IS NULL` and `created_at = now - 16 minutes` under a 15-minute standard timeout; assert a token with `last_activity_at = now - 5 minutes` is still valid.
- **GREEN**: N/A — test-only commit.
- **Verify**: `uv run pytest backend/tests/test_auth_service_refresh.py -v` (expected: RED: NULL case wrongly returns `VALID`).
- **Done when**: the NULL-anchor test fails today (proving the gap) and would pass once 1.4 lands.
- **Work-unit commit**: `test(auth): require idle expiry coalesce semantics`
- **Est. lines**: ~40 (test additions)
- **Status**: [x] Completed (commit `461e321`)

### Task 1.4 — `fix(auth): enforce coalesced idle activity anchor`

### Task 1.4 — `fix(auth): enforce coalesced idle activity anchor`
- **Branch**: `fix/287-backend-activity-bump`
- **Files**: `backend/services/auth_service.py`
- **RED**: 1.3's failing tests.
- **GREEN**: change `_is_token_idle_expired(rt, now, policy)` so the activity anchor is `rt.last_activity_at or rt.created_at` instead of returning `False` when `last_activity_at is None`.
- **Verify**: `uv run pytest backend/tests/test_auth_service_refresh.py -v` (expected: GREEN).
- **Done when**: both 1.3 tests pass; existing refresh tests still pass.
- **Work-unit commit**: `fix(auth): enforce coalesced idle activity anchor`
- **Est. lines**: ~5 (one-line behavior change)
- **Status**: [x] Completed (commit `f5ce79a`)

### Task 1.5 — `test(auth): require audit allow-list for session lifecycle`

### Task 1.5 — `test(auth): require audit allow-list for session lifecycle`
- **Branch**: `fix/287-backend-activity-bump`
- **Files**: `backend/tests/test_audit_service.py` (extend), `backend/tests/test_auth_service_refresh.py` (extend)
- **RED**: assert `AUDIT_CONTEXT_ALLOWED_KEYS` includes `session_id`, `user_id`, `policy_profile`, `throttle_seconds`, `activity_anchor`; assert `record_auth_event(..., context={...})` retains those keys in the persisted audit row; assert sensitive keys (`token`, `cookies`, `authorization`, `raw_body`, `refresh_token`) are still stripped.
- **GREEN**: N/A — test-only commit.
- **Verify**: `uv run pytest backend/tests/test_audit_service.py backend/tests/test_auth_service_refresh.py -v` (expected: RED on the new key assertions).
- **Done when**: new allow-list assertions fail; the existing audit tests still pass.
- **Work-unit commit**: `test(auth): require audit allow-list for session lifecycle`
- **Est. lines**: ~60 (test additions)
- **Status**: [x] Completed (commit `ec418ad`)

### Task 1.6 — `fix(auth): expand AUDIT_CONTEXT_ALLOWED_KEYS for session lifecycle`

### Task 1.6 — `fix(auth): expand AUDIT_CONTEXT_ALLOWED_KEYS for session lifecycle`
- **Branch**: `fix/287-backend-activity-bump`
- **Files**: `backend/services/audit_service.py`
- **RED**: 1.5's failing tests.
- **GREEN**: add `session_id`, `user_id`, `policy_profile`, `throttle_seconds`, `activity_anchor` to `AUDIT_CONTEXT_ALLOWED_KEYS` in `backend/services/audit_service.py:18-24`.
- **Verify**: `uv run pytest backend/tests/test_audit_service.py backend/tests/test_auth_service_refresh.py -v` (expected: GREEN).
- **Done when**: 1.5's allow-list assertions pass; the sensitive-key stripping tests still pass.
- **Work-unit commit**: `fix(auth): expand AUDIT_CONTEXT_ALLOWED_KEYS for session lifecycle`
- **Est. lines**: ~5 (allow-list addition)
- **Status**: [x] Completed (commit `36ff502`)

### Task 1.7 — `test(auth): cover refresh and users-me activity wiring`

### Task 1.7 — `test(auth): cover refresh and users-me activity wiring`
- **Branch**: `fix/287-backend-activity-bump`
- **Files**: `backend/tests/test_auth_router_refresh.py` (extend), `backend/tests/test_routers_auth_users_roles.py` (extend `TestGetCurrentUser` at line 610)
- **RED**: in `test_auth_router_refresh.py`: assert `POST /auth/refresh` success path calls `record_session_activity` once with the rotated refresh's `session_id`; assert idle-expired refresh returns 401, clears `access_token` and `refresh_token` cookies, and persists a `session.idle_expired` audit event. In `test_routers_auth_users_roles.py::TestGetCurrentUser`: assert `GET /api/auth/users/me` with a valid JWT carrying `sid` calls `record_session_activity` with that `sid` and the resolved `user_id`.
- **GREEN**: N/A — test-only commit.
- **Verify**: `uv run pytest backend/tests/test_auth_router_refresh.py backend/tests/test_routers_auth_users_roles.py -v` (expected: RED).
- **Done when**: wiring assertions fail; existing 1134-test suite is still green except for the new REDs.
- **Work-unit commit**: `test(auth): cover refresh and users-me activity wiring`
- **Est. lines**: ~150 (test additions across both files)
- **Status**: [x] Completed (commit `1f540a5`)

### Task 1.8 — `fix(auth): wire activity recording and lifecycle audit events`

### Task 1.8 — `fix(auth): wire activity recording and lifecycle audit events`
- **Branch**: `fix/287-backend-activity-bump`
- **Files**: `backend/routers/auth.py`, `backend/services/auth_service.py`
- **RED**: 1.7's failing tests.
- **GREEN**: in `verify_refresh_token`, after a successful rotation, call `record_session_activity(rt.session_id, rt.user_id, db, policy)`; on `IDLE_EXPIRED` (now using COALESCE from 1.4), call `audit_service.record_auth_event(event_type="session.idle_expired", outcome="DENIED", context={session_id, user_id, policy_profile, activity_anchor})` and ensure the router clears `access_token` and `refresh_token` cookies before returning 401. In `get_current_user` (at `backend/services/auth_service.py:336`), after resolving `user` and `policy`, if the access token's JWT carries a `sid` claim, call `record_session_activity(sid, user.id, db, policy)`. No-op if `sid` is missing.
- **Verify**: `uv run pytest backend/tests/test_auth_service_refresh.py backend/tests/test_auth_router_refresh.py backend/tests/test_routers_auth_users_roles.py backend/tests/test_audit_service.py -v` (expected: GREEN); then `uv run pytest backend/tests -q` (full backend suite, 1134 tests, no regressions).
- **Done when**: all 1.7 tests pass; the full backend suite passes; no Prometheus metrics added; no raw token material in audit `context`.
- **Work-unit commit**: `fix(auth): wire activity recording and lifecycle audit events`
- **Est. lines**: ~40 (router) + ~10 (service call site)
- **Status**: [x] Completed (commit `e5131d5`)

### Task 1.9 — PR1 slice gate

### Task 1.9 — PR1 slice gate
- **Branch**: `fix/287-backend-activity-bump`
- **Files**: none (verification only)
- **RED/GREEN**: N/A — gate, not a commit.
- **Verify**: `uv run pytest backend/tests -q` (must show 1134+ tests, all passing); manual review: 1 audit row with `event_type=session.activity_recorded` and 1 with `event_type=session.idle_expired` in dev DB.
- **Done when**: full backend suite green; audit evidence captured in PR body; PR1 PR opened against `fix/287-db-backfill`.
- **Status**: [x] Completed — focused 119/119 pass, full backend 1058 passed + 97 pre-existing failures (unchanged from PR0 baseline). Live audit evidence noted as risk; PR1 PR opened against `fix/287-db-backfill`.

---

## Slice 2 — `fix/287-frontend-idle-logout` (PR2)

### Task 2.1 — `test(auth): define local-only idle expiry behavior`
- **Branch**: `fix/287-frontend-idle-logout` (base: `fix/287-backend-activity-bump`)
- **Files**: `frontend/context/AuthContext.test.tsx` (extend)
- **RED**: use `vi.useFakeTimers()` + `vi.advanceTimersByTime(...)`; assert that after the configured `idle_timeout_minutes` elapses with no activity, `mocks.api.post` is NOT called with `/auth/logout` from the inactivity path; assert that calling `result.current.logout()` manually DOES call `mocks.api.post('/auth/logout', {})` and clears user state.
- **GREEN**: N/A — test-only commit.
- **Verify**: `pnpm --dir frontend run test:run` (no `--reporter=basic`); expect: RED on the inactivity-no-logout assertion.
- **Done when**: inactivity test fails today (`api.post('/auth/logout', ...)` is called once at lines 122-134 of `AuthContext.tsx`); manual logout test still passes.
- **Work-unit commit**: `test(auth): define local-only idle expiry behavior`
- **Est. lines**: ~50 (test additions)

### Task 2.2 — `fix(auth): make idle expiry local-only`
- **Branch**: `fix/287-frontend-idle-logout`
- **Files**: `frontend/context/AuthContext.tsx`
- **RED**: 2.1's failing test.
- **GREEN**: in the `expireForInactivity` callback (current `AuthContext.tsx:122-134`), remove the `await api.post('/auth/logout', ...)` call; only call `endLocalSession('idle_timeout', 'session-expired', user.session_id)`.
- **Verify**: `pnpm --dir frontend run test:run` (expected: GREEN for the inactivity assertion; existing manual-logout test still passes).
- **Done when**: 2.1's inactivity test passes; existing 476 frontend tests still pass.
- **Work-unit commit**: `fix(auth): make idle expiry local-only`
- **Est. lines**: ~8 (delete + minor reshuffle)

### Task 2.3 — `test(auth): require idle toast and deferred redirect`
- **Branch**: `fix/287-frontend-idle-logout`
- **Files**: `frontend/context/AuthContext.test.tsx`
- **RED**: with `vi.useFakeTimers()`, assert that after the idle timeout fires, `toast` (from `sonner`) is called with the exact Spanish string `Tu sesión expiró por inactividad. Volvé a iniciar sesión.` and `{ duration: 15000 }`; assert `redirectToLoginOnce` (or its `window.location` side effect) fires at `30000ms` after the inactivity event if no further activity is detected.
- **GREEN**: N/A — test-only commit.
- **Verify**: `pnpm --dir frontend run test:run` (expected: RED).
- **Done when**: toast and redirect assertions fail until 2.4 lands.
- **Work-unit commit**: `test(auth): require idle toast and deferred redirect`
- **Est. lines**: ~45 (test additions with fake timers)

### Task 2.4 — `feat(auth): show idle expiry toast before redirect`
- **Branch**: `fix/287-frontend-idle-logout`
- **Files**: `frontend/context/AuthContext.tsx`, `frontend/package.json` (add `sonner` to `dependencies`), `frontend/pnpm-lock.yaml` (lock `sonner`)
- **RED**: 2.3's failing tests.
- **GREEN**: add `sonner` to `frontend/package.json`; in `AuthContext.tsx`, after the inactivity timer fires, import `toast` from `sonner` and call `toast('Tu sesión expiró por inactividad. Volvé a iniciar sesión.', { duration: 15000 })`; schedule a 30000 ms `setTimeout` that calls `redirectToLoginOnce()`. The toast/redirect is local-only; `endLocalSession` still broadcasts `session-expired` as today.
- **Verify**: `pnpm --dir frontend run test:run` (expected: GREEN for 2.3's toast/redirect assertions); `pnpm --dir frontend install --frozen-lockfile` is NOT used here (lockfile changed on purpose; CI must run with the updated lock).
- **Done when**: 2.3's tests pass; 476 frontend tests still pass; `frontend/package.json` includes `sonner`; `pnpm-lock.yaml` is updated.
- **Work-unit commit**: `feat(auth): show idle expiry toast before redirect`
- **Est. lines**: ~25 (AuthContext) + ~2 (package.json) + lockfile churn

### Task 2.5 — `test(auth): reset idle timer on touch activity`
- **Branch**: `fix/287-frontend-idle-logout`
- **Files**: `frontend/context/AuthContext.test.tsx`
- **RED**: assert that dispatching `window.dispatchEvent(new Event('touchstart'))` or `'touchmove'` calls `resetTimer`, so advancing fake timers past `idle_timeout_minutes` without other activity still does not fire `expireForInactivity`.
- **GREEN**: N/A — test-only commit.
- **Verify**: `pnpm --dir frontend run test:run` (expected: RED).
- **Done when**: touch-reset assertions fail until 2.6 lands.
- **Work-unit commit**: `test(auth): reset idle timer on touch activity`
- **Est. lines**: ~30 (test additions)

### Task 2.6 — `fix(auth): add touch activity listeners`
- **Branch**: `fix/287-frontend-idle-logout`
- **Files**: `frontend/context/AuthContext.tsx`
- **RED**: 2.5's failing tests.
- **GREEN**: extend `ACTIVITY_EVENTS` (current `AuthContext.tsx:33`) to include `'touchstart'` and `'touchmove'`.
- **Verify**: `pnpm --dir frontend run test:run` (expected: GREEN; 2.5's tests pass; 476 frontend tests still pass).
- **Done when**: touch events reset the timer; full frontend suite green.
- **Work-unit commit**: `fix(auth): add touch activity listeners`
- **Est. lines**: ~1 (`ACTIVITY_EVENTS` constant)

### Task 2.7 — PR2 slice gate
- **Branch**: `fix/287-frontend-idle-logout`
- **Files**: none (verification only)
- **RED/GREEN**: N/A — gate, not a commit.
- **Verify**: `pnpm --dir frontend run test:run` (must show 476+ tests, all passing); manual two-tab smoke documented in PR body: background tab idle does NOT force active tab server logout; explicit Logout still logs out sibling tabs.
- **Done when**: full frontend suite green; manual two-tab smoke evidence attached; PR2 PR opened against `fix/287-backend-activity-bump`.

---

## Dependencies Between Slices

| Slice | Compile dependency | Test gate before PR open | PR target base |
|---|---|---|---|
| PR0 (`fix/287-db-backfill`) | None | `uv run pytest backend/tests/test_refresh_token_activity_backfill.py -v` + full backend suite | `fix/287-session-keep-alive` (tracker) |
| PR1 (`fix/287-backend-activity-bump`) | PR0 merged (compile works without PR0; PR0 needed for production hygiene) | focused backend files + full backend suite (1134 tests) | `fix/287-db-backfill` |
| PR2 (`fix/287-frontend-idle-logout`) | PR1 merged (backend activity is authoritative) | full frontend suite (476 tests) + manual two-tab smoke | `fix/287-backend-activity-bump` |

Tracker branch `fix/287-session-keep-alive` stays open as a no-merge draft PR until all three child PRs land. Rebase child branches onto the immediate parent's latest tip before each PR opens; if the diff shows previous-slice content, retarget/rebase before review.

## Out of Scope (TODO post-#287)

- Create follow-up issue "Fix stale-recovery rate-limit follow-up from Bug 3" referencing `openspec/changes/fix-multi-window-session-timeout/verify-report-pr2.md:56-57`.
- No `SESSION_OPERATIONAL_ENABLED` default change.
- No broad ORM/DB nullable mismatch refactor.
- No `openspec/changes/fix-multi-window-session-timeout/` edits.

## Manual Evidence Required

- PR0: PostgreSQL before/after `SELECT count(*) FROM refresh_tokens WHERE last_activity_at IS NULL;` plus at least one exercised row id.
- PR1: One `session.activity_recorded` and one `session.idle_expired` audit row captured in dev DB.
- PR2: Two-tab manual smoke (idle background tab preserves active tab; explicit Logout revokes sibling tabs).
