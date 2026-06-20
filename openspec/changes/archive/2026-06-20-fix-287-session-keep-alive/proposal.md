# Proposal: Fix #287 Session Keep-Alive Regression

Status: Draft  
Change ID: `fix-287-session-keep-alive`  
GitHub Issue: `alexandervazquez98/next-gen#287` (`status:approved`)  
Extends: `#188` / `openspec/changes/fix-multi-window-session-timeout/` without editing that change.

## Intent

Fix two production-visible regressions left by the #188 chain/PR6 gap:

- **Bug 1:** authenticated activity does not update `refresh_tokens.last_activity_at`; active users on static pages can be timed out or kept alive only by refresh cadence, not real activity.
- **Bug 2:** frontend idle expiry calls `POST /auth/logout`, which revokes the whole refresh-token family and logs out active sibling tabs.

Backend remains authoritative for inactivity. Frontend idle handling becomes UX-only local cleanup plus cross-tab broadcast. Explicit click **Logout** continues to revoke the full family.

## Scope

### PR0 — DB-only backfill (`fix/287-db-backfill`)
- Add batched deployment backfill: `UPDATE refresh_tokens SET last_activity_at = now() WHERE last_activity_at IS NULL`, chunks around 1000 rows with sleep between batches.
- Keep this slice DB-only; no auth behavior changes.
- Tests/evidence: migration/backfill unit or dry-run test plus PostgreSQL live-row evidence.
- Decisions: 4, 12, 17.

### PR1 — Backend activity bump (`fix/287-backend-activity-bump`)
- Add `record_session_activity(session_id, user_id, db, policy)` in `backend/services/auth_service.py`.
- Bump activity on refresh and every authenticated `get_current_user` path, throttled by `SESSION_ACTIVITY_WRITE_THROTTLE_SECONDS` default `60`.
- Support both `standard` and `operational`; operational may no-op/heartbeat per policy.
- Emit `session.activity_recorded` and `session.idle_expired` through existing audit logging.
- Failure policy: `record_session_activity` DB errors use `logger.exception(...)` and do not fail the authenticated request.
- Tests: `backend/tests/test_auth_service_refresh.py`, `backend/tests/test_auth_router_refresh.py`, and auth user-route coverage for `get_current_user`/`/auth/users/me`.
- Decisions: 3, 7, 8, 9, 10, 13, 14, 15, 18, 20.

### PR2 — Frontend idle logout (`fix/287-frontend-idle-logout`)
- Change `frontend/context/AuthContext.tsx` idle expiry to avoid `/auth/logout`; clear local state, broadcast `session-expired`, show `sonner` toast: “Tu sesión expiró por inactividad. Volvé a iniciar sesión.”
- Add `touchstart` and `touchmove` activity listeners.
- Toast is dismissable for 15s; redirect to `/login` after 30s if still inactive.
- Install `sonner` in `frontend/package.json`.
- Tests: `frontend/context/AuthContext.test.tsx` and any session bus/toast helper tests.
- Decisions: 1, 2, 11, 16, 19.

## Out of Scope

- Bug 3 stale-recovery/rate-limit branch; create a separate issue after #287.
- Unrelated existing test failures.
- Broad model/DB nullable mismatch refactor beyond what #287 strictly needs.
- Changing `SESSION_OPERATIONAL_ENABLED` default.
- Editing `openspec/changes/fix-multi-window-session-timeout/`.

## Capabilities

### New Capabilities
- `auth-session-lifecycle`: server-authoritative session activity, idle expiry, local idle UX, and multi-tab session event behavior.

### Modified Capabilities
- `audit-logging`: add auth session lifecycle events `session.activity_recorded` and `session.idle_expired`.

## Verified Current Evidence

