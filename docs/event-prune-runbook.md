# Event Prune & Recovery Lifecycle Runbook

Operational runbook for the auto-prune scheduler and the one-shot `Event.created_at` backfill introduced in fix-423 (issue #423). The fix unblocks RECOVERED-event accumulation that previously grew unbounded across cycles.

## What it does

- **Auto-prune scheduler** ticks every `EVENT_PRUNE_INTERVAL_SECONDS` (default 3600s) on the backend's in-process APScheduler (`backup_scheduler`). It closes `RECOVERED` events that have been waiting longer than `EVENT_PRUNE_STALE_AFTER_SECONDS` (default 3600s) and that have no operator acknowledgement.
- **Cursor hardening** in `event_batch_pruner` paginates past `created_at = NULL` rows using a composite `(created_at, id)` cursor. Without the one-shot backfill below, the cursor still works on legacy NULL rows, but the audit trail and any downstream analytics that rely on `created_at` lose accuracy.
- **ICMP-latency writer** no longer creates a fresh `Event` row on every DOWN→OK→DOWN cycle. It reuses the existing `RECOVERED` row from the previous cycle and writes `created_at` on every CREATE, so the cursor stays bounded going forward.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `EVENT_PRUNE_ENABLED` | `true` | Kill-switch for the auto-prune scheduler. When `false`, the job is registered but is a no-op. |
| `EVENT_PRUNE_INTERVAL_SECONDS` | `3600` | Scheduler tick cadence. Lower for staging, keep 3600 in production. |
| `EVENT_PRUNE_BATCH_SIZE` | `500` | Max events closed per scheduler tick. Mirrors `EVENT_BATCH_SIZE`. |
| `EVENT_PRUNE_STALE_AFTER_SECONDS` | `3600` | Minimum age (since `recovered_at`) before a `RECOVERED` event is eligible for auto-prune. |

All four are documented in `.env.example` and wired into the `backend` service in `docker-compose.yml`. The Pydantic class is `EventPruneSettings` in `backend/config.py`.

## Observability

The auto-prune scheduler surfaces two metrics on `GET /api/system/status` under `collector.prune`:

- `recovered_stale_total` (gauge): count of `RECOVERED` events older than `EVENT_PRUNE_STALE_AFTER_SECONDS` and not yet closed.
- `pruned_total` (counter): number of scheduler ticks that closed at least one event. Empty batches do not increment.
- `last_run_at` (timestamp): last scheduler tick wall-clock time.
- `last_run_closed_count` (int): number of events closed on the last tick.

Watch `recovered_stale_total` trend toward 0 over the first 24 hours after the first deploy. Stable low values mean the scheduler is keeping up.

## First deploy (with the legacy 19,076 NULL rows)

1. Pull the PR #1 branch and deploy as usual.
2. Run the operator runbook with the new flag to backfill the legacy NULL rows:

   ```bash
   sh scripts/safe-rebuild.sh --run-event-backfill
   ```

   The script runs the one-shot backfill inside the backend container. It is idempotent: only mutates rows where `created_at IS NULL` and uses `COALESCE(recovered_at, last_seen, closed_at, datetime())`. The dry-run preview tells you how many rows will be touched:

   ```bash
   docker compose exec -T backend python -m backend.scripts.backfill_event_created_at --batch-size 500 --sleep-seconds 0.5 --dry-run
   ```

3. Deploy PR #2 (scheduler + ICMP-latency widening + lock-contract regression). The scheduler starts ticking on the next `startup_event` of the backend.
4. Monitor `collector.prune.recovered_stale` for 24h. Once it stabilizes below 100, the auto-prune is healthy.

## Subsequent deploys

The `--run-event-backfill` flag is a one-shot. After the first PR #1 deploy, the backfill is already done. Subsequent deploys can omit the flag:

```bash
sh scripts/safe-rebuild.sh
```

The script will print a `SKIP` message and remind you to re-run with `--run-event-backfill` only if you ever reset the graph or import an external dump with NULL `created_at`.

## Emergency disable

If the scheduler misbehaves (lock contention, runaway batch, etc.), disable it without redeploying:

```bash
# Edit .env
echo "EVENT_PRUNE_ENABLED=false" >> .env
# Recreate the backend container so it picks up the new ENV
docker compose up -d --force-recreate backend
```

The job is registered but becomes a no-op. The RECOVERED events keep accumulating; you can still run `POST /api/events/prune` manually while disabled.

## Manual prune (operational)

The auto-prune does not replace manual cleanup. Use `POST /api/events/prune` to:

- Force-close a known batch during a maintenance window.
- Recover from a `prune_lock` lock-row corruption (the scheduler will retry on the next tick).
- Close a specific historical RECOVERED set with operator-provided context.

The auto-prune and the manual `/api/events/prune` share the `prune_lock` advisory lock. Concurrent calls return `HTTP 409` on the second caller — never both write.

## Rollback

The full rollback path is in `openspec/changes/archive/2026-08-14-fix-423-recovered-event-accumulation/design.md` §Rollback. Quick summary:

1. `EVENT_PRUNE_ENABLED=false` + recreate backend → scheduler stops, no DB impact.
2. Revert `event_service.py` cursor → manual `POST /events/prune` falls back to pre-fix behavior (first batch only).
3. Revert `engines/snmp_worker.py:742,782,786` → ICMP-latency writer re-creates ROOT on every cycle (regression).
4. Leave the backfill script in place; it is a no-op on re-run.

## References

- Issue: https://github.com/alexandervazquez98/next-gen/issues/423
- Spec: `openspec/specs/event-prune-recovery-lifecycle/spec.md`
- Spec (modified): `openspec/specs/event-writer-coordination-observability/spec.md` (REQ-OBS-PRUNE-001/002/003)
- Design: `openspec/changes/archive/2026-08-14-fix-423-recovered-event-accumulation/design.md`
- Verify report: `openspec/changes/archive/2026-08-14-fix-423-recovered-event-accumulation/verify-report.md`
- Backfill script: `backend/scripts/backfill_event_created_at.py` (`--help` for full options)
- Metrics module: `backend/services/event_prune_metrics.py`
- API surface: `GET /api/system/status` → `collector.prune.{recovered_stale, pruned, last_run_at, last_run_closed_count}`
