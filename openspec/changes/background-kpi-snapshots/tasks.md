# Tasks — background-kpi-snapshots (Issue #262)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 520–780 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 -> PR 2 |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

## PR 1 — Backend TDD + implementation (snapshot scheduler + history metadata)

**Dependency:** must land before any frontend contract consumption in PR 2.

### Scope
`backend/main.py`, `backend/tests/test_system_status.py`

1. **[x] RED — Add/update backend tests for 15-minute cadence, stale metadata, and endpoint separation (TDD start).**
   - Update `backend/tests/test_system_status.py`:
     - rename/update `test_should_record_system_status_snapshot_honors_five_minute_throttle` to `..._fifteen_minute_throttle` with assertions:
       - 14 min old latest snapshot -> `False`
       - 15 min old latest snapshot -> `True`
     - add tests for `latest_recorded_at` + staleness contract:
       - rows present and age 29m -> `is_stale == False`
       - rows present and age 31m -> `is_stale == True`
       - no rows -> `is_stale == True`, `latest_recorded_at is None`
     - add test that `get_system_status` path is side-effect free for snapshots:
       - mock/patch `_record_system_status_snapshot` and assert it is **not** called from `get_system_status()`.
   - **Test command:** `cd backend && python -m pytest tests/test_system_status.py`
   - **RED evidence:** Added tests for behavior absent from baseline; first failing output was not preserved because delegated apply failed with model context error after writing changes. See `apply-progress.md`.

2. **[x] GREEN — Implement config-driven schedule constants and safe parsing helpers in `backend/main.py`.**
   - Add parsing helpers for:
     - `SYSTEM_STATUS_SNAPSHOT_INTERVAL_SECONDS` (default `900`, floor >= 60)
     - `SYSTEM_STATUS_HISTORY_RETENTION_DAYS` (default `7`)
     - `SYSTEM_STATUS_HISTORY_STALE_THRESHOLD_SECONDS` (default `1800`)
     - `SYSTEM_STATUS_SNAPSHOTS_ENABLED` (default `true`)
   - Replace hard-coded `_SYSTEM_STATUS_HISTORY_MIN_INTERVAL_SECONDS`/retention constants with parsed config-backed values.
   - Preserve current `logger.warning` behavior on invalid env values.
   - **Test command:** `cd backend && python -m pytest tests/test_system_status.py`
   - **GREEN evidence:** `cd .worktrees/background-kpi-snapshots/backend && python -m pytest tests/test_system_status.py` -> 13 passed, 5 warnings in 2.08s

3. **[x] GREEN — Extract live payload builder and remove snapshot persistence side-effect from `/api/system/status`.**
   - In `backend/main.py`, create helper `_build_system_status_payload()` containing all current live status calculations currently inside `get_system_status`.
   - Update `get_system_status()` to:
     - return `_build_system_status_payload()`;
     - remove the call to `_record_system_status_snapshot(payload)`.
   - Ensure response shape remains unchanged.
   - **Test command:** `cd backend && python -m pytest tests/test_system_status.py`
   - **GREEN evidence:** `cd .worktrees/background-kpi-snapshots/backend && python -m pytest tests/test_system_status.py` -> 13 passed, 5 warnings in 2.08s

4. **[x] GREEN — Add scheduled capture job wiring in startup lifecycle.**
   - In `backend/main.py`:
     - add `IntervalTrigger` import (or equivalent)
     - add job function `_record_system_status_snapshot_job()` that builds payload and calls `_record_system_status_snapshot(payload)`.
     - register job in `startup_event()` with:
       - `id="system_status_snapshot"`
       - interval = 15 min
       - `replace_existing=True`, `max_instances=1`, `coalesce=True`
       - feature gate by `SYSTEM_STATUS_SNAPSHOTS_ENABLED`
     - keep existing shared `backup_scheduler` and scheduler shutdown path.
   - **Test command:** `cd backend && python -m pytest tests/test_system_status.py`
   - **GREEN evidence:** `cd .worktrees/background-kpi-snapshots/backend && python -m pytest tests/test_system_status.py` -> 13 passed, 5 warnings in 2.08s

5. **[x] GREEN — Extend `/api/system/status/history` response with freshness metadata.**
   - In `backend/main.py`:
     - augment `_fetch_system_status_history()` response with:
       - `snapshot_interval_seconds`
       - `stale_threshold_seconds`
       - `latest_recorded_at`
       - `is_stale`
     - keep `retention_days` and existing `hours/limit` semantics.
     - ensure rows are pruned by existing retention/`hours` filters and returned newest-first.
   - **Test command:** `cd backend && python -m pytest tests/test_system_status.py`
   - **GREEN evidence:** `cd .worktrees/background-kpi-snapshots/backend && python -m pytest tests/test_system_status.py` -> 13 passed, 5 warnings in 2.08s

6. **[x] GREEN — Add scheduler registration test (if feasible without brittle timing).**
   - Add/extend backend tests to assert on scheduler job metadata after startup registration (job id, interval, `max_instances`, `coalesce`, enable flag).
   - Use light-weight patching/mocking of `AsyncIOScheduler` if direct startup side effects are difficult in test context.
   - **Test command:** `cd backend && python -m pytest tests/test_system_status.py`
   - **GREEN evidence:** `cd .worktrees/background-kpi-snapshots/backend && python -m pytest tests/test_system_status.py` -> 13 passed, 5 warnings in 2.08s

