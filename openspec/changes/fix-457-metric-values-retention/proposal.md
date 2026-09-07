# Proposal: `metric_values` Retention

Issue #457 adds bounded retention to the TimescaleDB metric hypertable.

## Intent

Stop unbounded SNMP metric growth from expanding every `pg_dump` and `safe-rebuild.sh` window.

## Problem (verbatim from issue #457)

> `metric_values` is the primary TimeScaleDB hypertable for SNMP polling metrics. It is created at `backend/repositories/metric_repo.py:18`:
>
> ```python
> db.execute(text("SELECT create_hypertable('metric_values', 'time', if_not_exists => TRUE);"))
> ```
>
> …but `add_retention_policy(...)` is **never called** for it. The hypertable accumulates rows indefinitely.

> A `sh scripts/safe-rebuild.sh` run on a server with several months of accumulated metrics took the `pg_dump -Fc` step from < 30s (empty install) to 5+ minutes, with the resulting `.dump` exceeding 250MB and still growing at ~1–2 MB/sec at the time it was checked. The hypertable scan is what dominates the post-deploy backup window and slows every `safe-rebuild.sh` invocation on an established deployment.

### Evidence rationale from issue #457

- Every deployment's pre-rebuild backup window scales with `metric_values`; after 6–12 months it becomes minutes-to-tens-of-minutes, blocking operator iteration.
- `BACKUP_DIR` cleanup does nothing about per-dump size; large dumps mean longer restore time.
- PR #453 slice 2 left the hypertable dump as the dominant cost after more than 3 months of collection.

> `docs/polling-pipeline-tuning.md:109` — *"Do not enable retention, compression, or downsampling changes until benchmark and storage-growth evidence exists."*

## Parent Retention Evidence

The following table is quoted from issue #457.

| Domain | Retention | Evidence |
| --- | --- | --- |
| `audit_events` | 90 days | `backend/services/audit_service.py:15` (`AUDIT_RETENTION_DAYS = 90`) + `audit_retention_cleanup` scheduler at `backend/main.py:486-495` |
| `system_status` snapshots | 7 days | `backend/main.py:40` (`_SYSTEM_STATUS_HISTORY_RETENTION_DAYS = 7`, env-overridable) + `background-kpi-snapshots` slice |
| Recovered events | configurable (default 3600s stale) | `EVENT_PRUNE_*` env vars + `run_prune_recovered_events` scheduler (fix-423) |
| `BACKUP_DIR` files | 7 days default, up to 3650 | `backend/models/backup_config.py:22` + `_cleanup_old_backups` at `backend/services/backup_service.py:472-478` |
| Rate limit attempts | 1 day | `backend/middleware/rate_limit.py:25` |
| MQTT mapping lifecycle audit | 90 days | reuses `AUDIT_RETENTION_DAYS` per `feat-mqtt-386-audit-trail/design.md:315` |
| **`metric_values` hypertable** | **none — accumulates indefinitely** | **(this issue)** |

## Scope

### In scope

- One metric retention policy; default 90 days.
- Environment settings, scheduler, boot application, documentation, and specification.
- Strict-TDD coverage from issue #457.

### Explicitly out of scope

- Compression policies (`add_compression_policy`).
- Downsampling / continuous aggregates.
- Chunk-drop backfill.
- Changing any other retention window.
- Frontend, Neo4j, LM Studio, AI chat, and unrelated polling changes.

## Capabilities

### New

- `time-series`: `metric_values` retention contract.

No `openspec/specs/time-series/spec.md` exists on this branch; sdd-spec creates it.

### Modified

- None. `audit-logging` is precedent, not a changed capability.

## Approach

1. **Service:** Create `backend/services/retention_service.py` with `apply_metric_retention(retention_days: int) -> None` and `run_metric_retention_cleanup()`. Use idempotent `add_retention_policy('metric_values', INTERVAL '<N> days')`; the scheduler entrypoint re-applies a missing policy defensively.

