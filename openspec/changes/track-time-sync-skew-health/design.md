# Design: Track Time Sync Skew Health

## Technical Approach

Add a failure-isolated `time_sync` payload to `GET /api/system/status`. The backend will compare a midpoint backend UTC timestamp with Neo4j `datetime()`, report absolute skew in milliseconds, and classify it with bounded environment-backed thresholds. Existing liveness (`/`), readiness-style service fields, and system-status HTTP behavior remain unchanged.

## Architecture Decisions

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Add helper in `backend/main.py` | Matches current system-status pattern, but avoid large inline logic. | Use small helpers in `main.py`; keep threshold parsing in `config.py`. |
| Use Neo4j only first | Does not validate Postgres clock, but matches spec and timestamp risk from Neo4j `datetime()`. | Scope to backend-vs-Neo4j; Postgres remains follow-up. |
| Single local timestamp vs midpoint | Single timestamp is simpler; midpoint reduces round-trip noise. | Capture `before`/`after` around the Cypher call and compare Neo4j to midpoint. |
| Privileged container NTP | Could self-remediate, but increases privileges and violates scope. | Document host-level NTP/chrony/systemd-timesyncd only. |

## Data Flow

```text
GET /api/system/status
  ├─ existing CPU/RAM/disk/service checks
  ├─ _build_time_sync_status()
  │    ├─ backend before UTC
  │    ├─ Neo4j: RETURN datetime() AS neo4j_time
  │    ├─ backend after UTC
  │    └─ normalize → skew_ms → status
  └─ response.time_sync
```

Neo4j query or conversion failure returns `status: "UNKNOWN"` inside `time_sync` and logs a warning; it does not alter `neo4j`, `postgres`, HTTP status, or snapshot recording semantics.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/config.py` | Modify | Add `TimeSyncSettings` with `TIME_SYNC_WARNING_MS` default `1000`, `TIME_SYNC_CRITICAL_MS` default `5000`, bounded parsing, and cached getter. |
| `backend/main.py` | Modify | Add Neo4j time query, temporal normalization, status classification, and include `time_sync` in `_build_system_status_payload()`. |
| `backend/tests/test_system_status.py` | Modify | Add unit tests for OK/WARNING/CRITICAL, Neo4j query failure, invalid temporal values, and unchanged service fields. |
| `frontend/services/queryResources.ts` | Modify | Extend `SystemStatus` typing with optional `time_sync`; no UI change required. |
| `docker-compose.yml` | Modify | Add non-behavioral env visibility: `TZ=${TZ:-UTC}`, `TIME_SYNC_MODE=${TIME_SYNC_MODE:-host}`, and threshold envs to backend. |
| `.env.example` | Modify | Document `TZ`, `TIME_SYNC_MODE=host`, and threshold defaults. |
| `docs/time-sync-runbook.md` | Create | Host clock verification/remediation for NTP, chrony, and systemd-timesyncd; explicitly no in-container NTP. |

## Interfaces / Contracts

```json
"time_sync": {
  "status": "OK|WARNING|CRITICAL|UNKNOWN",
  "sources": { "reference": "backend", "compared": "neo4j" },
  "skew_ms": 42.5,
  "thresholds_ms": { "warning": 1000, "critical": 5000 },
  "backend_time": "2026-07-05T12:00:00.000Z",
  "neo4j_time": "2026-07-05T12:00:00.042Z",
  "measured_at": "2026-07-05T12:00:00.000Z",
  "query_latency_ms": 4.2,
  "error": null
}
```

For `UNKNOWN`, `skew_ms`, `neo4j_time`, and `query_latency_ms` may be `null`, with `error` set to a short non-secret reason.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Threshold mapping and threshold env fallback | Direct helper tests with monkeypatched settings/time values. |
| Unit | Neo4j temporal normalization | Fake session returning Python `datetime`, Neo4j-like `to_native()`, and invalid values. |
| Unit | Failure isolation | Fake Neo4j time query raises; assert `time_sync.status == "UNKNOWN"` and existing fields remain present. |
| Integration | Endpoint shape | Existing system-status payload test extended; no new external DB test required. |
| E2E | Not required | Backend telemetry-only change; docs cover operator workflow. |

## Migration / Rollout

No data migration required. Rollout is additive and backward compatible. Existing clients ignore the optional `time_sync` field; frontend type update prevents TypeScript drift. Operators manage real clock sync on hosts; container `TZ=UTC` is display/config consistency, not synchronization.

## Open Questions

None.
