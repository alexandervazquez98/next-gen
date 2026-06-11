# Design: Background KPI Snapshots

## Context

The current backend already has a compact `system_status_snapshots` table and helper functions in `backend/main.py` for:

- building a persisted row from a live system status payload,
- serializing history rows,
- pruning rows older than `_SYSTEM_STATUS_HISTORY_RETENTION_DAYS`, and
- returning `/api/system/status/history` rows newest-first.

However, `/api/system/status` currently calls `_record_system_status_snapshot(payload)` as a side effect. Because the dashboard is the caller that polls `/api/system/status`, snapshot continuity depends on browser activity. This change moves persistence ownership to the backend scheduler while preserving `/api/system/status` as the live-card source.

## Architecture

Use the existing backend process and existing APScheduler instance in `backend/main.py` for the minimal implementation footprint.

```text
FastAPI startup
  └─ start shared AsyncIOScheduler
       ├─ existing daily backup job
       ├─ existing audit retention cleanup job
       └─ new system_status_snapshot job, interval=15m
             └─ collect current system status payload
                  └─ persist compact SystemStatusSnapshot row
                       └─ prune rows older than 7 days

Frontend SystemDashboard
  ├─ live cards: /api/system/status polling every 3s (unchanged)
  └─ history/stale state: /api/system/status/history polling every 60s
```

The snapshot job should reuse the same compact payload-building path that powers `/api/system/status`, but `/api/system/status` must no longer be required for persistence. To avoid duplicating live-status logic, extract the body of `get_system_status()` into a helper such as `_build_system_status_payload()` and call it from both the endpoint and the background job.

## Backend design

### Snapshot capture flow

1. Add a small helper that builds the live system-status payload without request context.
   - Suggested name: `_build_system_status_payload()`.
   - It should contain the existing CPU/RAM/disk/service/collector/disk I/O logic now inside `get_system_status()`.
2. Keep `get_system_status()` returning that payload for live dashboard cards.
3. Remove the persistence side effect from `get_system_status()`.
4. Add a scheduler job function, e.g. `_record_system_status_snapshot_job()`:
   - call `_build_system_status_payload()`,
   - call `_record_system_status_snapshot(payload)`,
   - log success at debug/info level and failures as warnings,
   - do not raise failures out of the scheduler job.

### Cadence and retention

Change the status-history write interval from the current 5-minute throttle to 15 minutes:

- `_SYSTEM_STATUS_HISTORY_MIN_INTERVAL_SECONDS = 900`
- retention remains `_SYSTEM_STATUS_HISTORY_RETENTION_DAYS = 7`

The existing database lock and latest-row check should remain. This protects against accidental immediate duplicate writes in-process and also allows a safe `run immediately on startup` option without creating an extra row if a recent snapshot already exists.

### Scheduler lifecycle

Register the new job during FastAPI startup before `backup_scheduler.start()`:

- job id: `system_status_snapshot`
- trigger: `IntervalTrigger(minutes=15)` or equivalent seconds from config
- `replace_existing=True`
- `max_instances=1`
- `coalesce=True`
- no backlog catch-up flood after downtime

Recommended startup behavior:

- Register the interval job.
- Optionally execute one immediate snapshot capture after scheduler registration or use APScheduler `next_run_time=datetime.now(...)`.
- The existing throttle prevents duplicate rows if another snapshot was recently recorded.

Shutdown continues to use the existing scheduler shutdown path. If implementation discovers the shared `backup_scheduler.shutdown()` can raise when not running in tests, guard it defensively, but do not broaden this change beyond scheduler lifecycle safety.

### Configuration and defaults

Keep defaults explicit and environment-configurable:

| Setting | Default | Purpose |
| --- | ---: | --- |
| `SYSTEM_STATUS_SNAPSHOTS_ENABLED` | `true` | Emergency kill switch for background persistence. |
| `SYSTEM_STATUS_SNAPSHOT_INTERVAL_SECONDS` | `900` | 15-minute snapshot cadence. Clamp or validate to avoid high-frequency writes. |
| `SYSTEM_STATUS_HISTORY_RETENTION_DAYS` | `7` | Retention window. |
| `SYSTEM_STATUS_HISTORY_STALE_THRESHOLD_SECONDS` | `1800` | UI warning threshold, default two intervals. |

