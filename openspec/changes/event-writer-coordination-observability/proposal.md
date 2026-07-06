# Proposal: Event Writer Coordination Observability

## Intent

Make PostgreSQL advisory-lock coordination for cross-writer Event deduplication observable without changing Event write semantics. Operators need runtime evidence of lock acquisition volume, wait latency, slow-lock conditions, and derived alert state while #334 remains the CI guard for future writer coverage.

## Scope

### PR1 Boundary Note

PR1 is limited to the metrics/settings/logging core in `backend/config.py`, `backend/services/event_lock.py`, and focused lock-helper tests. Writer/status wiring and operator documentation remain later chained slices (PR2 and PR3 respectively) even where listed as affected areas for the full change.

### In Scope
- Add lightweight in-process lock metrics and structured logs around shared Event triplet lock acquisition.
- Surface real application alert state from lock metrics: INFO above 250ms, WARNING when p95 exceeds 1s, CRITICAL when p99 exceeds 5s over the configured window.
- Document shared PostgreSQL/session-lifetime invariants and how #334 complements runtime observability.

### Out of Scope
- Prometheus/OpenTelemetry/exporter dependencies or scrape endpoint.
- Fail-open/fail-closed lock timeout behavior; this slice only measures and logs waits.
- Liveness/readiness degradation from lock contention.
- Reimplementing or expanding the #334 CI guard, except as an integration reference.

## Capabilities

### New Capabilities
- `event-writer-coordination-observability`: Runtime metrics, structured logs, alert state, and operational invariants for Event writer advisory-lock coordination.

### Modified Capabilities
- None; existing Event deduplication behavior remains unchanged.

## Approach

Instrument `backend/services/event_lock.py` as the central lock helper. Add writer/context labels at protected call sites, keep metric state in-process with a stable internal model for a future exporter adapter, and derive alert state from configurable conservative thresholds. Preserve `pg_advisory_xact_lock` blocking semantics and deterministic sorted lock acquisition.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/services/event_lock.py` | Modified | Measure acquisition count/wait duration, emit slow-lock logs, maintain alert state. |
| `backend/engines/snmp_worker.py` | Modified | Pass writer context to shared lock helper. |
| `backend/services/snmp_service.py` | Modified | Pass legacy writer context while preserving session lifetime. |
| `backend/polling/event_writer.py` | Modified | Pass batch writer context without changing sorted acquisition. |
| `backend/tests/*event*lock*` | Modified | Cover metrics/logging semantics without changing lock behavior. |
| `docs/itsm/event-flow.md` or runbook | Modified | Document invariants, thresholds, and #334 relationship. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Metric/log cardinality from triplet labels | Med | Use writer/status labels; avoid raw high-cardinality IDs in default logs. |
| Alert thresholds too noisy | Med | Use conservative configurable defaults and document rationale. |
| Observability changes lock semantics | Low | Centralize timing around existing acquisition and test no timeout behavior. |

## Rollback Plan

Revert the proposal implementation commit(s). Event writers fall back to existing advisory-lock behavior because no schema, dependency, exporter, or timeout policy changes are introduced.

## Dependencies

- Existing #322 advisory-lock helper and protected writers.
- #334 CI guard remains an external coverage guard only.

## Success Criteria

- [ ] Lock acquisition count, wait latency, slow-lock logs, and alert state are available in-process.
- [ ] Thresholds default to 250ms INFO, 1s p95 WARNING, 5s p99 CRITICAL and are configurable where appropriate.
- [ ] Tests prove Event deduplication semantics and healthcheck behavior remain unchanged.
