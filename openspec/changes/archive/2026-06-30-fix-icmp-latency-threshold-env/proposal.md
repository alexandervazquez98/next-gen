# Proposal: Fix ICMP Latency Threshold Environment Propagation

## Intent

Containerized ICMP latency evaluation ignores operator-configured warning/critical thresholds because Compose reads `.env` for interpolation but does not export those variables into containers unless listed. This makes alerts fall back to `100/500ms` defaults even when `.env` sets different values.

## Scope

### In Scope
- Pass `ICMP_LATENCY_WARNING_MS` and `ICMP_LATENCY_CRITICAL_MS` into every Compose service that executes `get_icmp_settings()`.
- Keep the fix Compose-only unless validation proves Python config parsing is broken.
- Define minimum evidence: rendered Compose config includes both variables for affected services, and existing Python env parsing tests still pass.

### Out of Scope
- Changing ICMP threshold defaults or validation rules in Python.
- Refactoring Compose env management into anchors/shared files.
- Adding new ICMP latency product behavior beyond honoring existing env vars.

## Capabilities

### New Capabilities
- `icmp-latency-threshold-env`: Containerized ICMP latency threshold consumers receive operator-configured warning/critical env vars.

### Modified Capabilities
- None

## Approach

Use a configuration-only fix. Add `ICMP_LATENCY_WARNING_MS=${ICMP_LATENCY_WARNING_MS:-100}` and `ICMP_LATENCY_CRITICAL_MS=${ICMP_LATENCY_CRITICAL_MS:-500}` to `backend` and `snmp-engine` in `docker-compose.yml`. This is explicit and low-risk: Python already reads, validates, and caches these env vars; Compose is the missing propagation layer. Do not touch Python unless validation reveals an application defect.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `docker-compose.yml` | Modified | Export latency thresholds to `backend` and `snmp-engine`. |
| `backend/config.py` | Unchanged | Existing defaults/validation remain source of truth. |
| `backend/polling/writer_pool.py` | Unchanged | Receives configured thresholds via backend env. |
| `backend/engines/snmp_worker.py` | Unchanged | Receives configured thresholds via snmp-engine env. |
| `backend/repositories/topology_repo.py` | Unchanged | Receives configured thresholds via backend env. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Missing a runtime service | Low | Limit to services running backend Python code that imports `get_icmp_settings()`: `backend`, `snmp-engine`. |
| YAML/env interpolation mistake | Low | Run `docker compose config --quiet` and inspect rendered service env. |
| Operators expect live reload | Med | Document/rely on container recreation; `get_icmp_settings()` is process-cached. |

## Rollback Plan

Revert the `docker-compose.yml` environment additions and recreate affected containers; behavior returns to existing Python defaults or explicitly injected external env.

## Dependencies

- Docker Compose configuration rendering available for validation.

## Success Criteria

- [ ] `docker compose config --quiet` succeeds.
- [ ] Rendered `backend` and `snmp-engine` environments contain both ICMP latency threshold variables with configured/default values.
- [ ] Existing backend ICMP settings tests pass or are documented if not runnable.
