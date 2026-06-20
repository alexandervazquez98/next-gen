# Design: fix-287-session-keep-alive

Status: Draft  
Change ID: `fix-287-session-keep-alive`  
GitHub Issue: `alexandervazquez98/next-gen#287`

## Executive Summary

Fix #287 with a feature-branch chain: PR0 repairs legacy DB rows, PR1 makes backend activity writes authoritative and throttled, and PR2 changes frontend idle expiry to local-only UX. Backend remains the security authority; frontend idle handling no longer revokes the refresh-token family.

## Current-State Findings

- `backend/services/auth_service.py` already creates refresh tokens with `last_activity_at=now`, verifies refresh state, and exposes `get_current_user`, but `_is_token_idle_expired()` returns non-expired when `last_activity_at is None` and no `record_session_activity` exists.
- `backend/routers/auth.py` rotates refresh tokens in `/auth/refresh`, clears cookies on idle expiry, and `/auth/logout` revokes all user refresh tokens.
- `backend/services/audit_service.py` persists auth events but currently allow-lists only `route`, `method`, `request_id`, `changed_fields`, and `required_permission` in context; session lifecycle context needs an allow-list expansion.
- `frontend/context/AuthContext.tsx` currently calls `/auth/logout` inside `expireForInactivity`, then broadcasts `session-expired`; activity events omit `touchstart`/`touchmove`.
- `frontend/services/sessionBus.ts` already supports `logout` and `session-expired` with BroadcastChannel/localStorage dedupe.

## Architecture Overview

```text
Browser activity ── /api/auth/users/me ── get_current_user ─┐
Browser refresh  ── /api/auth/refresh ── verify_refresh_token ├─ record_session_activity
                                                             │      │
                                                             │      ├─ DB conditional UPDATE refresh_tokens.last_activity_at
                                                             │      ├─ per-worker advisory throttle cache
                                                             │      └─ audit_service.record_auth_event
Frontend idle timer ── local clear + sessionBus broadcast ───┘
```

### Data Flow

1. **Normal authenticated request**: access cookie/header is decoded in `get_current_user`; user and policy are resolved; if `sid` exists, `record_session_activity(session_id, user_id, db, policy, request=None)` attempts a throttled standard-session bump; request succeeds even if the bump fails.
2. **Refresh crosses idle threshold**: `/auth/refresh` calls `verify_refresh_token`; idle anchor is `last_activity_at or created_at`; if older than `policy.idle_timeout_minutes`, return `IDLE_EXPIRED`, clear cookies, emit `session.idle_expired`, and return 401.
3. **Background tab local idle expiry**: AuthContext timer fires, does not call `/auth/logout`, clears local state, broadcasts `session-expired`, shows the toast for 15s, and redirects after 30s if still inactive. Active sibling tabs are not server-revoked.

### Throttle State Diagram

```text
unknown ── request ──> db-gate-attempted ── updated row ──> cached(session_id,next_allowed_at)
   ▲                         │                                  │
   │                         └─ DB says too soon ───────────────┘
   └──────── periodic eviction: remove expired keys when cache > max or on write path
```

Throttle choice is **hybrid**: the deterministic cross-worker gate is a DB conditional update (`WHERE session_id=:sid AND user_id=:uid AND last_activity_at <= now - throttle`); the in-process dict only skips obvious same-worker writes and is safe to lose. Pure in-memory is not deterministic across workers; pure DB has more round trips.

## PR0 — DB-only Backfill

### Files Touched

| File | Action | Purpose |
|---|---|---|
| `backend/scripts/backfill_refresh_token_activity.py` | Create | Batched `last_activity_at IS NULL` backfill script with chunk size and sleep args. |
| `backend/tests/test_refresh_token_activity_backfill.py` | Create | RED/GREEN coverage for non-empty and empty batches. |

### Function Signatures

```python
def backfill_refresh_token_activity(db: Session, *, batch_size: int = 1000, sleep_seconds: float = 0.1) -> int: ...
def main() -> int: ...
```

### Work-Unit Commit Plan

1. `test(auth): define refresh token activity backfill contract` — RED tests for NULL row and empty batch; touches `backend/tests/test_refresh_token_activity_backfill.py`.
2. `fix(auth): add batched refresh token activity backfill` — implements bounded DB-only script; touches script + test.
3. `test(auth): document live backfill evidence command` — adds test/live evidence notes in test docstrings or script help; touches script/test only.

### Test Additions

- `backend/tests/test_refresh_token_activity_backfill.py`: RED asserts a NULL `last_activity_at` row becomes non-null and empty batches no-op.
- Gates: focused `uv run pytest backend/tests/test_refresh_token_activity_backfill.py -v`; then full backend suite.

### Boundary / Rollback

Must merge before PR1 if production has NULL rows, but PR1 still handles NULL with `COALESCE`. Rollback is non-destructive: rows set to `now()` are conservative; restore from DB backup only if required. Manual evidence: PostgreSQL before/after count and at least one exercised row.

