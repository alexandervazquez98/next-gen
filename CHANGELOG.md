# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Smart Culling for GeoView Map**: When >200 active alarms, the map now intelligently shows only the top 50 most critical CIs instead of overwhelming the operator with 1000+ markers. Includes a "Ver todos / Ver más críticos" toggle in the map toolbar.
- **Aura Radius Cap**: Maximum aura radius capped at 10km regardless of event count, preventing visual pollution from 50km+ circles.
- **Severity-Weighted Ranking**: CIs are ranked by `Σ(severity_weight * event_count)` where critical=3, warning=2, info=1.

### Fixed
- **GeoView CI Visibility**: Resolved an issue where the map appeared empty when >1000 alarms were active due to backend event truncation (LIMIT 100) cascading through the enrichment layer.

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
