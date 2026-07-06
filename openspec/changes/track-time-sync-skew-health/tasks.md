# Tasks: Track Time Sync Skew Health

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 350-550 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Single PR with work-unit commits: tests+backend, config/env, docs+frontend type |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Add tested backend `time_sync` telemetry | PR 1 | Test-first; no liveness/readiness changes |
| 2 | Expose config/env and operator docs | PR 1 | Keep docs with deploy-visible settings |
| 3 | Update optional frontend type | PR 1 | Type-only compatibility update |

## Phase 1: Test-First Backend Coverage

- [x] 1.1 Add failing tests in `backend/tests/test_system_status.py` for `time_sync.status` OK/WARNING/CRITICAL using fixed backend/Neo4j times.
- [x] 1.2 Add failing tests in `backend/tests/test_system_status.py` for Neo4j query failure and invalid temporal values returning `UNKNOWN`.
- [x] 1.3 Add failing assertion in `backend/tests/test_system_status.py` that existing `neo4j`, `postgres`, `collector`, and HTTP payload behavior remain unchanged.

## Phase 2: Backend Implementation

- [x] 2.1 Add `TimeSyncSettings` and cached env parsing in `backend/config.py` for `TIME_SYNC_WARNING_MS=1000` and `TIME_SYNC_CRITICAL_MS=5000` with safe bounds/fallbacks.
- [x] 2.2 Add helpers in `backend/main.py` to query `RETURN datetime() AS neo4j_time`, capture before/after UTC, compute midpoint, latency, and absolute `skew_ms`.
- [x] 2.3 Add temporal normalization in `backend/main.py` for Python `datetime`, Neo4j-like `to_native()`, ISO strings, and unusable values.
- [x] 2.4 Add threshold classification in `backend/main.py` producing `OK`, `WARNING`, `CRITICAL`, or `UNKNOWN` with non-secret error text.
- [x] 2.5 Include `time_sync` in `_build_system_status_payload()` without changing liveness/readiness or existing service fields.

## Phase 3: Configuration, Docs, and Frontend Contract

- [x] 3.1 Add backend env visibility in `docker-compose.yml`: `TZ`, `TIME_SYNC_MODE=host`, `TIME_SYNC_WARNING_MS`, and `TIME_SYNC_CRITICAL_MS`.
- [x] 3.2 Document the same settings and defaults in `.env.example`, stating `TZ=UTC` is not clock synchronization.
- [x] 3.3 Create `docs/time-sync-runbook.md` with host NTP, chrony, and systemd-timesyncd verification/remediation; explicitly exclude privileged in-container NTP.
- [x] 3.4 Extend `SystemStatus` in `frontend/services/queryResources.ts` with optional `time_sync` payload types; do not add UI behavior.

## Phase 4: Verification

- [ ] 4.1 Run `cd backend && python -m pytest backend/tests/test_system_status.py` or the repo-correct equivalent from `backend/pytest.ini`.
- [ ] 4.2 If frontend type checks exist in `frontend/package.json`, run the relevant type/test command for `frontend/services/queryResources.ts`.
- [x] 4.3 Review `openspec/changes/track-time-sync-skew-health/specs/time-sync-skew-health/spec.md` scenarios against implemented tests and mark tasks complete.
