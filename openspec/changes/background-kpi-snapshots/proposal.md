# Proposal: background-kpi-snapshots

Status: Draft
Change ID: `background-kpi-snapshots`
GitHub Issue: `#262`

## Executive Summary
Persist server operational snapshots from a **backend background task** every 15 minutes so KPI history remains continuous even when the System Dashboard is closed. Keep live dashboard cards driven by `/api/system/status` polling as-is, and surface a staleness indicator when snapshot recording pauses or falls behind.

## Problem
Operational history currently appears to be populated indirectly when `/api/system/status` is polled. If no frontend user is actively opening the dashboard, no live polling occurs and history becomes stale or empty, even if the backend is healthy. This creates confusion in operations workflows that rely on continuity over outages and shift handoffs.

## Business Intent and Outcome
- Ensure 7-day operational snapshot history remains continuous and available after closing/reopening the dashboard.
- Keep live cards responsive and up-to-date via live status polling.
- Surface a clear UI signal when the backend snapshot pipeline stops updating, without requiring operator interpretation of missing rows.
- Maintain a light, predictable write pattern (`15m` cadence, compact rows, 7-day retention).

## Proposal Question Round (assumptions captured)
Based on your answers:
1. Use a new synchronized worktree baseline and keep change scoped to this issue.
2. Snapshot cadence is **15 minutes**.
3. UX must include continuity + staleness alert/indicator if backend recording fails.
4. Scope must not touch CI/SNMP/ICMP metric collection logic.
5. Optimize for low-frequency writes and low performance impact.

If any of these assumptions need correction, or if you want a second question round, let me know before moving to design.

## Goals
1. **Backend-owned persistence:** snapshot writes are performed by backend scheduling, independent of UI requests.
2. **Predictable cadence:** snapshots recorded at 15-minute intervals (or configuration-equivalent if needed).
3. **Retention contract:** keep snapshots for 7 days and continue oldest-row pruning.
4. **Staleness visibility:** dashboard shows explicit warning when latest persisted snapshot is older than allowed freshness window.
5. **No behavioral regression in live telemetry:** `/api/system/status` still powers live cards and current-status visuals.

## Non-Goals
- No change to CI/SNMP/ICMP polling, collector internals, or metric collection semantics.
- No high-frequency write pipeline or raw metric persistence expansion.
- No change to core authentication/session policy behavior.
- No migration to a new timeseries store or redesign of current `system_status_snapshots` schema (unless required during implementation if data shape proves insufficient).

## Scope
### In Scope
- Backend startup scheduling and background execution path for snapshot capture.
- Snapshot capture logic (extracted/reused) and retention behavior.
- `/api/system/status/history` response/metadata enhancements for freshness checks if needed.
- System Dashboard UI updates for stale-indicator state.
- Tests around scheduler/write behavior and stale-state rendering.

### Out of Scope
- Changes to SNMP/CI/ICMP metric ingestion and metric endpoints.
- UI-triggered persistence paths.
- Additional metric precision beyond compact KPI row model.
- Any feature beyond snapshot pipeline observability (e.g., alerting integrations, webhook emissions).

## Affected Areas (expected)
- `backend/main.py` (scheduler lifecycle + background snapshot job; optional history API freshness metadata)
- `backend/models/system_status_history.py` (likely unchanged unless schema needs minor fields)
- `backend/tests/test_system_status.py` (snapshot interval/retention expectations)
- `frontend/components/SystemDashboard.tsx` (staleness indicator + messaging)
- `frontend/components/SystemDashboard.test.tsx` (new UI states)
- Potentially supporting query hooks/types if API response shape changes

## Proposed Design Direction
1. **Create a dedicated background snapshot job in backend startup**
   - Add/extend APScheduler usage in `backend/main.py` to run a task every 15 minutes.
   - Task should gather the compact KPI payload using existing status collection logic and persist via the same compact model currently used.
   - Keep existing `_SYSTEM_STATUS_HISTORY_RETENTION_DAYS = 7` and existing pruning approach.

2. **Remove UI-triggered snapshot writes from live endpoint**
   - Keep `/api/system/status` side-effect-free for snapshot persistence.
   - Keep endpoint behavior focused on live telemetry returns for cards.

3. **Introduce staleness detection**
   - Either in backend (`/api/system/status/history` includes `latest_recorded_at`/`is_stale`) or frontend (derive staleness from `history.rows[0].recorded_at` + generated timestamp).
   - Recommend stale threshold around **2 intervals** (e.g., 30 minutes) before alerting.

4. **Keep performance bounded**
   - Use compact row payload only (existing schema fields).
   - 15-minute write interval (4 writes/hour), not on each user poll.
   - One retry-safe write path with warning logs, not automatic busy-loop retries.

5. **Operational safety and config controls**
   - Optional feature flag/env for enabling background snapshots, to support emergency rollback.
   - Scheduler-safe startup/shutdown behavior and single-owner job registration.

## Acceptance Outline
- With dashboard closed for hours, reopening shows persisted snapshots covering recent windows (subject to backend uptime).
- Snapshot cadence is approximately every 15 minutes and retention remains at 7 days.
- Live status cards continue to update from `/api/system/status` polling during UI usage.
- If background snapshots stop, dashboard displays a clear alert message (not just empty state).
- No measurable performance regression: no high-frequency DB writes beyond 15-min cadence.

## Risks
1. **Scheduler drift/multiple-instance write duplication** if multiple backend instances schedule same job.
2. **Transient snapshot gaps** during backend restarts or temporary failures; should fail visible to operators via staleness signal.
3. **False-positive stale warnings** from clock skew/reporting delay; mitigation needed via tolerance window.
4. **Endpoint coupling risk** if snapshot logic is tightly coupled to request context; keep capture path independent and tested.

## Rollback Plan
- Disable background snapshot scheduler via config flag / deployment toggle.
- Temporary fallback path: keep old endpoint-based write behavior behind same flag if immediate recovery needed.
- Because this is additive and isolated, rollback can be done by un-scheduling background job and restoring previous `_record_system_status_snapshot` call behavior.

## Risks to Product Outcome / Tradeoffs
- If no staleness threshold exists, operators may miss hidden data-loss windows.
- If the interval is too long for operations use, continuity granularity decreases; if too short, DB write overhead increases.
- If persistence failures are silent, trust in dashboard continuity drops despite live status still appearing current.

## Success Criteria
- Continuous 7-day history available after periods where the dashboard was closed.
- Snapshot rows are produced at ~15-minute intervals and old rows pruned past 7 days.
- Staleness indicator reliably appears when latest snapshot age exceeds threshold.
- CI/SNMP/ICMP metric collection behavior unchanged.
- No high-frequency persistence writes introduced and no observable service-side polling load increase.