- Prior design requested `record_session_activity` in `get_current_user` (`design.md:156-158`, `208-211`).
- Current `main` creates refresh tokens with `last_activity_at=now` in `backend/services/auth_service.py:79-94`; idle checks read it at `110-117`.
- Current `get_current_user` returns session metadata but does not update activity (`backend/services/auth_service.py:336-397`).
- Current logout revokes all active refresh tokens for the user (`backend/routers/auth.py:417-441`, `backend/services/auth_service.py:312-330`).
- Current idle expiry calls `/auth/logout` before local cleanup (`frontend/context/AuthContext.tsx:122-134`).
- Current activity listeners are `click`, `keydown`, `mousemove`, `focus`, `visibilitychange` only (`frontend/context/AuthContext.tsx:33`).

## Acceptance Criteria

1. PR0 backfills live PostgreSQL `refresh_tokens.last_activity_at IS NULL` rows in batches, with evidence against at least one real row.
2. Backend RED tests are written before implementation for throttle, refresh idle expiry, `/auth/users/me` activity bump, audit emission, and DB-write-failure resilience.
3. `get_current_user` or equivalent bumps the resolved `session_id` at most once per throttle window; 5 requests inside 60s produce 1 SQL update.
4. Refresh with `last_activity_at = now - 16 minutes` and a 15-minute standard timeout returns 401, clears cookies, and emits `session.idle_expired`.
5. Refresh and authenticated requests both count as activity; `/auth/users/me` polling counts too.
6. `record_session_activity` logs exceptions and lets the request continue.
7. Frontend idle expiry never calls `/auth/logout`; manual `logout()` still does.
8. Idle expiry clears only local state, broadcasts `session-expired`, shows the Spanish toast for 15s, and redirects to `/login` after 30s if still inactive.
9. Two-tab manual smoke: idle background tab does not revoke the refresh-token family or force active tab server logout; explicit Logout still logs out sibling tabs.
10. Touch activity (`touchstart`, `touchmove`) resets the idle timer.
11. Audit/log evidence exists for `session.activity_recorded` and `session.idle_expired`; no Prometheus metrics are added.
12. Backend command: `uv run pytest ...` for affected tests, then full backend suite when slice-ready. Frontend command: `pnpm --dir frontend run test:run` (no `--reporter=basic`). Existing 1134 backend / 476 frontend tests must not regress.
13. Issue #287 acceptance item for Bug 3 is explicitly deferred to its own issue and is not a #287 merge gate.

## Risks

| Risk | Mitigation |
|---|---|
| `openspec/config.yaml` may be stale vs Engram `artifact_store=both` | Persist both Engram and OpenSpec; specs should prefer this proposal. |
| `ci-cd-pipeline` work is untracked relative to this chain | Do not mix CI/CD changes into #287 slices. |
| No dedicated lint/format command in cached test capabilities | Use targeted tests plus known full test commands only. |
| Vitest reporter gotcha | Use `pnpm --dir frontend run test:run`; do not add `--reporter=basic`. |
| No E2E harness for true browser tabs | Require documented manual two-tab smoke before merge. |
| Activity writes could add DB load | Throttle writes with env default 60s; test SQL update count. |
| `last_activity_at` NULL decision conflicts with current non-null model/init behavior | Specs must define minimal nullability/backfill behavior without broad schema refactor. |
| Adding `sonner` changes frontend dependency graph | Isolate in PR2 with lockfile update and toast tests. |

## Rollback Plan

- PR2 rollback: revert `sonner` dependency and idle-local-only changes; manual Logout remains server authoritative.
- PR1 rollback: disable activity bump by setting a high throttle or reverting `record_session_activity` wiring; existing refresh verification remains.
- PR0 rollback: no destructive migration; rows updated to `now()` are acceptable conservative activity baselines. If needed, restore from DB backup.

## Dependencies

- Existing audit event store from `audit-logging` capability.
- Existing session bus (`next-gen-auth-session`) for cross-tab broadcast.
- New frontend dependency: `sonner`.

## Open Questions Before Spec

- Should specs require changing `RefreshToken.last_activity_at` ORM nullability to support “NULL until first request,” or treat NULL only as a transitional DB state?
- What exact follow-up issue number will own Bug 3 acceptance once created?