## PR1 — Backend Activity Bump

### Files Touched

| File | Action | Purpose |
|---|---|---|
| `backend/services/auth_service.py` | Modify | Add logger, throttle cache, COALESCE idle anchor, and `record_session_activity`. |
| `backend/routers/auth.py` | Modify | Call activity recorder on refresh success; emit idle audit. |
| `backend/services/session_policy.py` | Modify | Add `get_session_activity_write_throttle_seconds()`. |
| `backend/services/audit_service.py` | Modify | Allow-list session lifecycle context keys. |
| `backend/tests/test_auth_service_refresh.py` | Modify | Unit tests for COALESCE, throttle, operational no-op, DB failure. |
| `backend/tests/test_auth_router_refresh.py` | Modify | Router tests for refresh bump, idle 401 cookie clearing, audit event. |
| `backend/tests/test_routers_auth_users_roles.py` | Modify | `/auth/users/me` activity-bump coverage. |

### Function Signatures

```python
def get_session_activity_write_throttle_seconds() -> int: ...
def record_session_activity(session_id: str | None, user_id: int, db: Session, policy: SessionPolicy, request: Request | None = None) -> bool: ...
def _evict_activity_throttle_cache(now: datetime) -> None: ...
```

Return `True` only when the DB row was updated and audit was attempted; `False` for missing `sid`, operational no-op, throttle skip, DB no-row update, or logged DB failure.

### Audit Event Payload Schema

Use `audit_service.record_auth_event` with event types `session.activity_recorded` and `session.idle_expired`.

| Field | Type | Sensitive? | Notes |
|---|---:|---|---|
| `event_type` | str | No | Exact names above. |
| `outcome` | str | No | `SUCCESS` or `DENIED`. |
| `actor_username` | str \| None | No | Username only, no token. |
| `reason` | str | No | `activity_recorded`, `throttle_skipped`, `idle_timeout`. |
| `context.session_id` | str | No raw token | Stable session id; allow-listed. |
| `context.user_id` | int | No | DB user id. |
| `context.policy_profile` | str | No | `standard`/`operational`. |
| `context.throttle_seconds` | int | No | Config value. |
| `context.activity_anchor` | str | No | `last_activity_at` or `created_at`; no timestamps if not needed. |

Excluded: raw refresh/access tokens, cookies, authorization headers, request body, token hashes.

### Logging / Error Handling

Logger: `logging.getLogger(__name__)` in `services.auth_service`; existing `services.audit_service` logger remains.

| Event | Logger | Level |
|---|---|---|
| Activity row updated | `services.auth_service` | `debug` |
| Advisory throttle skip | `services.auth_service` | `debug` |
| DB write failure | `services.auth_service` | `exception` |
| Idle expiry | `routers.auth` or `services.auth_service` | `info` |
| Audit persist failure | `services.audit_service` | existing `warning` |

DB failure matrix: activity-update failure rolls back and auth continues; audit failure is swallowed by `audit_service`; refresh verification DB failure remains a request failure; idle-expired response clears cookies before raising 401.

### Work-Unit Commit Plan

1. `test(auth): define activity recorder throttle contract` — RED unit tests for one update per 60s and DB failure resilience.
2. `fix(auth): add deterministic session activity recorder` — hybrid throttle and conditional DB update.
3. `test(auth): require idle expiry coalesce semantics` — RED for `last_activity_at=None` using `created_at`.
4. `fix(auth): enforce coalesced idle activity anchor` — update `_is_token_idle_expired`.
5. `test(auth): cover refresh and users-me activity wiring` — RED router/dependency tests.
6. `fix(auth): wire activity recording and lifecycle audit events` — refresh + `get_current_user` calls and audit payloads.

### Test Additions

- `backend/tests/test_auth_service_refresh.py`: RED update-count throttle, operational no-op, NULL anchor, DB exception continuation.
- `backend/tests/test_auth_router_refresh.py`: RED idle 401 clears both cookies and emits audit; refresh success records activity.
- `backend/tests/test_routers_auth_users_roles.py`: RED `/api/auth/users/me` calls recorder with JWT `sid`.
- Gates: focused file commands above, then full backend suite.

### Boundary / Rollback

PR1 requires PR0 script merged only for production hygiene; compile does not depend on PR0. Rollback: set `SESSION_ACTIVITY_WRITE_THROTTLE_SECONDS` extremely high or revert PR1. PR2 must not start until PR1 compiles and backend focused/full suites pass.

## PR2 — Frontend Local Idle Logout

### Files Touched

| File | Action | Purpose |
|---|---|---|
| `frontend/context/AuthContext.tsx` | Modify | Remove idle `/auth/logout`, add toast/deferred redirect, touch events. |
| `frontend/context/AuthContext.test.tsx` | Modify | Local idle, manual logout, touch, toast timing tests. |
| `frontend/services/sessionBus.test.ts` | Modify | Preserve existing `session-expired` behavior if needed. |
| `frontend/package.json` | Modify | Add `sonner`. |
| `frontend/pnpm-lock.yaml` | Modify | Lock `sonner`. |

