## Exploration: Track host-level time synchronization and clock-skew health checks

### Current State
`GET /api/system/status` is implemented directly in `backend/main.py` through `_build_system_status_payload()`. It reports OS resource usage, Neo4j connectivity via `database.verify_connection(max_retries=1, retry_delay=0)`, PostgreSQL connectivity via `SELECT 1`, collector status, event-lock observability, and startup time. The endpoint is informational only; it does not record history on request and should not alter liveness/readiness behavior.

Neo4j access is centralized for the API through `backend/database.py`, which creates a global Neo4j driver. Existing backend and worker event writers frequently use Neo4j `datetime()` in Cypher, while backend-side history uses Python UTC normalization. There is no current backend-vs-Neo4j clock-skew measurement, no database time query in `/api/system/status`, and no `TZ`/`TIME_SYNC_MODE` visibility in Compose or `.env.example`.

Deployment documentation covers safe rebuilds, backups, Compose validation, and polling rollout, but it does not document host-level NTP/chrony/systemd-timesyncd expectations or remediation steps for clock drift.

### Affected Areas
- `backend/main.py` — owns `/api/system/status`, service connectivity checks, system-status history serialization, and the best insertion point for clock-skew payload construction.
- `backend/database.py` — exposes the global Neo4j driver; a skew check can reuse `get_db()`/driver sessions rather than creating a second driver.
- `backend/postgres_db.py` — exposes SQLAlchemy `engine`; if Postgres time is included, reuse the existing connection pattern already used by status checks.
- `backend/tests/test_system_status.py` — existing focused unit-test file for system-status payload behavior; best place for normal, warning, critical, and database-unavailable skew cases.
- `docker-compose.yml` — backend, worker, Neo4j, and Postgres environment blocks currently omit timezone/time-sync visibility.
- `.env.example` — operator-facing env template currently omits `TZ` and documentation-only `TIME_SYNC_MODE`/equivalent.
- `README.md` and/or a new focused docs runbook under `docs/` — current deployment guidance is operator-facing but lacks host clock synchronization requirements.

### Approaches
1. **Backend-vs-Neo4j skew only in `/api/system/status`** — Add a small helper that captures backend UTC time, queries Neo4j `datetime()`, computes absolute skew in milliseconds, maps it to `OK`/`WARNING`/`CRITICAL`/`UNKNOWN`, and returns it under a new `time_sync` payload.
   - Pros: Matches triage boundary; minimal moving parts; directly covers the timestamp source most exposed in event Cypher writes; easy to unit test with monkeypatches.
   - Cons: Does not prove Postgres clock alignment; DB query latency introduces small measurement noise unless measured carefully.
   - Effort: Low/Medium

2. **Backend-vs-Neo4j plus optional Postgres time visibility** — Extend the same payload to include Neo4j skew and Postgres skew, using `SELECT now()` for Postgres.
   - Pros: More complete for mixed Python/Neo4j/Postgres time semantics and Timescale history; useful for operators diagnosing all persistence layers.
   - Cons: Broader than the explicit triage focus on backend/database skew; more failure combinations; higher test matrix; risks conflating connectivity status with skew health.
   - Effort: Medium

3. **Documentation/env visibility only** — Add `TZ=UTC`, `TIME_SYNC_MODE=host`, and NTP/chrony/systemd-timesyncd runbook guidance without runtime skew measurement.
   - Pros: Very safe; no runtime behavior change; satisfies deployment expectation documentation.
   - Cons: Fails the triage requirement to expose backend/database clock-skew status in `/api/system/status`; no automated evidence for warning/critical/unavailable cases.
   - Effort: Low

### Recommendation
Use Approach 1 as the implementation baseline, with documentation/env visibility from Approach 3. Add a bounded `time_sync` section to `/api/system/status` that reports backend-vs-Neo4j skew and threshold metadata without affecting healthcheck pass/fail behavior. Keep Postgres skew as an explicitly optional follow-up unless the proposal/spec expands scope, because the issue's triage boundary names backend/database skew but the timestamp-risk driver is Neo4j `datetime()` vs Python UTC event timestamps.

The payload should be failure-isolated like `event_lock`: if the Neo4j time query fails, return an `UNKNOWN`/unavailable skew status while preserving existing `neo4j` and `postgres` connectivity fields. Thresholds should be documented and testable; a conservative initial shape is normal below warning, WARNING at moderate skew, and CRITICAL at severe skew, with exact millisecond thresholds defined in the spec/design.

### Risks
- Neo4j temporal values returned by the Python driver may be Neo4j temporal objects rather than Python `datetime`; implementation should normalize explicitly and tests should cover the conversion path.
- Measuring skew with a single request includes round-trip latency. The helper should capture local time close to the DB query and either accept small noise or use a midpoint calculation.
- Adding Compose timezone env to all services is safe, but docs must be clear that containers inherit host time and this change does not run NTP inside containers.
- `/api/system/status` currently uses direct helper functions in `main.py`; adding too much logic there could worsen file sprawl. Keep helper functions small or move a focused service only if design justifies it.
- Documentation language is mixed today, but SDD artifacts should remain English; user-facing docs should follow existing project style unless the spec chooses otherwise.

### Ready for Proposal
Yes — propose a narrow, non-invasive change: expose backend-vs-Neo4j clock-skew telemetry in `/api/system/status`, add `TZ=UTC` and documentation-only host time-sync visibility to env/Compose, document host NTP/chrony/systemd-timesyncd requirements/remediation, and add focused tests for normal, warning, critical, and DB-unavailable cases. Explicitly preserve liveness/readiness behavior and avoid privileged in-container NTP.
