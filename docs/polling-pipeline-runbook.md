# Polling Pipeline Runbook

Operational runbook for the scalable metric polling pipeline. The legacy serial SNMP worker remains the rollback path until the whole chain is validated.

## Enablement order

Enable one layer at a time and keep the system observable between steps:

1. Set `POLLING_PIPELINE_OBSERVE_ONLY=true`; confirm current cycle duration and failure baseline.
2. Apply PostgreSQL queue migrations; then set `POLLING_PG_QUEUE_ENABLED=true`.
3. Run a synthetic benchmark with `backend/scripts/polling_host_benchmark.py` or `backend/scripts/polling_load_simulator.py` and attach the JSON report to the rollout notes.
4. Set `POLLING_SNMP_LEASED_WORKER=true` with low `POLLING_WORKERS` and small `POLLING_TASK_BATCH_SIZE`.
5. Set `POLLING_DB_WRITER_ENABLED=true` with `POLLING_DB_WRITERS=1` and conservative `POLLING_RESULT_BATCH_SIZE`.
6. Set `POLLING_BACKPRESSURE_ENABLED=true`.
7. Set `POLLING_METADATA_CACHE_ENABLED=true` after confirming cache TTL/version mismatch behavior in logs.
8. Raise workers/batches only after simulator evidence and live observability show headroom.

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
3. Disable `POLLING_DB_WRITER_ENABLED` and stop writer consumers.
4. Disable `POLLING_SNMP_LEASED_WORKER`.
5. Leave `POLLING_PG_QUEUE_ENABLED` data intact for replay/audit unless a maintainer approves cleanup.
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
