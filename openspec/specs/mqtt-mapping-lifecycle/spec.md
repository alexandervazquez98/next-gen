# MQTT Mapping Lifecycle Specification

## Purpose

Define the lifecycle rules for MQTT-to-CI/MetricDef mappings and the audit emission contract that records every transition, validation failure, and denied attempt — without leaking sensitive payload or credential material.

## Requirements

### Requirement: Mapping lifecycle state machine

The system MUST manage MQTT mappings through states `DRAFT`, `APPROVED`, and `REVOKED`. The system MUST accept the actions `create`, `update`, `approve`, `revoke`, and `update_thresholds`. `create` MUST produce a `DRAFT` mapping; `approve` MUST transition `DRAFT` to `APPROVED`; `revoke` MUST transition any state to `REVOKED`; `update` MUST keep state in `DRAFT`; `update_thresholds` MUST apply only to `APPROVED` mappings.

#### Scenario: Create yields a DRAFT mapping

- GIVEN an operator with `MQTT_MAPPING_MANAGE`
- WHEN the operator calls `create` with valid source/target identifiers
- THEN the mapping is persisted with `state=DRAFT` and `version=1`.

#### Scenario: Approve transitions DRAFT to APPROVED and bumps version

- GIVEN a mapping exists in `state=DRAFT`
- WHEN an operator calls `approve`
- THEN the mapping state becomes `APPROVED` and `version` is incremented by 1.

#### Scenario: Revoke from APPROVED

- GIVEN a mapping exists in `state=APPROVED`
- WHEN an operator calls `revoke`
- THEN the mapping state becomes `REVOKED`.

### Requirement: Audit emission on success, validation failure, and denial

The system MUST emit exactly one audit row for every lifecycle invocation, using `target_type=mqtt_mapping`. Success MUST use `outcome=success`; validation failure MUST use `outcome=validation_failure`; permission denial MUST use `outcome=denied`. Event types MUST be `MQTT_MAPPING_CREATE`, `MQTT_MAPPING_UPDATE`, `MQTT_MAPPING_APPROVE`, `MQTT_MAPPING_REVOKE`, and `MQTT_MAPPING_THRESHOLD_UPDATE`.

#### Scenario: Create produces a CREATE audit row

- GIVEN an operator with `MQTT_MAPPING_MANAGE`
- WHEN the operator successfully creates a mapping
- THEN an audit row exists with `event_type=MQTT_MAPPING_CREATE`, `outcome=success`, `previous_state=null`, `next_state=DRAFT`, `version=1`.

#### Scenario: Update enumerates changed fields

- GIVEN a `DRAFT` mapping
- WHEN the operator updates selected fields
- THEN the audit row carries `event_type=MQTT_MAPPING_UPDATE`, `outcome=success`, and `changed_fields` listing the modified field names.

#### Scenario: Approve by an authorized operator

- GIVEN a `DRAFT` mapping and an operator with `MQTT_MAPPING_MANAGE`
- WHEN the operator approves
- THEN the audit row carries `previous_state=DRAFT`, `next_state=APPROVED`, and the new `version`.

#### Scenario: Threshold update on APPROVED mapping

- GIVEN an `APPROVED` mapping and the operator has `MQTT_MAPPING_MANAGE`
- WHEN the operator updates thresholds
- THEN the audit row carries `event_type=MQTT_MAPPING_THRESHOLD_UPDATE`, `previous_state=APPROVED`, `next_state=APPROVED`, and `changed_fields` listing threshold keys.

#### Scenario: Denied approve attempt is audited

- GIVEN an operator WITHOUT `MQTT_MAPPING_MANAGE`
- WHEN the operator attempts `approve`
- THEN an audit row exists with `event_type=MQTT_MAPPING_APPROVE`, `outcome=denied`, and `required_permission=MQTT_MAPPING_MANAGE`.

### Requirement: Audit context contents

The audit context MUST include `mapping_id`, `source_device_id`, `source_metric_id`, `target_ci_id`, `target_metric_def_id`, `previous_state`, `next_state`, `version`, and (for update-style events) `changed_fields`. The context MUST NOT contain raw MQTT payload bodies, bearer tokens, session cookies, passwords, authorization headers, or any field flagged as a secret.

#### Scenario: Context carries identifiers and state but no payload

- GIVEN a successful lifecycle mutation
- WHEN the audit row is read back via the audit API
- THEN it includes the required identifiers and state fields
- AND it contains no payload body, token, cookie, password, or authorization value.

### Requirement: Audit emission failure isolation

The system MUST complete the user-facing lifecycle mutation even if audit emission fails. The system MUST log a warning when emission fails and MUST NOT raise the failure to the caller.

#### Scenario: Mutation succeeds when emission fails

- GIVEN the audit store is unavailable for write
- WHEN the operator successfully creates a mapping
- THEN the mapping is persisted and the API returns success
- AND a warning is logged for the dropped audit row.
