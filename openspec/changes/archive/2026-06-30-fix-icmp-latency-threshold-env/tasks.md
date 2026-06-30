# Tasks: Fix ICMP Latency Threshold Environment Propagation

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 20-60 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Propagate existing ICMP latency threshold env vars to affected Compose services and verify render behavior | PR 1 | Single config-only fix with evidence; keep tests with the change |

## Phase 1: Baseline Evidence

- [x] 1.1 RED: Render `docker-compose.yml` with configured threshold env values and confirm `backend`/`snmp-engine` currently miss `ICMP_LATENCY_WARNING_MS` and `ICMP_LATENCY_CRITICAL_MS`.
- [x] 1.2 RED: Render `docker-compose.yml` without threshold env values and confirm affected services do not explicitly receive default `100`/`500` values.

## Phase 2: Compose Propagation

- [x] 2.1 Add `ICMP_LATENCY_WARNING_MS=${ICMP_LATENCY_WARNING_MS:-100}` to `backend.environment` in `docker-compose.yml`.
- [x] 2.2 Add `ICMP_LATENCY_CRITICAL_MS=${ICMP_LATENCY_CRITICAL_MS:-500}` to `backend.environment` in `docker-compose.yml`.
- [x] 2.3 Add both ICMP latency threshold variables with matching defaults to `snmp-engine.environment` in `docker-compose.yml`.
- [x] 2.4 Do not modify `backend/config.py` or ICMP threshold product semantics unless validation reveals an application defect.

## Phase 3: Verification

- [x] 3.1 GREEN: Run `docker compose config --quiet` to validate Compose syntax after the list-style environment edits.
- [x] 3.2 GREEN: Inspect rendered `docker compose config` with configured env values and verify `backend` and `snmp-engine` receive both configured thresholds.
- [x] 3.3 GREEN: Inspect rendered `docker compose config` with omitted env values and verify both affected services receive default `100`/`500` thresholds.
- [x] 3.4 Verify non-consuming services are not required to receive the new variables.
- [x] 3.5 Run targeted backend ICMP settings tests, e.g. `cd backend && python -m pytest backend/tests/test_snmp_worker.py -k ICMPSettings`, or document why unavailable.

## Phase 4: Cleanup

- [x] 4.1 REFACTOR: Keep the final diff limited to the focused Compose change plus necessary evidence notes.
- [x] 4.2 Update `openspec/changes/fix-icmp-latency-threshold-env/tasks.md` task checkboxes during apply.
