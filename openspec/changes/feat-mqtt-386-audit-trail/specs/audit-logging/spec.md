# Delta for Audit Logging

## MODIFIED Requirements

### Requirement: Critical change event capture and denied attempts

The system MUST capture first-slice critical changes for create/update/delete of CIs, users, roles, permissions, MQTT mapping lifecycle, and critical system configuration, including denied and failed attempts when context is attributable to a user.
(Previously: First-slice covered CI, user, role, permission, and critical-config mutations — MQTT mapping lifecycle is now in scope.)

#### Scenario: Critical change attempts are captured with outcomes

- GIVEN an actor attempts any first-slice critical action
- WHEN the action is allowed or denied
- THEN one audit record MUST be written with action target, event outcome (`SUCCESS`, `DENIED`, or `VALIDATION_FAILURE`), and concise non-sensitive reason on failure/denial.

#### Scenario: Non-critical actions remain out of slice

- GIVEN an action modifies a non-critical entity outside first-slice scope
- WHEN the action completes
- THEN the system MUST NOT require mandatory audit capture in this slice.

## ADDED Requirements

### Requirement: Mapping lifecycle context keys in allow-list

The audit service allow-list MUST include the keys `mapping_id`, `source_device_id`, `source_metric_id`, `target_ci_id`, `target_metric_def_id`, `previous_state`, `next_state`, `version`, and `changed_fields` for `target_type=mqtt_mapping` events. Non-listed keys passed for these events MUST be stripped before persistence.

#### Scenario: Mapping context keys survive sanitization

- GIVEN a mapping lifecycle event with allow-listed context keys
- WHEN the audit service sanitizes the context
- THEN every allow-listed key is preserved verbatim.

#### Scenario: Unknown mapping context keys are stripped

- GIVEN a mapping lifecycle event whose context includes a key not on the allow-list
- WHEN the audit service sanitizes the context
- THEN the unknown key is removed and is not persisted.

### Requirement: Mapping lifecycle event types and target type

The audit service MUST recognize `MQTT_MAPPING_CREATE`, `MQTT_MAPPING_UPDATE`, `MQTT_MAPPING_APPROVE`, `MQTT_MAPPING_REVOKE`, and `MQTT_MAPPING_THRESHOLD_UPDATE` as first-slice event types, and MUST persist every row for these events with `target_type=mqtt_mapping` and the mapping id as `target_id`.

#### Scenario: Mapping event row carries the canonical target type

- GIVEN any MQTT mapping lifecycle invocation (success, validation failure, or denied)
- WHEN an audit row is persisted
- THEN the row contains `target_type=mqtt_mapping` and `target_id` equal to the mapping id.

#### Scenario: Mapping events are queryable by target filter

- GIVEN multiple audit rows exist across event types
- WHEN the audit log API is filtered with `target_type=mqtt_mapping&target_id={id}`
- THEN only rows for that mapping are returned, ordered by `created_at`.

### Requirement: Mapping lifecycle redaction invariants

The audit service MUST strip from mapping context any raw MQTT payload body, bearer token, session cookie, authorization header, password, request body, refresh token, or other secret material before persistence. `record_critical_change` and `record_denied` paths MUST apply the same redaction for `target_type=mqtt_mapping`.

#### Scenario: Sensitive payload keys never persist in mapping context

- GIVEN a mapping lifecycle call whose context accidentally contains `body`, `token`, `cookie`, `password`, `raw_body`, `authorization`, `refresh_token`, or `session_token`
- WHEN the audit row is written
- THEN none of those keys appear in the persisted context.

#### Scenario: Rejection of secret material is silent

- GIVEN a mapping lifecycle call with sensitive keys present
- WHEN sanitization runs
- THEN sanitization drops the keys without raising to the caller.
