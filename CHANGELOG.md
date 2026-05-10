# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Mass Metric Dictionary Apply**: Bundle OIDs per brand+model into reusable "MetricDictionary" entities with live SNMP preview before bulk-applying to CIs, plus per-CI exclusion/inclusion customization.
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