For minimal footprint, these can be read in `backend/main.py` with small parsing helpers. Invalid values should fall back to defaults and log a warning. The interval should not be configurable below a safe floor such as 60 seconds; product default remains 900 seconds.

### Duplicate-process guard decision

This design does not add a distributed lock or leader election in the first implementation.

Decision:

- In-process guard: keep `_SYSTEM_STATUS_HISTORY_LOCK`, `max_instances=1`, and latest-row throttle.
- Cross-process behavior: if multiple backend processes run the same scheduler, duplicate job attempts may occur, but the latest-row check against the shared database should cause all but one attempt within the 15-minute window to skip after the first commit.
- Residual race: two processes can query before either commits and both insert. For this issue, accept this low risk rather than adding schema changes or advisory-lock abstraction.

If production deployment commonly uses multiple Uvicorn/Gunicorn workers, a follow-up hardening option is a PostgreSQL advisory lock around `_record_system_status_snapshot()` or a uniqueness constraint on a time bucket. That is intentionally out of the minimal first pass unless tests or deployment review prove it necessary.

## Data and API contract

### Persisted row

No schema change is required. Continue using `backend/models/system_status_history.py:SystemStatusSnapshot` fields:

- `recorded_at`
- `cpu`, `ram`, `disk`
- compact disk I/O rates/busy state
- Neo4j/Postgres status
- collector status and compact collector stats

### `/api/system/status`

Remains the live-card source.

Contract changes:

- Response shape unchanged.
- Polling cadence from frontend remains unchanged.
- No snapshot persistence side effect is required or expected.

### `/api/system/status/history`

Extend the response metadata so the frontend does not need to hard-code freshness rules or infer server time incorrectly.

Recommended response shape:

```json
{
  "generated_at": "2026-01-01T12:45:00Z",
  "hours": 168,
  "limit": 500,
  "retention_days": 7,
  "snapshot_interval_seconds": 900,
  "stale_threshold_seconds": 1800,
  "latest_recorded_at": "2026-01-01T12:30:00Z",
  "is_stale": false,
  "rows": []
}
```

Rules:

- `latest_recorded_at` is the newest persisted snapshot timestamp in the returned/queryable window, or `null` when no rows exist.
- `is_stale` is `true` when there are no rows or when `generated_at - latest_recorded_at > stale_threshold_seconds`.
- Rows older than 7 days remain excluded.
- `retention_days` remains `7`.

This is backward-compatible for existing frontend code because it only adds fields.

## Stale detection UI contract

The System Dashboard should display an operator-visible warning in the Operational History section when `history.is_stale === true`.

Suggested copy:

> Operational history snapshots are stale. Latest persisted snapshot: <timestamp or "none">. Live cards may still be current, but the 7-day history pipeline is behind.

UI behavior:

- Show the warning above charts/history rows so it is visible even when old rows exist.
- Do not block live cards or hide history charts; stale rows can still be useful context.
- If history fetch fails, keep the existing error state separate from stale state.
- Update existing empty-state copy from "every five minutes" to "every 15 minutes".

The frontend should prefer backend-provided `is_stale`, `latest_recorded_at`, and `stale_threshold_seconds`. If an older backend response lacks those fields during rollout, it may derive staleness from `generated_at` and first row timestamp as a defensive fallback.

## File changes

Expected implementation files:

- `backend/main.py`
  - extract live status payload builder,
  - remove endpoint-triggered snapshot write,
  - add interval scheduler registration and job function,
  - add history metadata for freshness,
  - update interval constant/config parsing.
- `backend/tests/test_system_status.py`
  - update throttle test from 5 minutes to 15 minutes,
  - add tests for history metadata/staleness helpers,
  - add tests that the live endpoint path does not require snapshot recording side effects where practical.
