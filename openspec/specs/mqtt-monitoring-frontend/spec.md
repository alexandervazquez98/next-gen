# MQTT Monitoring Frontend Specification

## Purpose

Operator UI for browsing raw MQTT telemetry and bridge runtime status. Every reading MUST stay clearly non-KPI. Extends (does NOT modify) `mqtt-monitoring-integration` at `openspec/changes/integrate-mqtt-readings-monitoring/specs/mqtt-monitoring-integration/spec.md`.

## Requirements

### Requirement: Route and Nav Entry Gated by MQTT_READ

`/monitoring/mqtt` and its sidebar entry SHALL be reachable only when the session holds `MQTT_READ` or `ADMIN`, evaluated via `hasPermission`.

#### Scenario: Operator with MQTT_READ enters route

- GIVEN a session whose effective permissions include `MQTT_READ`
- WHEN the operator navigates to `/monitoring/mqtt`
- THEN the page renders and the four tabs begin fetching.

#### Scenario: Operator without MQTT_READ is denied entry

- GIVEN a session lacking `MQTT_READ` and `ADMIN`
- WHEN the operator navigates to `/monitoring/mqtt`
- THEN the route guard redirects to the landing page
- AND no `/api/mqtt/*` fetch fires.

#### Scenario: Sidebar entry visibility

- GIVEN a session lacking `MQTT_READ` and `ADMIN`
- WHEN the sidebar renders
- THEN the "MQTT Monitoring" NavItem MUST NOT appear.

### Requirement: Raw Devices Browser

The Raw Readings tab SHALL request `GET /api/mqtt/devices` and render one row per device.

#### Scenario: Devices render from API

- GIVEN the operator opens the Raw Readings tab
- WHEN `GET /api/mqtt/devices` returns devices
- THEN each row MUST show `device_id`, `name`, `last_seen`, `mapped_metrics_count`, `unmapped_metrics_count`.

#### Scenario: Empty list shows empty state

- GIVEN `GET /api/mqtt/devices` returns `[]`
- WHEN the tab renders
- THEN a non-error "No devices" empty state MUST display.

### Requirement: Per-Device Metrics and Latest Readings

Expanding a device SHALL request `GET /api/mqtt/devices/{id}/metrics`. A "Latest Readings" panel SHALL request `GET /api/mqtt/readings?limit=100` on a fixed interval.

#### Scenario: Device expansion loads metrics

- GIVEN a device row is rendered
- WHEN the operator expands it
- THEN `GET /api/mqtt/devices/{device_id}/metrics` MUST fire
- AND `metric_id`, `name`, `unit`, `last_value`, `last_ts` MUST render per metric.

### Requirement: RAW_MQTT_NON_KPI Badge Always Visible

Every raw reading rendered by this page MUST show the API-supplied `classification` as a badge and a `kpi_eligible=false` indicator. The badge text MUST come from the payload, never be hidden by overlapping widgets.

#### Scenario: Reading row carries non-KPI badge

- GIVEN a reading with `classification="RAW_MQTT_NON_KPI"` and `kpi_eligible=false`
- WHEN the row renders
- THEN a `RAW_MQTT_NON_KPI` badge MUST be present
- AND a `kpi_eligible=false` indicator MUST be visible
- AND no widget MUST overlap or hide the badge.

#### Scenario: Missing payload fields default to non-KPI

- GIVEN a payload where `classification` or `kpi_eligible` is missing or null
- WHEN the row renders
- THEN the UI MUST default-render the non-KPI badge rather than omit it.

### Requirement: Bridge Status and Counters

A Bridge Status tab MUST request `GET /api/mqtt/status` on a fixed interval and render runtime flags plus counters.

#### Scenario: Healthy bridge renders counters

- GIVEN the endpoint returns `{ running: true, connected: true, configured: true, ... }`
- WHEN the Bridge Status tab renders
- THEN counters, `last_message_at`, and subscribed patterns MUST be visible
- AND a "Running" badge MUST render.

#### Scenario: Stale heartbeat displays Not Running

- GIVEN `last_message_at` exceeds the stale window
- WHEN the tab renders
- THEN the state MUST render as "Not Running" with `reason_code` and a runbook hint.

#### Scenario: Unconfigured runtime surfaces last_error

- GIVEN the runtime reports `{ configured: false, running: false }`
- WHEN the tab renders
- THEN "Not Configured" and `last_error` text MUST be visible when present.

### Requirement: No "Mark as KPI" Affordance

The MQTT Monitoring UI MUST NOT expose any control that promotes raw readings to KPI classification, regardless of tab or permission.

#### Scenario: DOM has no promotion control

- GIVEN any tab renders for any session
- WHEN the rendered DOM is inspected
- THEN no element with text matching `Mark as KPI|Promote|Assign to KPI` may exist.