2. **Environment:** Add `MetricRetentionSettings` in `backend/config.py`, mirroring `EventPruneSettings` (fix-423). Document `METRIC_RETENTION_DAYS=90` and `METRIC_RETENTION_ENABLED=true` in `.env.example`; invalid days use the default.

3. **Scheduler:** In `backend/main.py`, register the entrypoint on `backup_scheduler` beside audit cleanup, using `CronTrigger`, `coalesce=True`, `max_instances=1`, and `replace_existing=True`. Disabled retention is not registered.

4. **Boot:** In `backend/repositories/metric_repo.py:create_hypertable`, apply the policy after hypertable creation when retention is enabled. Fresh installs get it on first boot; existing installs are covered by the scheduler on the next deployment.

5. **Docs:** Update `docs/polling-pipeline-tuning.md` to retire the evidence caveat, citing issue #457 storage-growth evidence. Keep compression and downsampling deferred.

6. **Spec:** During sdd-spec, create `openspec/specs/time-series/spec.md` with the retention requirement and scenarios, mirroring `openspec/specs/audit-logging/spec.md:94-107`.

## Precedents and Boundary

- `run_audit_retention_cleanup` (`audit_service.py:288-295`).
- `_cleanup_old_backups` (`backup_service.py:472-478`).
- `EventPruneSettings` (fix-423).
- `add_retention_policy` is forward-looking only; it does not retroactively delete existing data.
- Existing rows are not pruned by the policy itself; no purge mechanism is added.

## Affected Files

| Path | Role |
|---|---|
| `backend/services/retention_service.py` | NEW policy service and scheduler entrypoint. |
| `backend/main.py` | Scheduler wiring and environment reload. |
| `backend/config.py` | `MetricRetentionSettings`, mirroring `EventPruneSettings`. |
| `.env.example` | `METRIC_RETENTION_DAYS` and `METRIC_RETENTION_ENABLED`. |
| `backend/repositories/metric_repo.py` | Boot-time policy application. |
| `docs/polling-pipeline-tuning.md` | Retire the evidence caveat. |
| `openspec/specs/time-series/spec.md` | New capability contract; untouched in proposal. |

## Strict-TDD Verification Anchor

Write RED tests first, then implement and turn them GREEN.

- Two consecutive `apply_metric_retention(90)` calls produce one `timescaledb_information.jobs` row.
- `apply_metric_retention(30)` yields `.config` `30 days 00:00:00`.
- `METRIC_RETENTION_ENABLED=false` prevents scheduler registration.
- Invalid `METRIC_RETENTION_DAYS` preserves the default.
- One explicit-time, 100-day-old write is excluded by the follow-up `pg_dump`-equivalent query.

Use unit boundaries plus TimescaleDB integration evidence.

## Risks

- Policy syntax, extension, or permissions may differ: run the real integration test.
- Expiry removes old telemetry: default 90 days, kill-switch, and explicit documentation.
- Existing storage may remain large: policy is forward-looking; no backfill is added.

## Rollback Plan

Disable `METRIC_RETENTION_ENABLED`, revert the application change, and remove any installed policy through standard TimescaleDB administration after backup confirmation. Restore from the pre-deployment dump if already-dropped chunks are needed; policy removal cannot restore deleted data.

## Dependencies

- TimescaleDB and the `metric_values` hypertable.
- Database permission to manage retention policies.
- Existing `backup_scheduler` lifecycle.

## Success Criteria

- [ ] One idempotent policy exists with the 90-day default.
- [ ] The 30-day interval and all five strict-TDD cases pass.
- [ ] Disabled/invalid settings behave safely.
- [ ] Boot and scheduler paths cover fresh and existing installs.
- [ ] Runbook and `time-series` contract document evidence and forward-only behavior.
- [ ] No out-of-scope capability is added.

## Delivery Boundary

- This phase writes only `proposal.md`.
- No code, test, or main-spec file is changed here.
- The next phase owns the `time-series` requirements.

## Next Step

Run `sdd-spec-minim`.

Do not modify `openspec/specs/time-series/spec.md` during this proposal phase.