- `frontend/services/queryResources.ts`
  - extend `SystemStatusHistoryResponse` type with optional/new metadata fields.
- `frontend/components/SystemDashboard.tsx`
  - render stale warning,
  - update empty-state cadence copy.
- `frontend/components/SystemDashboard.test.tsx`
  - assert stale warning appears for stale metadata,
  - assert warning is absent for fresh metadata,
  - update copy expectations.

No changes are expected in CI/SNMP/ICMP collector services or polling workers.

## Testing strategy (strict TDD)

Strict TDD is active. During apply, implement in RED/GREEN/TRIANGULATE/REFACTOR order and record evidence.

### Backend tests

Run with `cd backend && python -m pytest`.

Recommended RED tests before backend implementation:

1. `test_should_record_system_status_snapshot_honors_fifteen_minute_throttle`
   - 14 minutes old: skip.
   - 15 minutes old: record.
2. History metadata/staleness helper test:
   - latest snapshot 29 minutes old: `is_stale` false.
   - latest snapshot 31 minutes old: `is_stale` true.
   - no rows: `is_stale` true and `latest_recorded_at` null.
3. Scheduler registration test, if feasible without starting real long-running loops:
   - job id `system_status_snapshot` is added with 15-minute interval and `max_instances=1`.
4. Endpoint separation test, if feasible:
   - `get_system_status()` returns live payload without invoking `_record_system_status_snapshot`.

### Frontend tests

Run with `corepack pnpm --dir frontend run test:run`.

Recommended RED tests before frontend implementation:

1. Renders stale operational history alert when `history.is_stale` is true.
2. Does not render alert when `history.is_stale` is false.
3. Empty state says snapshots are recorded every 15 minutes.
4. Existing live-card rendering tests continue to pass with unchanged `/api/system/status` shape.

### Manual verification

If local scheduler behavior is not fully covered by automated tests, manually verify in development logs with a shortened interval only in a local environment. Do not commit a shortened default. Evidence should include scheduler registration and a persisted row written without visiting the dashboard.

## Performance and operational considerations

- Normal writes: 1 compact row per 15 minutes, approximately 96 rows/day and 672 rows for 7 days per backend scheduler owner.
- History query remains bounded by `limit` (dashboard uses 500) and retention cutoff.
- No high-frequency raw metrics persistence is introduced.
- Snapshot capture reuses current live-status collection and must not alter CI/SNMP/ICMP collection cadence.
- Background job failures should be warning logs and visible to operators through stale history metadata/UI.

## Rollout

1. Deploy backend with scheduler enabled by default.
2. Confirm startup logs show the system status snapshot job registered.
3. Confirm `/api/system/status/history` includes new freshness metadata.
4. Confirm the dashboard shows no stale warning after fresh snapshots are present.
5. After 30+ minutes without successful snapshots, confirm stale warning appears.

## Rollback

Preferred rollback is configuration-only:

- set `SYSTEM_STATUS_SNAPSHOTS_ENABLED=false` to stop background snapshot writes.

Code rollback options:

- revert scheduler registration and restore prior endpoint side-effect behavior only if emergency continuity is more important than the endpoint-separation requirement.
- Because no schema migration is planned, rollback does not require database changes.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Multiple backend processes attempt the same scheduled write | In-process lock, `max_instances=1`, `replace_existing=True`, and latest-row throttle; consider PostgreSQL advisory lock later if deployment requires it. |
| Snapshot gaps during backend restarts or DB outages | Do not catch up with high-frequency backfill; expose stale metadata and UI warning. |
| False stale warning due to clock/timing jitter | Default stale threshold is 30 minutes, two cadence intervals, not exactly one interval. |
| Endpoint helper extraction accidentally changes live-card response | Keep response shape unchanged and protect with existing frontend/backend tests. |
| Disk I/O sampling changes because background job calls the live payload builder | Accept one extra 15-minute sample from the same existing helper; do not alter diskstats/SNMP/ICMP collection semantics. |
