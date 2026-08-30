# MQTT Mapping Management Specification

## Purpose

Operator workflow for draft mappings, DRAFT-only edits, approve/revoke via confirm modal, and APPROVED-only threshold edits. Every mutation MUST be gated by `MQTT_MAPPING_MANAGE` (or `ADMIN`). Extends (does NOT modify) `mqtt-monitoring-integration` at `openspec/changes/integrate-mqtt-readings-monitoring/specs/mqtt-monitoring-integration/spec.md`.

## Requirements

### Requirement: Permission Model

Reads require `MQTT_READ` (or `ADMIN`); writes require `MQTT_MAPPING_MANAGE` (or `ADMIN`). Permissions SHALL be read via `hasPermission(...)` matching the backend `UserPermission` enum.

#### Scenario: No MQTT_READ blocks the tab

- GIVEN a session lacking `MQTT_READ` and `ADMIN`
- WHEN the operator opens the Mappings tab
- THEN the tab body MUST NOT render and no `/api/mqtt/mappings*` call MUST fire.

#### Scenario: Read-only hides all write controls

- GIVEN a session with `MQTT_READ` only
- WHEN the Mappings tab renders
- THEN "New Mapping", "Edit", "Approve", "Revoke", and "Thresholds" controls MUST NOT render.

#### Scenario: 403 surfaces a named permission toast

- GIVEN any mutation fires without `MQTT_MAPPING_MANAGE`
- WHEN the API returns `403`
- THEN a toast naming `MQTT_MAPPING_MANAGE` MUST render
- AND the prior list state MUST remain unchanged.

### Requirement: Browse and Filter Mappings

The Mappings tab MUST request `GET /api/mqtt/mappings` and render one row per mapping.

#### Scenario: Status filter narrows the list

- GIVEN the operator selects `status=APPROVED`
- WHEN the tab re-fetches
- THEN the request MUST include `?status=APPROVED`
- AND only matching rows MUST render.

### Requirement: Create Mapping — DRAFT Only

`POST /api/mqtt/mappings` MUST create `DRAFT` rows; no "approve on create" toggle is allowed. Submit with missing required fields MUST NOT fire and MUST render inline errors.

#### Scenario: Valid submit creates DRAFT

- GIVEN the form has `source_device_id`, `source_metric_id`, `source_metric_name`, `target_ci_id`, `target_metric_def_id`
- WHEN the operator submits
- THEN `POST /api/mqtt/mappings` MUST fire
- AND the new row MUST appear with `status="DRAFT"`.

### Requirement: Edit Mapping — DRAFT Only

PUT `/api/mqtt/mappings/{id}` SHALL be enabled only on `DRAFT` rows; the form MUST re-fetch the latest payload before each edit to avoid partial overwrites.

#### Scenario: DRAFT row is editable

- GIVEN a mapping with `status="DRAFT"`
- WHEN the operator opens the edit form
- THEN the form MUST prefill from the latest GET
- AND submit MUST send a full-payload PUT.

#### Scenario: Non-DRAFT row disables edit

- GIVEN a mapping with `status="APPROVED"` or `"REVOKED"`
- WHEN the row renders
- THEN the edit control MUST be disabled with tooltip "Editable only in DRAFT state".

### Requirement: Approve and Revoke Require Confirm Modal

Approve and revoke MUST open a confirm modal naming `mapping_id`, `target_ci_id`, and `source_metric_name`. The mutation MUST NOT fire until Confirm is clicked; cancelling MUST issue no network call.

#### Scenario: Approve opens confirm naming the mapping

- GIVEN a `DRAFT` mapping and a session with `MQTT_MAPPING_MANAGE`
- WHEN the operator clicks "Approve"
- THEN a modal MUST render naming `mapping_id`, `target_ci_id`, `source_metric_name`
- AND `POST /api/mqtt/mappings/{id}/approve` MUST NOT fire until Confirm is clicked.

#### Scenario: Cancel issues no call

- GIVEN the confirm modal is open
- WHEN the operator cancels or closes it
- THEN no `/approve` or `/revoke` network call MUST fire
- AND no toast SHALL appear.

#### Scenario: Revoke disabled outside APPROVED

- GIVEN a mapping with `status="DRAFT"` or `"REVOKED"`
- WHEN the row renders
- THEN the "Revoke" control MUST be disabled with tooltip "Only APPROVED mappings can be revoked".

#### Scenario: Confirmed approve reflects new status

- GIVEN the operator confirms the modal
- WHEN `POST /api/mqtt/mappings/{id}/approve` returns success
- THEN the row MUST display `status="APPROVED"` with `approved_at` populated.

### Requirement: Threshold Edits — APPROVED Only

GET/PUT `/api/mqtt/mappings/{id}/thresholds`. The form MUST be interactive only on APPROVED rows; a 409 MUST surface inline next to the affected field with no success toast.

#### Scenario: APPROVED enables the threshold form

- GIVEN a mapping with `status="APPROVED"`
- WHEN the operator opens Thresholds
- THEN inputs MUST be enabled and prefill from `GET /api/mqtt/mappings/{id}/thresholds`.

#### Scenario: Non-APPROVED keeps thresholds read-only

- GIVEN a mapping with `status="DRAFT"` or `"REVOKED"`
- WHEN the operator opens Thresholds
- THEN inputs MUST be disabled with tooltip "Thresholds editable only on APPROVED mappings"
- AND submit MUST NOT be possible.

### Requirement: Cache Invalidation on Mutations

Successful mutations MUST invalidate MQTT React Query keys; approve/revoke MUST additionally invalidate `systemStatus`.

#### Scenario: Mutations invalidate all relevant keys

- GIVEN a successful create/update/approve/revoke/threshold mutation
- WHEN `onSuccess` fires
- THEN the UI MUST invalidate `mqttMappings`, `mqttMappingThresholds`, raw-read keys, and Bridge Status
- AND approve/revoke MUST additionally invalidate `systemStatus`.
