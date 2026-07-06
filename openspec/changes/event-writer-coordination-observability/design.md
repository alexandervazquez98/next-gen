# Design: Event Writer Coordination Observability

## Technical Approach

Instrument the existing shared Event advisory-lock helper and preserve the current writer topology. `backend/services/event_lock.py` remains the only primitive that executes `SELECT pg_advisory_xact_lock(hashtext(:key))`; it will measure elapsed blocking time, record bounded in-process metrics, emit slow-lock logs, and expose a snapshot/alert helper for status reporting. Call sites only add stable writer context labels. No timeout, exporter, fail-open/fail-closed policy, or readiness/liveness behavior is introduced.

## Architecture Decisions

| Option | Tradeoff | Decision |
|---|---|---|
| Instrument `event_lock.py` centrally | Lowest semantic risk; all protected writers already converge there | Use this; avoid touching Neo4j Event write/dedup Cypher beyond context arguments |
| Add Prometheus/OpenTelemetry/exporter | Better external integration but adds dependency and endpoint scope | Defer; first slice uses in-process Python state with exporter-ready snapshot shape |
| Use lock wait as healthcheck failure | Visible to orchestration but can restart healthy blocked writers | Do not degrade `/` or `/api/system/status`; report `event_lock.alert_state` only |
| Add lock timeout policy | Reduces blocking but requires fail-open/fail-closed product decision | Out of scope; keep PostgreSQL blocking semantics unchanged |

## Data Flow

```text
Event writer -> acquire_event_triplet_lock(writer=...)
             -> pg_advisory_xact_lock blocks until acquired
             -> EventLockMetrics records count/wait
             -> slow log if wait >= INFO threshold
             -> existing Neo4j Event create/update path

/api/system/status -> get_event_lock_observability_snapshot()
                   -> derived INFO/WARNING/CRITICAL alert_state
                   -> payload only; no status-code or health degradation
```

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/config.py` | Modify | Add `EventLockSettings` and cached env-backed lock observability settings: INFO `250ms`, p95 WARNING `1000ms`, p99 CRITICAL `5000ms`, bounded window/sample size. PR1 scope. |
| `backend/services/event_lock.py` | Modify | Add bounded in-memory metrics, percentile/alert snapshot, slow-lock structured logging, optional `writer_context` argument. Preserve SQL and blocking semantics. PR1 scope. |
| `backend/engines/snmp_worker.py` | Modify | Pass bounded writer contexts for collection failure, ICMP availability, and threshold breach lock acquisitions. Keep sorted acquisition order. Later slice: PR2. |
| `backend/services/snmp_service.py` | Modify | Pass legacy writer context while keeping the existing PostgreSQL session open across the Neo4j write. Later slice: PR2. |
| `backend/polling/event_writer.py` | Modify | Thread `writer_context="polling_event_writer"` through sorted batch lock acquisition without changing distinct-triplet sorting. Later slice: PR2. |
| `backend/main.py` | Modify | Add `event_lock` snapshot to `/api/system/status`; do not alter root healthcheck, service status strings, or HTTP status behavior. Later slice: PR2. |
| `backend/tests/test_writer_advisory_lock.py` | Modify | Unit-test SQL preservation, metrics recording, alert thresholds, no timeout SQL/settings, and slow-lock logging. |
| `backend/tests/test_snmp_worker.py`, `backend/tests/test_snmp_service_collection_failures.py`, `backend/tests/test_polling_event_writer.py` | Modify | Assert call sites pass expected writer context while keeping current lock counts/order. Later slice: PR2. |
| `backend/tests/test_system_status.py` | Modify | Assert status payload includes lock observability without changing health semantics. Later slice: PR2. |
| `docs/polling-pipeline-runbook.md` | Modify | Document shared PostgreSQL identity, session lifetime, sorted locks, thresholds, and #334 as complementary CI coverage. Later slice: PR3. |

## Interfaces / Contracts

```python
def acquire_event_triplet_lock(pg_db, ci_id: str, metric_id: str, event_type: str, *, writer_context: str = "unknown") -> None: ...
def get_event_lock_observability_snapshot() -> dict: ...
def reset_event_lock_observability_for_tests() -> None: ...
```

Snapshot contract: `{"acquisitions_total": int, "wait_ms": {"count": int, "p95": float|None, "p99": float|None, "max": float|None}, "alert_state": "OK|INFO|WARNING|CRITICAL", "thresholds_ms": {...}, "by_writer": {...}}`. Labels are bounded writer contexts only; raw triplet IDs are not default labels.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | Metrics, percentiles, alert state, slow-log threshold, SQL unchanged | pytest with fake clock/MagicMock/caplog in `test_writer_advisory_lock.py` |
| Integration-ish | Writer context propagation and sorted lock order | Existing patched writer tests; update expected calls without real DB |
| API | Status payload exposes lock state without health degradation | `test_system_status.py`; root endpoint unchanged |
| E2E | None in first slice | Existing real-Postgres advisory-lock blocking tests remain the semantic proof |

## Migration / Rollout

No migration required. Rollout is code-only, dependency-free, and reversible. Operators may tune thresholds by environment variables after deploy.

## Open Questions

None blocking. Future exporter integration and lock timeout policy remain separate decisions.
