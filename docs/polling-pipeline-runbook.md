# Polling Pipeline Runbook

Operational runbook for the scalable metric polling pipeline. The legacy serial SNMP worker remains the rollback path until the whole chain is validated.

## Enablement order

Enable one layer at a time and keep the system observable between steps. All behavior-changing flags are default-off; do not enable the next step until the current command and metrics are understood.

1. Set `POLLING_PIPELINE_OBSERVE_ONLY=true`; confirm current cycle duration and failure baseline.
2. Apply PostgreSQL queue migrations explicitly; migrations are not auto-run on startup:

   ```bash
   python backend/scripts/run_polling_migrations.py --dry-run
   python backend/scripts/run_polling_migrations.py
   ```

3. Set `POLLING_PG_QUEUE_ENABLED=true`, then enqueue a controlled test cycle from an approved JSON record export:

   ```bash
   python backend/scripts/polling_enqueue_cycle.py \
     --records-file /path/to/polling-records.json \
     --scheduled-for 2026-05-25T12:00:00Z \
     --config-version rollout-v1
   ```

   When `POLLING_METADATA_CACHE_ENABLED=true`, pass `--current-metadata-version` or use `--config-version` so stale exported records are rejected before enqueue. When `POLLING_BACKPRESSURE_ENABLED=true`, the command refuses cycles larger than `POLLING_BACKPRESSURE_MAX_TASK_QUEUE_DEPTH`.

4. Run a synthetic benchmark with `backend/scripts/polling_host_benchmark.py` or `backend/scripts/polling_load_simulator.py` and attach the JSON report to the rollout notes.
5. Set `POLLING_SNMP_LEASED_WORKER=true` with low `POLLING_WORKERS` and small `POLLING_TASK_BATCH_SIZE`.
6. Set `POLLING_DB_WRITER_ENABLED=true` with `POLLING_DB_WRITERS=1` and conservative `POLLING_RESULT_BATCH_SIZE`, then run the result writer under a supervisor:

   ```bash
   python backend/scripts/polling_result_writer.py --worker-id writer-1
   ```

7. Set `POLLING_BACKPRESSURE_ENABLED=true`; verify oversized cycle rejection with `backend/scripts/polling_enqueue_cycle.py --dry-run` before larger enqueues.
8. Set `POLLING_METADATA_CACHE_ENABLED=true` after confirming cache TTL/version mismatch behavior through `backend/scripts/polling_enqueue_cycle.py --current-metadata-version`.
9. Raise workers/batches only after simulator evidence and live observability show headroom.

## Evidence required before increasing concurrency

Do not increase `POLLING_WORKERS`, DB writers, or batch sizes until you have:

- simulator evidence for the intended CI/metric count and protocol mix;
- live cycle lag below the 15-minute target for at least three cycles;
- queue depth stable or decreasing;
- writer lag stable and below alert threshold;
- DB latency within the benchmark envelope;
- no increasing dead-letter count or Neo4j pending count;
- timeout rate understood by protocol and target/site.

## Emergency concurrency reduction

Use this emergency concurrency reduction procedure when devices, queues, or databases show pressure:

1. Set `POLLING_WORKERS=1` and reduce `POLLING_TASK_BATCH_SIZE`.
2. Set `POLLING_DB_WRITERS=1` and reduce `POLLING_RESULT_BATCH_SIZE`.
3. Keep `POLLING_BACKPRESSURE_ENABLED=true` so tasks defer instead of dropping data.
4. If pressure continues, set `POLLING_SNMP_LEASED_WORKER=false` to return to the legacy serial path.
5. Preserve queue rows for replay; do not delete queue tables during incident response.

## Rollback order

Rollback in reverse enablement order:

1. Disable `POLLING_METADATA_CACHE_ENABLED`.
2. Disable `POLLING_BACKPRESSURE_ENABLED` only if the queue is stable; otherwise leave it enabled while reducing concurrency.
3. Disable `POLLING_DB_WRITER_ENABLED` and stop `backend/scripts/polling_result_writer.py` consumers.
4. Disable `POLLING_SNMP_LEASED_WORKER`.
5. Disable `POLLING_PG_QUEUE_ENABLED` after queue consumers are stopped; leave queue data intact for replay/audit unless a maintainer approves cleanup.
6. Disable `POLLING_PIPELINE_OBSERVE_ONLY` last if legacy behavior is fully restored.

## Queue replay guidance

- Replay only rows with durable status `available`, `retry_wait`, `deferred`, or expired `leased` rows.
- Prefer raising `next_eligible_at` rather than editing timestamps backward.
- Replay by protocol/partition to avoid creating a sudden target storm.
- Keep ICMP/PING-CHECK first when communication validation is operationally urgent.
- Keep a copy of cycle IDs and replay counts in incident notes.

## Dead-letter handling

Dead-letter is not deletion. It means the task/result exceeded retry policy and needs operator review.

1. Group dead-letter rows by protocol, site, credential, endpoint, and error code.
2. Fix root causes such as bad credentials, invalid OIDs, unreachable sites, or parser errors.
3. Requeue only after the cause is corrected; otherwise keep the row dead-lettered with reason.
4. Never bulk requeue all dead-letter rows during an outage.

## Observability and alerts

Dashboard panels/alerts should include:

