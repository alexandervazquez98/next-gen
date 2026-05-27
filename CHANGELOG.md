# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.12.7] — 2026-05-27

### Added
- **ICMP latency and jitter telemetry** (PR #177, issue #175):
  - Preserves existing binary ICMP availability metrics for event lifecycle compatibility while adding `icmp_latency_ms` and `icmp_jitter_ms` sidecar telemetry streams.
  - Parses successful ping latency, stores latency only on successful probes, and calculates jitter as the absolute delta between consecutive successful latency samples.
  - Guards legacy and leased polling paths so latency/jitter metrics are never polled or evaluated as availability events.
  - Adds an idempotent migration script for existing CIs with ping metrics: `backend/scripts/migrate_icmp_sidecar_metrics.py`.
  - Adds focused backend regression coverage for parser semantics, event safety, scheduler/executor guards, writer sidecar persistence, and migration idempotency.

## [1.12.6] — 2026-05-26

### Fixed
- **Recovered event console visibility** (PR #174, issue #173):
  - Adds a console-specific event feed that preserves `ACTIVE` as unresolved `OPEN`/`ACK` while keeping `RECOVERED` events visible in the Monitoring Console.
  - Protects ACKed/commented recovered events during streaming cleanup by rechecking prune eligibility at close time.
  - Adds backend and frontend regression coverage for recovered visibility, query routing, and prune pagination safety.

- **Metric Analytics heterogeneous CI comparison follow-up** (extends PR #165):
  - Fixes `MetricHistoryChart` single-CI history loading by routing through the shared `fetchNodeMetricHistory()` API helper instead of an undefined `api` reference.
  - Allows primary and secondary multi-CI comparisons to choose metrics per selected CI, so different hardware models/brands can be compared before metric homologation.
  - Synchronizes multi-chart brush/zoom by timestamp range instead of shared point indices to avoid misleading windows across metrics with different sampling cadence.
  - Adds focused coverage for single-node metric history URL construction, heterogeneous multi-CI defaults, and timestamp-based chart brush ranges.

## [1.12.4] — 2026-05-25

### Fixed
- **Metric deletion UI and event cleanup semantics** (PR #161, issue #160):
  - Clarifies global metric definition deletion versus per-CI metric exclusion in the Admin Metrics UI.
  - Marks active collection-failure events as `RECOVERED` in the same Neo4j transaction that deletes the `MetricDef`.
  - Keeps historical Timescale metric samples retained by default and reports that policy in the delete response.
  - Adds regression coverage for frontend delete/exclusion behavior, idempotent backend deletion, and rollback on delete failure.

## [1.12.3] — 2026-05-25

### Fixed
- **SNMP no-response event severity normalization** (PR #159, issue #152):
  - Treats SNMP no-response, timeout, and no-data collection failures as `WARNING` events regardless of configured metric criticality.
  - Adds event lifecycle discriminators for collection failures, threshold breaches, and availability events to avoid conflating recovery paths.
  - Refreshes/reuses matching collection-failure events and recovers them when later valid samples arrive, while preserving threshold and availability lifecycles.
  - Preserves structured SNMP polling status through the leased executor/writer path and adds regression coverage for legacy worker, service helper, and leased writer behavior.
  - Defers broader legacy event discriminator normalization to issue #155 and stale event review reminders to issue #154.

## [1.12.2] — 2026-05-25

### Fixed
- **Bulk metric operation freeze mitigation** (PRs #156-#158, issue #153):
  - Offloads heavy metric create/delete backend work from the FastAPI event loop.
  - Adds a process-local same-metric mutation guard with controlled duplicate-operation responses.
  - Adds backend timing instrumentation for metric mutation/reconciliation hot paths.
  - Shows MetricsManager pending save/delete state, prevents duplicate local submissions, refreshes metrics/nodes after mutations, and clears stale deleted-metric UI state.
  - Adds focused backend and frontend regression coverage for the mitigation.

## [1.12.1] — 2026-05-25

### Fixed
- **Legacy SNMP latest readings refresh** (PR #151, issue #150):
  - Refreshes Neo4j `HAS_METRIC.last_value` and `HAS_METRIC.last_updated` after successful Timescale bulk persistence.
  - Keeps the UI/topology latest readings aligned with fresh `metric_values` rows while the scalable polling path remains disabled.
  - Preserves ICMP debounce/recovery behavior and avoids publishing latest values when Timescale persistence fails.

## [1.12.0] — 2026-05-25

### Added
- **Scalable metric polling architecture** (PRs #140-#149, issue #139):
  - Adds default-off polling pipeline flags and side-effect-free contracts for staged rollout.
  - Adds PostgreSQL-backed polling cycles, task/result queues, leases, retries, dead-letter handling, and explicit migration runner.
  - Adds deterministic scheduler task expansion with idempotency keys and protocol payload contracts for SNMP, ICMP, CLI, REST, and `MQTT_STUB`.
  - Adds leased SNMP/ICMP worker path that claims queue tasks and emits result envelopes instead of writing directly to Timescale/Neo4j.
  - Adds result writer pool with `metric_sample_receipts`, atomic sample/receipt persistence, Neo4j event batching, and replay-aware idempotency.
  - Adds queue-admission backpressure policies, metadata cache TTL/version checks, recursive secret scrubbing, simulator/benchmark commands, rollout runbooks, and runtime operator commands.
- **SNMP engine architecture guide**:
  - Adds `docs/snmp-scalable-engine.md` with a Mermaid diagram, happy path, flags, rollback model, and current caveats for the new leased SNMP engine.

### Changed
- Documents the scalable polling rollout path in `README.md`, `docs/polling-pipeline-runbook.md`, and `docs/polling-pipeline-tuning.md`.

### Notes
- Backpressure and metadata cache are currently queue-admission controls, not a deep adaptive control loop inside every worker.
- The scalable path is default-off and should be enabled progressively in staging before production rollout.

## [1.11.10] — 2026-05-24

### Fixed
- **Monitoring console ownership feedback** (PR #135, issue #31):
  - Surfaces failed “Tomar caso” ownership attempts inline instead of failing silently.
  - Disables the ownership action while the mutation is in flight and resets transient state across modal transitions.
- **Related alarms query cache hygiene** (PR #136, issue #32):
  - Prevents `RelatedAlarmsPanel` from mounting its related-events query without a valid `ciId`.
  - Removes the `['events', 'related', 'unknown']` fallback query key that polluted TanStack Query cache.
- **Refresh endpoint rate limiting** (PR #137, issue #109):
  - Applies existing rate-limit checks to `POST /api/auth/refresh`.
  - Tracks invalid refresh attempts and clears the counter after successful refresh.
  - Adds focused refresh rate-limit regression tests.

## [1.11.9] — 2026-05-24

### Fixed
- **AI agent permission validation hardening** (PR #121, issue #108):
  - Validates AI-agent JWT `permissions` claims against the `AIPermission` enum before granting access.
  - Rejects human/admin permissions, unknown permission strings, and malformed permission claims with fail-closed `403` responses.
  - Preserves valid AI-agent tokens and treats missing `permissions` as an empty permission list.
  - Adds regression tests for valid/invalid permissions plus token type, persona, and subject identity constraints.

## [1.11.8] — 2026-05-23

### Changed
- **System Status and SNMP Collector Optimizations**:
  - Implemented fast-fail Neo4j connectivity check (`verify_connection`) on the status endpoint to prevent API thread starvation on database startup/downtime.
  - Decoupled the SNMP collector worker from the main backend container by introducing `DISABLE_BACKEND_COLLECTOR=true`, preventing duplicate background workers.
  - Persisted independent collector state in Neo4j `:CollectorStatus` node under `snmp_worker.py` and modified `snmp_service.py` to retrieve it with memory fallback.
  - Eager-loaded CIs in the React UI layout (`App.tsx`) using the `useNodesQuery` hook, ensuring instantaneous populating of node count badges and metrics caching on login.

## [1.9.1] — 2026-05-11

### Fixed
- **SSE stream-progress endpoint fixes** (issue #85):
  - Added missing `/api` prefix to SSE fetch URL (was causing 404)
  - Added Authorization Bearer token to SSE fetch headers (was causing 401)
  - Added completion feedback alert when prune operation finishes
  - Added `PruneLock` distributed lock model (PostgreSQL) to prevent concurrent prune operations
  - Fixed race condition in lock acquisition using atomic `INSERT ... ON CONFLICT DO NOTHING`
  - Fixed unbounded retry recursion in lock acquisition (bounded loop with max_attempts=3)

## [1.9.0] — 2026-05-11

### Added
- **Batch Event Closure with SSE Progress Streaming**: Bulk close all RECOVERED events via `POST /events/prune` with real-time progress via `GET /events/bulk/stream-progress`
  - `event_batch_pruner()` async generator with cursor-based pagination (stable to inserts between batches)
  - Configurable batch size, delay, and timeout via `EVENT_BATCH_SIZE`, `EVENT_BATCH_DELAY_MS`, `EVENT_BATCH_TIMEOUT_S`
  - Request-scoped idempotency cache (no cross-user contamination)
  - `Last-Event-ID` header support for SSE reconnection
  - Anti-doble-click guard: button disabled + loading state during operation
  - Frontend progress indicator in MonitoringConsole

## [1.11.4] — 2026-05-20

### Fixed
- **ICMP polling false positives**: Fixed timeout, retry, and debounce logic in `snmp_worker.py`
  - Added `ICMPSettings` class with configurable `timeout_ms` (default 3s), `retries` (default 2), `debounce_count` (default 3)
  - Fixed platform-conditional ping: Linux uses `ping -W` (seconds), Windows uses `ping -w` (ms)
  - Added retry loop: any success returns UP, all fail returns DOWN
  - Added debounce counter: DOWN only after 3 consecutive failures
  - Fixed bare `except Exception: pass` causing silent failures — now logs `OSError`
  - Fixed protocol check using substring matching — now uses exact `protocol.upper() == 'ICMP'`
  - Removed duplicate status update path (debounce only sets status)
  - Added Pydantic Field validation to prevent invalid configs (0 timeout, -1 retries, 0 debounce)
  - Added 12 unit tests covering ICMPSettings, fetch_icmp_ping retry, and debounce counter
  - Added `ICMP_TIMEOUT_MS`, `ICMP_RETRIES`, `ICMP_DEBOUNCE_COUNT` env vars to docker-compose.yml

## [1.11.5] — 2026-05-21

### Fixed
- **Auth token security refactor** (PR #112):
  - Tokens stored in HTTP-only cookies (XSS protection) instead of localStorage
  - Refresh token rotation with 7-day TTL and one-time use
  - JWT_SECRET_KEY mandatory — fails startup if env var missing
  - Login rate limiting: 3 failed attempts → 15 min lockout (429 with Retry-After)
  - SSE 401 resilience: bulk operations survive token expiry with refresh retry queue
  - Cypher injection in seed_admin fixed via parameterized queries
  - RBAC enum vs string comparison bug fixed in check_permission
  - Admin credentials loaded from env vars or generated randomly on first start
  - Added 34 unit tests for auth service, rate limiting, and router

## [1.11.0] — 2026-05-19

### Added
- **CLI Polling Monitoring**: Execute CLI commands on multi-vendor network equipment via SSH/Telnet, extract values via regex, and feed numeric results into the ITOM monitoring pipeline
  - `MetricDef.protocol` extended with `CLI` value alongside existing SNMP and ICMP
  - `cli_worker.py` engine with SSH (preferred) and Telnet (fallback), privilege escalation, regex extraction, and NaN rate limiter (3 consecutive misses → alert)
  - `POST /api/cli/test` endpoint for interactive CLI query testing with raw output and extraction preview
  - CLI panel in MetricsManager UI for Test Query workflow: iterate on regex until satisfied, then Save as Metric
  - 34 unit tests covering regex extraction, credential resolution, escalation, and NaN rate limiting
  - `docs/cli-regex-manual.md` with regex format, numeric mapping table, 8 worked examples, and gotchas
  - `CLICredentialsSettings` in `backend/config.py` for `CLI_DEFAULT_USER`, `CLI_DEFAULT_PASS`, `CLI_ENABLE_PASS` env vars

### Fixed
- **CLI protocol branch bug**: `cli_protocol == 'SSH'` changed to `!= 'Telnet'` so Telnet-only mode works correctly

### Fixed
- **Nexgen-frontend proxy hostname conflict**: Vite proxy fallback changed from `localhost:8000` to `nexgen_backend:8000` to fix 404 on `GET /api/dictionaries/template-csv` caused by port conflict with netai-backend
- **Neo4j ResultConsumedError in topology_repo**: `get_cis_relationship_summary()` now consumes result set inside session context, fixing 500 error on `POST /api/cis/relationships`
- **Dictionary CSV template route ordering**: `GET /api/dictionaries/template-csv` now registers before `GET /api/dictionaries/{dictionary_id}` so FastAPI does not treat `template-csv` as a dictionary ID
- **CSV template download blob handling**: `api.ts` now respects `responseType: 'blob'` before content-type inspection so `URL.createObjectURL()` receives a real `Blob`
- **RelationshipTooltip hook ordering**: removed the early return that executed before `useEffect`, fixing the React hooks order crash in mass link views
- **Dictionary template visual cleanup**: template download now returns `.xlsx` with brand/model references on a separate sheet, and bulk upload accepts `.xlsx` as well as `.csv`
- **Dictionary upload copy consistency**: frontend labels now say `XLSX/CSV` or generic `File` so the UI matches the accepted upload formats

## [1.8.0] — 2026-05-10

### Added
- **Bulk Metric Dictionary Upload**: CSV-based bulk creation of MetricDictionary nodes with pre-populated template, 10% SNMP validation before commit, and automatic HAS_METRIC link creation on confirm.
  - `GET /api/dictionaries/template-csv` — download CSV template pre-populated with existing brand+model pairs from CI nodes
  - `POST /api/dictionaries/bulk` — parse and validate CSV (no commit), returns preview with per-row errors
  - `POST /api/dictionaries/bulk/validate-sample` — run SNMP polling on 10% random CIs per brand+model, return aggregated results
  - `POST /api/dictionaries/bulk/confirm` — atomic Neo4j transaction creating all MetricDictionary + HAS_METRIC links
  - `bulk_validate_rows()` batch-validates metric_ids in single Neo4j query (N+1 eliminated)
  - `bulk_validate_snmp_sample()` caches metric_defs per brand+model group (N+1 eliminated)
  - Metric validation inside write_tx guarantees atomicity (no stale pre-check race conditions)
  - Frontend: `DictionaryBulkUpload.tsx` component with Upload CSV + Apply tabs
  - Apply tab defaults all matching CIs selected (with deselect option)
  - `api.ts` fixed: FormData/Blob passed directly without JSON.stringify

### Fixed
- **StreamingResponse import**: `StreamingResponse` now correctly imported from `fastapi.responses` instead of `fastapi` (was blocking test collection)
  - `MetricDictionary` Neo4j nodes with brand+model required keys
  - `AppliedDictionary` overlay per CI for per-device customization
  - `GET/POST/PUT/DELETE /api/dictionaries` — Dictionary CRUD endpoints
  - `GET /api/dictionaries/{id}/target-cis` — list CIs matching dictionary's brand+model
  - `POST /api/dictionaries/{id}/apply` — apply dictionary to selected CIs (idempotent MERGE)
  - `POST /api/dictionaries/{id}/preview` — parallel SNMP preview (batch 20), OK/WARNING/CRITICAL/NO_DATA status
  - `GET/PUT/DELETE /api/cis/{ci_id}/applied-dictionary` — per-CI dictionary management
  - `reconcile_node_metrics()` updated: effective = (applicable ∪ dict_metrics) - excluded ∪ extra
  - Frontend: `DictionaryManager`, `DictionaryMassApply`, `CIDictionaryCustomization` components

## [1.6.0] — 2026-05-09

### Added
- **Event Correlation (Root Cause)**: When a parent CI fails, dependent CIs are marked as `PROPAGATED` instead of creating separate events. Reduces alarm noise by showing only the root cause event.
  - New fields on Event: `propagated_from`, `correlation_type` ('ROOT'|'PROPAGATED'), `root_cause_ci_id`
  - `find_open_parent_event()` traverses DEPENDS_ON/HOSTED_ON/CONNECTS_TO relationships up to 3 levels
  - Recovery propagation: when ROOT event recovers, all PROPAGATED events with same `root_cause_ci_id` also recover
  - API: events list includes `propagated=true` flag for PROPAGATED events
  - Dedup: RECOVERED events are re-opened on re-breach instead of creating duplicates

## [1.5.0] — 2026-05-09

### Added
- **CI Relationship Validator**: Add pre-creation validation to mass link editor and single-link creation. `POST /cis/relationships` batch endpoint returns CI relationship summaries. `RelationshipTooltip` + `RelationshipBadge` integrated into `MassLinkEditor` FilterPanel showing existing connections on hover.
- **Validation Guard**: `execute_bulk_links` warns when CIs already have the target relationship type before MERGE.
- **Simulate Enrichment**: `/links/mass/simulate` response includes `has_existing_relationships` with source/target CI lists.

### Fixed
- **Layer Filter**: Fixed `n.category` vs `n.type` mismatch — layer filter now checks both fields.
- **Debounce Race**: Fixed timeout race condition — IDs now captured via closure instead of ref.

## [1.4.0] — 2026-05-09

### Added
- **RTU/MQTT Telemetry Infrastructure (Phase 1)**: Foundation for monitoring BLIIoT S475E RTU devices via MQTT.
  - `RTUService` — full CRUD for RTU and Sensor entities in Neo4j
  - RTU/Sensor Pydantic models (`RTU`, `Sensor`, `TelemetryMessage`)
  - Neo4j repository layer with `find_sensor_by_key`, upsert, delete + Modbus register validation
  - REST API router with 9 endpoints: RTU CRUD, Sensor CRUD, mass operations
  - MQTT subscriber with QoS 1 handling, JSON payload parsing
  - Topic convention: `rtu/{location_id}/{rtu_id}/telemetry`
  - `MQTTSettings` singleton loaded from environment variables
  - Neo4j migration: RTU/Sensor node + relationship constraints (IF NOT EXISTS — idempotent)

### Fixed
- **RTU delete_sensor always returned 404** (issue #64): Removed incorrect existence check that used `find_sensor_by_key` with hardcoded dummy values (`register_addr=0`, `sensor_type=''`). Now delegates to `repo.delete_sensor` directly.

### Testing
- 7 new test files covering models, repo, service, router, integration, MQTT subscriber

## [1.3.0] — 2026-05-02

### Fixed
- **CMDB Correlations**: Fixed link query using OR logic so CIs properly display their correlations in the graph view.
- **Clustering Aura**: Aura now only visible for CRITICAL/WARNING clusters — no more visual noise from healthy clusters.
- **Clustering Tooltip**: Hover tooltip with 1.5s delay shows all CIs in cluster with individual status badges.
- **ClusterTooltip DOM ID**: Fixed collision when clusters have IDs differing only in special characters.
- **Cypher Injection Prevention**: Added allowlist validation for node labels in `_get_nodes_by_filter`.

### Added
- **Smart Culling for GeoView Map**: When >200 active alarms, the map now intelligently shows only the top 50 most critical CIs instead of overwhelming the operator with 1000+ markers. Includes a "Ver todos / Ver más críticos" toggle in the map toolbar.
- **Aura Radius Cap**: Maximum aura radius capped at 10km regardless of event count, preventing visual pollution from 50km+ circles.
- **Severity-Weighted Ranking**: CIs are ranked by `Σ(severity_weight * event_count)` where critical=3, warning=2, info=1.

### Fixed
- **GeoView CI Visibility**: Resolved an issue where the map appeared empty when >1000 alarms were active due to backend event truncation (LIMIT 100) cascading through the enrichment layer.

## [1.3.0] — 2026-05-02

### Added
- **Backup System**: PostgreSQL backup with APScheduler daily scheduling, admin-configurable schedule (default 06:00 dawn), manual backup trigger (ADMIN only), Neo4j BACKUP_SUCCESS/BACKUP_FAILURE events for admin dashboard, backup history and metrics API endpoints.
- **Backup Config Model**: PostgreSQL table for schedule_type, scheduled_time, enabled, retention_days, storage_path.
- **Backup History Model**: Audit log of all backups (scheduled/manual) with status, duration, file size.
- **Backup Metrics Endpoint**: `GET /api/backup/metrics` returns last_backup_at timestamp for admin dashboard.

### Fixed
- **Backup concurrent safety**: Added threading lock to prevent simultaneous backup runs corrupting files.
- **Backup cleanup error handling**: Cleanup failures now logged instead of silently swallowed.
- **APScheduler reschedule race condition**: Using `remove_job` instead of `remove_all_jobs`.

### Security
- Credentials for pg_dump now read from environment variables instead of hardcoded.

### Testing
- Judgment Day: 3 rounds, 2 judges, 0 CRITICALs remaining, APPROVED verdict.

## [1.1.0] — 2026-05-02

### Added
- **Hybrid Map Clustering**: Groups CIs by `location_name` (case-insensitive) with Haversine proximity fallback (500m threshold). Cluster markers display count badge, worst severity color, and CRITICAL clusters pulse with animate-ping.
- **Cluster Hover Tooltips**: Hovering over a cluster shows a popup listing all CIs in that location with name and severity.
- **Click-to-Expand Zones**: Clicking a cluster zooms the map to fit all members, renders individual CircleMarkers with connecting lines. Clicking outside collapses back to cluster view.
- **Feature Flag**: `geoview-clustering::enabled` localStorage key with toolbar toggle for enable/disable.
- **Judgment Day Protocol**: Full adversarial review cycle with 3 rounds, 2 judges, fix agent — resulting in APPROVED verdict.

## [1.0.0-prod-init] — 2026-04-22

### Added
- System startup event generation
- PostgreSQL health check endpoint
- Resource alerts to system logs
- Interactive node labels and hover focus effect
- Full port variabilization for all services
- Environment-based external ports mapping

### Fixed
- Missing IP and metrics in topology detail modal
- Admin auth split-brain scenario
- Postgres environment variable quoting issues
- Neo4j AUTH variable truncation at # character
- SnmpMetricsManager logic errors
- Event modal regressions
- Map link animations
- Frontend polling unification
- CI editor prefill issues

### Security
- Dynamic polling interval configuration
- Security hardening for environment config
- Allow-list enforcement for dynamic Cypher queries

### Infrastructure
- Docker Compose with full port variabilization
- Backend/frontend/service orchestration scripts
- Dependabot configuration
