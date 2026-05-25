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

## Queue partitions

- Partition by protocol plus site/subnet/CI hash so one hot site does not block the whole queue.
- Keep ICMP/PING-CHECK priority `0` and claim it before normal scheduled metrics.
- Increase partition count only when claim latency or queue depth proves contention.
- Watch lease expiries after changing partitions; uneven partitions can look like worker crashes.

## Worker counts

Start with low `POLLING_WORKERS` and raise gradually:

1. Run synthetic benchmark.
2. Enable leased worker with `POLLING_SNMP_LEASED_WORKER=true`.
3. Observe worker p95/p99, timeout rate, device CPU/link health, and queue depth.
4. Raise workers only if queue depth drains and target safety limits are not frequently denying work.

Suggested first production setting: `POLLING_WORKERS=4` to `8`, then tune by evidence.

## Lease TTL

Lease TTL should exceed normal p99 protocol latency plus batch overhead. Too short causes lease expiries and duplicate work; too long delays recovery from crashed workers.

- Start near 2-3x observed worker p99 latency.
- Alert on repeated lease expiries.
- Keep expired rows replayable; do not delete them.

## Batch sizes

- `POLLING_TASK_BATCH_SIZE`: start small, e.g. `100`; raise when workers are underutilized and queue claim overhead dominates.
- `POLLING_RESULT_BATCH_SIZE`: start at `500`; tune against DB latency and writer lag.
- Keep DB writer transactions short enough to retry safely.
- If DB latency rises, reduce result batch size before adding more writers.

## Retry/backoff/dead-letter

- `POLLING_BACKPRESSURE_RETRY_MAX_ATTEMPTS` defaults to a capped value; do not raise it to hide credential/OID problems.
- Repeated SNMP/CLI/REST failures should enter cooldown or dead-letter with reason.
- Under pressure, ICMP remains first; lower-priority work is delayed, not silently lost.

## Cache TTL/versioning

- `POLLING_METADATA_CACHE_TTL_SECONDS` defaults to 300 seconds.
- Lower TTL when CI/metric definitions change frequently.
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
