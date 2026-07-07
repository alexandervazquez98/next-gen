# MQTT Monitoring Integration Specification

## Purpose

Enable MQTT telemetry to be ingested and observable immediately via backend/API while preventing it from silently becoming official monitoring KPI data unless operators explicitly map and approve each MQTT reading into existing CI/MetricDef monitoring semantics.

## Requirements

### Requirement: Raw MQTT readings are API-visible but KPI-ineligible by default

The system MUST expose raw MQTT `Device`/`Metric` readings through backend/API surfaces in the initial MVP slice, and those raw readings MUST NOT be included in official monitoring KPI datasets, event streams, or dashboard payload derivations unless an explicit approved mapping exists.

#### Scenario: Raw MQTT readings are retrievable and clearly non-KPI

- GIVEN an MQTT message is ingested and stored as a raw device/metric reading
- WHEN an operator calls the MQTT raw-readings API endpoint
- THEN the API MUST return the reading with a non-KPI flag or classification
- AND the same payload must NOT appear in official KPI query responses, event outputs, or metric history as a KPI sample.

#### Scenario: New MQTT data does not alter existing KPI outputs without mapping

- GIVEN one or more unmapped MQTT readings exist during a query window
- WHEN `/api/monitoring` and KPI retrieval endpoints are called
- THEN official KPI values, thresholds, and events MUST remain unchanged compared to the same window without those unmapped readings.

### Requirement: Explicit mapping approval gate for KPI ingestion

The system MUST require an operator-created, explicit mapping rule to transform a raw MQTT reading into a monitoring KPI sample path, and that mapping rule MUST be in `APPROVED` state before any mapped persistence or event generation is allowed.

#### Scenario: Approved mapping enables bridge writes

- GIVEN an operator creates a mapping rule from a raw MQTT device/metric to a CI/MetricDef
- AND marks that rule as approved
- WHEN a matching reading is ingested
- THEN the reading MAY be written into monitoring KPI persistence and event generation paths.

#### Scenario: Unapproved mapping or absent mapping blocks KPI persistence

- GIVEN a raw MQTT reading arrives
- WHEN no approved mapping rule exists for that reading
- THEN the system MUST skip KPI persistence and event generation for that reading.
- AND the skip MUST be observable in API status/audit output.

### Requirement: Manual mapping rules are auditable, explicit, and permission-gated

The system MUST provide API-first operations to create, update, revoke, and view mapping rules without any automatic suggestion or auto-matching, and every effective mapping decision and status change MUST be logged with actor and timestamp metadata. Read operations MUST require an explicit MQTT read permission, and mapping/threshold mutations MUST require an explicit MQTT mapping-management permission or one centrally declared compatibility mapping to an existing permission.

#### Scenario: Operator-only explicit mapping lifecycle

- GIVEN an authorized operator submits mapping changes
- WHEN API receives create/update/revoke requests
- THEN only direct API operations by actors with mapping privileges are accepted.
- AND mappings must be marked `DRAFT`, `APPROVED`, or `REVOKED` explicitly.

#### Scenario: Mapping audit is recoverable and queryable

- GIVEN a mapping is approved, changed, or revoked
- WHEN operators request mapping audit data
- THEN the system MUST return immutable metadata including acting user, timestamps, source identifiers, and before/after mapping state.

### Requirement: Runtime subscriber wiring is explicit and verifiable

The MQTT subscriber process must be explicitly started as part of runtime operation, and the system MUST expose an API signal/status proving that subscriber execution is active and healthy. If the subscriber runs in a separate process/container from the API, health MUST be communicated through shared persisted heartbeat/status, not process-local memory.

#### Scenario: Runtime startup includes subscriber wiring

- GIVEN the production runtime is started
- WHEN services initialize
- THEN MQTT subscriber execution MUST start through an explicit runtime entrypoint/config path (not implicit background side-effects).
- AND status/readiness evidence for MQTT subscriber health MUST be available from API.

#### Scenario: Subscriber wiring is detectable when absent

- GIVEN the subscriber is not running or not connected
- WHEN operators request MQTT integration status
- THEN the API MUST report an explicit non-running state and provide a reason code suitable for runbook-driven remediation.

### Requirement: Manual threshold configuration applies to mapped MQTT metrics

The system MUST allow manual configuration of threshold values for mapped MQTT metrics and MUST apply those thresholds through the existing monitoring event/evaluation path used by other mapped metrics. Mapped MQTT KPI writes MUST be idempotent so MQTT redelivery or partial Timescale/event retry cannot duplicate metric samples or events.

#### Scenario: Configure thresholds for a mapped MQTT metric

- GIVEN a MQTT reading is mapped to CI/MetricDef with an approved rule
- WHEN an operator updates threshold values for that mapped metric via API
- THEN the new thresholds MUST be persisted and used during subsequent threshold evaluation.

#### Scenario: Threshold changes take effect in events without remapping

- GIVEN thresholds are changed for an already mapped MQTT metric
- WHEN the next mapped sample arrives
- THEN event outcomes MUST be computed using the updated thresholds.

### Requirement: No silent auto-mapping and no KPI pollution

The system MUST reject any implementation path that auto-maps MQTT readings to monitoring entities without explicit operator action, and MUST fail closed if ambiguity or missing mapping state would otherwise cause implicit KPI classification.

#### Scenario: Ambiguous or unmapped payloads stay explicit

- GIVEN an MQTT payload matches no approved mapping and cannot be uniquely resolved
- WHEN processed by the bridge layer
- THEN the system MUST not create KPI samples or alter KPI metadata automatically.
- AND it MUST emit an explicit unmapped outcome status.

## Non-Goals

- No first-slice UI for mapping workflow or unmapped-reading dashboards.
- No backfill of historic unmapped MQTT payloads into Timescale KPI history.
- No automatic mapping inference, recommendation, or policy-based auto-approval.

## Assumptions (MVP)

The following assumptions remain explicit because owner review is deferred for this slice:

- Operators who manage mappings and thresholds are authenticated API clients with explicit MQTT mapping-management permission; raw/status reads require explicit MQTT read permission.
- Mapping scope in MVP is per-rule to a target CI/MetricDef (not global/tenant-only threshold behavior).
- API visibility for unmapped readings is intended for operator/internal consumption in MVP.
- Mapping failures should be observable and may be partially skipped while continuing to process other readings.