7. **[x] TRIANGULATE — Run full backend suite slice and validate separation assumptions.**
   - Re-run:
     - `cd backend && python -m pytest tests/test_system_status.py`
     - `cd backend && python -m pytest` (or backend equivalent scope if >15 min)
   - Confirm:
     - `/api/system/status` remains unchanged in payload shape and continues polling behavior.
     - no duplicate immediate-write path from live endpoint.
     - retention remains 7 days.
   - **TRIANGULATE evidence:** targeted system-status suite passed. Full backend suite currently has unrelated baseline failures: 94 failed, 939 passed, 1 skipped.

8. **[x] REFACTOR — Tighten observability + operational safety before handoff.**
   - Add/adjust concise log messages on scheduled snapshot success/failure, and guard scheduler registration/shutdown edge cases.
   - Remove dead paths from side-effect removal so maintenance debt is not increased.
   - **Verification command:** `cd backend && python -m pytest tests/test_system_status.py`
   - **REFACTOR evidence:** payload builder extracted, endpoint side-effect removed, scheduler helper added, targeted tests remain green. See `apply-progress.md`.

## PR 2 — Frontend TDD + UI stale behavior contract

**Dependency:** expects backend freshness metadata contract from PR 1.

### Scope
`frontend/services/queryResources.ts`, `frontend/components/SystemDashboard.tsx`, `frontend/components/SystemDashboard.test.tsx`

9. **[x] RED — Add frontend contract/state tests for stale warning and cadence copy.**
   - Update `frontend/components/SystemDashboard.test.tsx`:
     - add mock history fixture with `is_stale: false` and assert no stale alert.
     - add mock history fixture with `is_stale: true`, `latest_recorded_at: ...` and assert explicit stale warning text and visibility.
     - add test that empty state copy says snapshots are recorded every 15 minutes.
     - ensure existing telemetry tests still pass for live card rendering.
   - **Test command:** `corepack pnpm --dir frontend run test:run frontend/components/SystemDashboard.test.tsx`
   - **RED evidence:** Added stale warning/type/cadence tests before implementation; initial filtered command used repo-relative path with `--dir frontend` and failed to find tests, then corrected to `components/SystemDashboard.test.tsx`.

10. **[x] GREEN — Extend history response type contract in `frontend/services/queryResources.ts`.**
    - Add optional/nullable fields to `SystemStatusHistoryResponse`:
      - `snapshot_interval_seconds?: number`
      - `stale_threshold_seconds?: number`
      - `latest_recorded_at?: string | null`
      - `is_stale?: boolean`
    - Keep existing fields backward-compatible so older responses still parse.
    - **Test command:** `corepack pnpm --dir frontend run test:run frontend/components/SystemDashboard.test.tsx`
    - **GREEN evidence:** `corepack pnpm --dir frontend run test:run components/SystemDashboard.test.tsx hooks/queries/resourceQueries.test.tsx` -> 2 files passed, 17 tests passed.

11. **[x] GREEN — Render stale indicator in `frontend/components/SystemDashboard.tsx` + keep charts visible.**
    - In operational history section, show an operator warning banner when stale:
      - conditionally visible when `history.is_stale === true` (fallback derive from backend if fields absent).
      - include `latest_recorded_at` timestamp/`none` in message.
      - do not block charts or historical rows.
    - Keep existing error/loading/no-data states distinct.
    - Update empty-state text to: recorded every 15 minutes.
    - **Test command:** `corepack pnpm --dir frontend run test:run frontend/components/SystemDashboard.test.tsx`
    - **GREEN evidence:** `corepack pnpm --dir frontend run test:run components/SystemDashboard.test.tsx hooks/queries/resourceQueries.test.tsx` -> 2 files passed, 17 tests passed.

12. **[x] TRIANGULATE — Frontend suite evidence and manual smoke checks.**
    - Run:
      - `corepack pnpm --dir frontend run test:run`
    - Manual checks:
      - dashboard open with fresh history: no warning.
      - history rows stale by threshold: stale warning appears above charts.
      - live cards remain polling-responsive without relying on history writes.
    - **TRIANGULATE evidence:** `corepack pnpm --dir frontend run test:run` -> 44 files passed, 424 tests passed.

13. **[x] REFACTOR — Minor UX/accessibility hardening.**
    - Verify stale warning text severity/visibility meets operator use.
    - Ensure no duplicate string duplication with existing error/empty state messages.
    - Keep CSS/layout changes within section and avoid unrelated refactors.
    - **Verification command:** `corepack pnpm --dir frontend run test:run`
    - **REFACTOR evidence:** stale warning helper added with backend metadata first and legacy fallback; interval copy now uses backend metadata; LSP diagnostics clean for changed frontend files.

## Validation, docs, and issue synchronization

14. **[ ] Run full validation matrix before merge.**
    - Backend: `cd backend && python -m pytest`
    - Frontend: `corepack pnpm --dir frontend run test:run`
    - Manual operational check (non-blocking): run backend with default interval and confirm:
      - no side-effect writes from `/api/system/status`;
      - `/api/system/status/history` includes freshness metadata;
      - stale warning triggers after ~30 mins without fresh rows.

15. **[ ] Sync issue #262 with implemented behavior + any config knobs (if needed).**
    - Update issue checklist/notes to record final cadence, retention, stale threshold defaults, and kill-switch/env names.
