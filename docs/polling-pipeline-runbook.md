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

## Out of scope

This runbook does not approve retention/compression changes, production MQTT semantics, or DB-backed load tests in production.
