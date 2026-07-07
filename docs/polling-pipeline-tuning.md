# Polling Pipeline Tuning Guide

Use this guide to tune the scalable polling pipeline after PR7 simulator evidence and before any production rollout. Defaults are conservative on purpose.

## Benchmark procedure

Start synthetic; use DB-backed mode only in non-production.

```bash
python backend/scripts/polling_load_simulator.py --json
python backend/scripts/polling_host_benchmark.py \
  --ci-count 8000 \
  --metrics-per-ci 35 \
  --protocol-mix ICMP:0.15,SNMP:0.55,CLI:0.15,REST:0.10,MQTT_STUB:0.05 \
  --workers 8 \
  --db-writers 1 \
  --sink synthetic \
  --json
```

For DB-backed staging tests only:

```bash
python backend/scripts/polling_host_benchmark.py --sink db --allow-db --json
```

Do not use DB-backed mode on production without a maintenance window and rollback owner.

## Event writer advisory-lock load evidence

Use this harness when changing event writer lock behavior or validating runner/database capacity. It compares writers contending on the same `(ci_id, metric_id, event_type)` triplet with writers using disjoint triplets and emits machine-readable JSON.

```bash
cd backend
python scripts/event_writer_lock_load.py \
  --writers 2 \
  --iterations 20 \
  --event-write-ms 25 \
  --workload-timeout-s 120 \
  > event-writer-lock-load.json
```

Requirements:

- PostgreSQL reachable through the normal backend environment variables (`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, or `RUNNING_LOCALLY=true` for localhost).
- Python backend dependencies installed, including SQLAlchemy and `psycopg2-binary`.
- A non-production database or an approved maintenance window. The script only takes transaction-scoped advisory locks and does not write application rows, but it still opens concurrent database sessions.

Interpretation:

- `workloads.same_triplet.lock_wait` should show higher wait than `workloads.disjoint_triplets.lock_wait` when contention is real.
- `event_write` measures the protected write window while the lock is held; tune `--event-write-ms` to approximate observed Neo4j Event write latency.
- `--workload-timeout-s` defaults to `120` seconds per threaded workload. It bounds how long the parent waits for worker results; workers run in daemon threads so a timed-out CLI can return non-zero instead of keeping the process alive. Database lock and statement timeouts still provide the first line of cleanup for PostgreSQL waits.
- Treat the JSON as baseline evidence, not a CI performance gate. The harness hard-fails only on argument, connection, lock acquisition, timeout, or execution errors; it has no default timing threshold.

## Queue partitions

- Partition by protocol plus site/subnet/CI hash so one hot site does not block the whole queue.
- Keep ICMP/PING-CHECK priority `0` and claim it before normal scheduled metrics.
- Increase partition count only when claim latency or queue depth proves contention.
- Watch lease expiries after changing partitions; uneven partitions can look like worker crashes.

## Worker counts

Start with low `POLLING_WORKERS` and raise gradually:

1. Run synthetic benchmark.
2. Apply migrations with `backend/scripts/run_polling_migrations.py` and enqueue only a controlled cycle with `backend/scripts/polling_enqueue_cycle.py` after `POLLING_PG_QUEUE_ENABLED=true`.
3. Enable leased worker with `POLLING_SNMP_LEASED_WORKER=true`.
4. Observe worker p95/p99, timeout rate, device CPU/link health, and queue depth.
5. Raise workers only if queue depth drains and target safety limits are not frequently denying work.

Suggested first production setting: `POLLING_WORKERS=4` to `8`, then tune by evidence.

## Lease TTL

Lease TTL should exceed normal p99 protocol latency plus batch overhead. Too short causes lease expiries and duplicate work; too long delays recovery from crashed workers.

- Start near 2-3x observed worker p99 latency.
- Alert on repeated lease expiries.
- Keep expired rows replayable; do not delete them.

## Batch sizes

- `POLLING_TASK_BATCH_SIZE`: start small, e.g. `100`; raise when workers are underutilized and queue claim overhead dominates.
- `POLLING_RESULT_BATCH_SIZE`: start at `500`; tune against DB latency and writer lag.
- Run `backend/scripts/polling_result_writer.py --worker-id writer-1` under a supervisor only after `POLLING_DB_WRITER_ENABLED=true`.
- Keep DB writer transactions short enough to retry safely.
- If DB latency rises, reduce result batch size before adding more writers.

## Retry/backoff/dead-letter

- `POLLING_BACKPRESSURE_RETRY_MAX_ATTEMPTS` defaults to a capped value; do not raise it to hide credential/OID problems.
- Use `backend/scripts/polling_enqueue_cycle.py --dry-run` to validate that `POLLING_BACKPRESSURE_ENABLED=true` rejects enqueues above `POLLING_BACKPRESSURE_MAX_TASK_QUEUE_DEPTH`.
- Repeated SNMP/CLI/REST failures should enter cooldown or dead-letter with reason.
- Under pressure, ICMP remains first; lower-priority work is delayed, not silently lost.

## Cache TTL/versioning

- `POLLING_METADATA_CACHE_TTL_SECONDS` defaults to 300 seconds.
- Lower TTL when CI/metric definitions change frequently.
- With `POLLING_METADATA_CACHE_ENABLED=true`, pass `--current-metadata-version` to `backend/scripts/polling_enqueue_cycle.py` so stale metadata is rejected before queue insertion.
- Stale metadata must refresh or defer; it must not drive polling beyond the freshness window.
- Cache only safe credential refs/session metadata. Do not cache secrets.

## Timescale/PostgreSQL tuning notes

- Keep raw recent telemetry available for forensic investigations.
- Do not enable retention, compression, or downsampling changes until benchmark and storage-growth evidence exists.
- Watch DB latency, insert rows/sec, idempotent conflicts, chunk health, and storage growth.
- The sidecar receipt table protects idempotency; do not purge it before result replay windows close.

## Neo4j tuning notes

- Use batch updates with `UNWIND` and keep batch sizes within transaction memory.
- Watch Neo4j pending count and transaction latency separately from Timescale writes.
- If Neo4j pending rises while Timescale succeeds, pause writer scaling and investigate event/latest update latency.

## Dashboard targets

A minimum dashboard should show cycle lag, queue depth, queue oldest age, lease expiries, worker p95/p99, timeout rate, writer lag, DB latency, dead-letter count, Neo4j pending, and simulator evidence from the last scale validation.
