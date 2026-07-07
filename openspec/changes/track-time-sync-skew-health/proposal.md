# Proposal: Track Time Sync Skew Health

## Intent

Expose backend-vs-Neo4j clock-skew telemetry so operators can detect timestamp drift that may affect event/history interpretation, without changing healthcheck pass/fail behavior or running privileged NTP inside containers.

## Scope

### In Scope
- Add a `time_sync` section to `GET /api/system/status` for backend-vs-Neo4j skew.
- Report states equivalent to `OK`, `WARNING`, `CRITICAL`, and `UNKNOWN` with threshold metadata.
- Document host-level NTP/chrony/systemd-timesyncd expectations and remediation.
- Add backward-compatible env/Compose visibility such as `TZ=UTC` or documentation-only time-sync mode.

### Out of Scope
- Privileged in-container NTP/chrony/systemd management.
- Changing liveness/readiness semantics based on clock skew.
- Mandatory Postgres skew telemetry in the first slice.

## Capabilities

### New Capabilities
- `time-sync-skew-health`: Runtime status telemetry and operator guidance for backend-to-Neo4j clock skew.

### Modified Capabilities
- None.

## Approach

Add a small failure-isolated helper in the system-status path that captures backend UTC time near a Neo4j `datetime()` query, normalizes the returned value, computes absolute skew in milliseconds, and maps it to configured/documented status thresholds. Return `UNKNOWN` when the Neo4j time query fails while preserving existing connectivity fields. Add focused unit tests for OK/WARNING/CRITICAL/UNKNOWN and operator docs for host clock synchronization.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/main.py` | Modified | Extend `/api/system/status` payload construction. |
| `backend/database.py` | Modified | Reuse existing Neo4j driver/session access if needed. |
| `backend/tests/test_system_status.py` | Modified | Cover skew status mapping and failure isolation. |
| `docker-compose.yml`, `.env.example` | Modified | Add backward-compatible timezone/time-sync visibility if useful. |
| `README.md` or `docs/` | Modified/New | Add NTP/chrony/systemd-timesyncd remediation runbook. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Neo4j driver returns temporal objects needing conversion | Med | Normalize explicitly and unit-test conversion. |
| Query latency adds measurement noise | Low | Capture local time close to the query or use midpoint calculation. |
| Operators assume containers run NTP | Med | Docs state containers inherit host time; no privileged NTP is implemented. |

## Rollback Plan

Remove the `time_sync` payload helper/tests and revert env/docs additions. Existing status, liveness, readiness, collector, Neo4j, and PostgreSQL checks remain independent.

## Dependencies

- Existing Neo4j driver access from the backend.
- Host-level time synchronization managed outside application containers.

## Success Criteria

- [ ] `/api/system/status` reports backend-vs-Neo4j skew with OK/WARNING/CRITICAL/UNKNOWN semantics.
- [ ] Neo4j time-query failure returns `UNKNOWN` without failing liveness/readiness.
- [ ] Operator docs explain host NTP/chrony/systemd-timesyncd verification and remediation.
