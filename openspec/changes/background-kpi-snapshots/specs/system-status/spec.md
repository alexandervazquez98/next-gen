# System Status Specification

## Purpose

Ensure operational KPI history is collected continuously by backend background work and made visible as a stable, bounded, continuously available 7-day timeline, while preserving the live dashboard's real-time status polling behavior.

## Requirements

### Requirement: Backend-owned periodic KPI snapshot persistence

The system MUST record compact operational KPI snapshots on a backend schedule every 15 minutes, independent of frontend/API call volume.
It MUST NOT depend on users opening the System Dashboard or calling `/api/system/status` for snapshot writes to occur.

#### Scenario: History continues without dashboard usage

- GIVEN no user opens the dashboard for multiple hours
- WHEN the backend remains running during that period
- WHEN a user later opens the dashboard and fetches `/api/system/status/history`
- THEN snapshot history MUST include recent rows from that period (subject to backend uptime and retention).

### Requirement: Snapshot cadence and retention contract

The system MUST retain 7 days of compact snapshots and keep writes bounded to a low-frequency pattern equivalent to the 15-minute cadence.
Rows older than the 7-day retention window MUST be pruned and MUST NOT appear in new `/api/system/status/history` responses.

#### Scenario: Continuous cadence with bounded frequency

- GIVEN the snapshot scheduler runs for more than 2 hours in normal operation
- WHEN history is queried for that window
- THEN the timestamp gap between consecutive persisted snapshots MUST not indicate writes at intervals much shorter than 15 minutes under normal operation.

#### Scenario: Seven-day retention

- GIVEN snapshots exist older than 7 days
- WHEN `/api/system/status/history` is requested
- THEN those rows MUST be excluded from returned results and retention metadata MUST report 7-day retention.

### Requirement: Live telemetry endpoint separation

The system MUST keep `/api/system/status` as the source for live cards, with polling behavior unchanged for UI responsiveness.
Persisting operational history MUST be delivered through background capture, not via side effects required on each `/api/system/status` request.

#### Scenario: Live cards stay current with polling

- GIVEN the dashboard polls `/api/system/status` on a short interval
- WHEN backend snapshot persistence is delayed or temporarily paused
- THEN the live cards MUST continue updating from live endpoint responses.

### Requirement: Staleness detection and operator visibility

The system MUST expose a clear staleness signal when persisted snapshots stop arriving.
The UI MUST show an explicit operator-visible warning when the latest snapshot age exceeds a freshness window of approximately two snapshot intervals (about 30 minutes, unless explicitly configured).
The UI MUST show normal history without warning when snapshots are fresh.

#### Scenario: Operator sees stale history warning

- GIVEN snapshot generation has been interrupted for longer than the stale threshold
- AND history rows returned are older than the threshold
- WHEN the dashboard renders history section
- THEN an explicit staleness alert MUST be displayed instead of silently showing an empty or fully normal history state.

#### Scenario: Recent snapshots clear stale warning

- GIVEN background snapshots resume within threshold
- WHEN a user opens the dashboard
- THEN the stale alert MUST be absent and history metrics SHOULD display as current.

### Requirement: No scope regression in CI/SNMP/ICMP collection

The change MUST not alter CI, SNMP, ICMP collection cadence, metric semantics, or existing metric contracts used by the live status endpoint.
The compact snapshot workflow MUST not introduce high-frequency writes or additional polling of those collectors.

#### Scenario: Collection semantics remain stable

- GIVEN any valid invocation of `/api/system/status` and normal collector operations
- WHEN the background snapshot feature is enabled
- THEN live status and collector fields already presented in status payloads MUST remain observable and accurate.
- AND no additional CI/SNMP/ICMP collection path for these fields SHOULD be introduced by the snapshot feature.

## Non-Goals

- No redesign of metric collection pipelines.
- No high-frequency raw-metric persistence beyond compact historical KPI rows.
- No CI/SNMP/ICMP polling cadence changes.