### Function Signatures

```ts
function showIdleExpiredToast(): void
function scheduleIdleRedirect(delayMs?: number): ReturnType<typeof setTimeout>
function redirectToLoginOnce(): void
```

Toast message: `Tu sesión expiró por inactividad. Volvé a iniciar sesión.`; duration `15_000`; redirect delay `30_000`.

### Work-Unit Commit Plan

1. `test(auth): define local-only idle expiry behavior` — RED proves idle does not call `/auth/logout`; manual logout still does.
2. `fix(auth): make idle expiry local-only` — remove server logout from timer.
3. `test(auth): require idle toast and deferred redirect` — RED fake-timer toast/redirect assertions.
4. `feat(auth): show idle expiry toast before redirect` — add `sonner` and helper.
5. `test(auth): reset idle timer on touch activity` — RED touch events.
6. `fix(auth): add touch activity listeners` — update `ACTIVITY_EVENTS`.

### Test Additions

- `frontend/context/AuthContext.test.tsx`: RED assertions for no idle `/auth/logout`, manual logout unchanged, toast 15s, redirect 30s, touch reset.
- `frontend/services/sessionBus.test.ts`: only if bus payload expectations need extension.
- Gates: `pnpm --dir frontend run test:run` only; no `--reporter=basic`. Manual two-tab smoke before merge.

### Boundary / Rollback

PR2 requires PR1 merged so backend activity is authoritative before local-only idle UX ships. Rollback: revert `sonner` dependency/lockfile and AuthContext changes; explicit Logout stays server authoritative.

## Cross-Cutting Concerns

### Env Vars

| Name | Default | Source of truth |
|---|---:|---|
| `SESSION_ACTIVITY_WRITE_THROTTLE_SECONDS` | `60` | `backend/services/session_policy.py` |
| `SESSION_STANDARD_IDLE_TIMEOUT_MINUTES` | `15` | existing `session_policy.py` |
| `SESSION_OPERATIONAL_ENABLED` | `false` | existing `session_policy.py`; unchanged |
| `SESSION_OPERATIONAL_ROLES` / `SESSION_OPERATIONAL_USERS` | empty | existing `session_policy.py` |

### Multi-Worker Safety

The in-memory dict is per worker and advisory only. Determinism comes from the DB conditional update, so two uvicorn/gunicorn workers racing inside the throttle window produce at most one persisted bump after the first commit. If both race before either commits, row-level update serialization plus the predicate recheck is required; tasks should verify SQLAlchemy emits one conditional `UPDATE`, not read-then-write.

### Backward Compatibility

`RefreshToken.last_activity_at` stays ORM non-null. PR0 reduces live NULLs; PR1 still reads `last_activity_at or created_at` so skipped PR0 or rows inserted during deployment do not become immortal.

## PR Boundary Verification

| Boundary | Must be merged before next PR compiles | Gates before opening | Manual evidence | Rollback |
|---|---|---|---|---|
| PR0 | Backfill script/test only; PR1 can compile without it | Focused backfill test + full backend suite | Live row before/after count | No destructive rollback; backup restore only if needed |
| PR1 | Backend recorder, policy helper, audit allow-list | Focused backend files + full backend suite | Logs/audit sample for activity and idle expiry | High throttle or revert PR1 |
| PR2 | PR1 backend authoritative activity | Full frontend test command | Two-tab smoke: idle background tab does not revoke active tab; explicit Logout does | Revert PR2 dependency + AuthContext |

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| `openspec/config.yaml` says repo-files while session says both | Persist design to OpenSpec and Engram. |
| `ci-cd-pipeline` untracked relative to #287 | Keep all files in auth/session slices only. |
| No lint/format command | Use targeted tests plus full known suites. |
| Vitest reporter rejects `--reporter=basic` | Use exact `pnpm --dir frontend run test:run`. |
| No E2E harness | Require manual two-tab evidence in PR2. |
| `_is_token_idle_expired` NULL gap | PR1 RED test for `created_at` fallback. |
| `sonner` absent | Isolate dependency to PR2 with lockfile. |
| Throttle memory leak | Bounded per-worker cache with TTL eviction and max size. |
| Multi-worker skew | DB conditional update is authoritative. |
| Audit schema drift / context dropped | PR1 updates `AUDIT_CONTEXT_ALLOWED_KEYS` and asserts persisted safe context. |

## Open Questions for Tasks Phase

- Exact max size for the per-worker throttle cache (recommended: 10,000 entries with expired-key eviction on write path).
- Exact conventional commit titles may be adjusted to match recent repo history after `git log --oneline -10` in apply.
- Whether PR0 live evidence should be a script output artifact or pasted into the PR body.