| Signal | Alert intent |
| --- | --- |
| cycle lag | Cycle approaches or exceeds 15 minutes. |
| queue depth | Backlog is growing instead of draining. |
| queue oldest age | Old tasks are not getting claimed. |
| lease expiries | Workers are crashing or lease TTL is too short. |
| worker p95/p99 | Protocol execution latency is rising. |
| timeout rate | SNMP/CLI/REST/ICMP targets are failing or timing out. |
| writer lag | Results are waiting too long before persistence. |
| DB latency | Timescale/PostgreSQL writes or Neo4j updates are slow. |
| dead-letter count | Data needs operator triage instead of automatic retry. |
| Neo4j pending | Timescale succeeded but event/latest update still needs retry. |

## Event writer coordination observability

Event deduplication across SNMP, legacy service, and polling result writers uses
the shared PostgreSQL advisory-lock helper in `backend/services/event_lock.py`.
Observability is intentionally lightweight: the current `/api/system/status`
payload exposes `event_lock` from the backend process that served the request.
In the default compose topology this is backend-process-local state; cross-process
aggregation, Prometheus/OpenTelemetry export, and scrape endpoints are future
work.

Stable snapshot contract:

```json
{
  "acquisitions_total": 0,
  "wait_ms": {"count": 0, "p95": null, "p99": null, "max": null},
  "alert_state": "OK",
  "thresholds_ms": {"info": 250.0, "warning_p95": 1000.0, "critical_p99": 5000.0},
  "by_writer": {}
}
```

- `acquisitions_total` is the successful lock-acquisition count in the current
  backend process.
- `wait_ms` contains bounded wait-duration samples for all writers in the
  process. Percentiles are `null` when no samples exist.
- `alert_state` is one of `OK`, `INFO`, `WARNING`, or `CRITICAL`.
- `thresholds_ms` reports the effective runtime thresholds.
- `by_writer` contains bounded writer-context labels such as `snmp_service`,
  `snmp_worker_icmp_availability`, and `polling_event_writer`. Raw CI, metric,
  and event-type triplet identifiers are not default labels.
- An empty `by_writer: {}` is valid before the process records any lock
  acquisition. Once the process records acquisitions, each writer key maps to
  the same bounded counter/distribution shape:

  ```json
  {
    "snmp_service": {
      "acquisitions_total": 12,
      "wait_ms": {"count": 12, "p95": 4.2, "p99": 5.1, "max": 5.1}
    },
    "polling_event_writer": {
      "acquisitions_total": 3,
      "wait_ms": {"count": 3, "p95": 1.7, "p99": 1.7, "max": 1.7}
    }
  }
  ```

  For every writer key, `acquisitions_total` is a number and `wait_ms` has
  `count` as a number plus `p95`, `p99`, and `max` as numbers or `null` when no
  samples exist.

If snapshot generation fails, `/api/system/status.event_lock` falls back to:

```json
{"alert_state": "UNKNOWN", "snapshot_error": true}
```

This fallback preserves the rest of the system-status payload and does not change
healthcheck, readiness, liveness, or HTTP status behavior.

### Coordination invariants

- All Event writers that must deduplicate each other MUST use the same
  PostgreSQL database identity. PostgreSQL advisory locks are scoped to a
  database; writers connected to different PostgreSQL databases cannot coordinate
  through this lock.
- Lock acquisition is transaction/session-scoped. The SQLAlchemy session passed
  to `acquire_event_triplet_lock(...)` MUST remain open until the following Neo4j
  Event create/update path completes. Commit, rollback, or session close releases
  the lock.
- Batched writers MUST continue deterministic sorted acquisition of distinct
  Event triplets before writes. This preserves stable lock order and avoids
  introducing deadlock-prone acquisition patterns.
- Observability MUST NOT introduce lock timeouts, fail-open behavior, or
  fail-closed behavior. Current behavior remains blocking via
  `pg_advisory_xact_lock(hashtext(:key))`.
- Issue #334 is the complementary CI guard for writer coverage. It protects
  future code changes from bypassing the shared lock helper; it does not replace
  runtime contention observability.

### Threshold tuning

Defaults are conservative and configurable by environment:

| Environment variable | Default | Purpose |
| --- | ---: | --- |
| `EVENT_LOCK_SLOW_LOG_INFO_MS` | `250` | Emit structured INFO slow-lock logs and derive INFO alert state. Set `0` to disable INFO slow-lock logging. |
| `EVENT_LOCK_WARNING_P95_MS` | `1000` | Derive WARNING when p95 wait meets or exceeds this value. |
| `EVENT_LOCK_CRITICAL_P99_MS` | `5000` | Derive CRITICAL when p99 wait meets or exceeds this value. |
| `EVENT_LOCK_SAMPLE_WINDOW_SIZE` | `500` | Bound retained wait samples per process and writer context. |
| `EVENT_LOCK_MAX_WRITER_CONTEXTS` | `20` | Bound writer-context label cardinality; overflow rolls into `other`. |

Tune thresholds only after comparing live wait percentiles against normal cycle
duration and database latency. No threshold changes should be treated as an
approval to increase polling concurrency by themselves.

## Out of scope

This runbook does not approve retention/compression changes, production MQTT semantics, or DB-backed load tests in production.
