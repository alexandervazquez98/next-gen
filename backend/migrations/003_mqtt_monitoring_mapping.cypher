// Migration 003 — MQTT Monitoring Mapping + idempotent KPI bridge metadata.
// =================================================================
//
// Adds the mapping model required by PR #321 slice 1.
// This script is ADDITIVE: all constraints/indexes use IF NOT EXISTS,
// so it is safe to rerun.

// ----------------------------------------------------------------------------
// Constraint: mapping IDs must be globally unique.
// ----------------------------------------------------------------------------
CREATE CONSTRAINT mqtt_metric_mapping_id_unique IF NOT EXISTS
FOR (m:MqttMetricMapping)
REQUIRE m.id IS UNIQUE;

// ----------------------------------------------------------------------------
// Composite uniqueness for explicit state transitions:
// multiple mappings for same source pair are allowed in DRAFT/REVOKED,
// but services must enforce APPROVED uniqueness at write time.
// ----------------------------------------------------------------------------
CREATE INDEX mqtt_metric_mapping_source_status IF NOT EXISTS
FOR (m:MqttMetricMapping)
ON (m.source_device_id, m.source_metric_id, m.status);

CREATE INDEX mqtt_metric_mapping_target_status IF NOT EXISTS
FOR (m:MqttMetricMapping)
ON (m.target_ci_id, m.target_metric_def_id, m.status);

// ----------------------------------------------------------------------------
// Core data fields used by PR4 bridge/runtime.
// ----------------------------------------------------------------------------
CREATE INDEX mqtt_metric_mapping_status IF NOT EXISTS
FOR (m:MqttMetricMapping) ON (m.status);

CREATE INDEX mqtt_metric_mapping_created_at IF NOT EXISTS
FOR (m:MqttMetricMapping) ON (m.created_at);

CREATE INDEX mqtt_metric_mapping_updated_at IF NOT EXISTS
FOR (m:MqttMetricMapping) ON (m.updated_at);

// ----------------------------------------------------------------------------
// Per-source approval lock guard. Guarantees concurrent approvals for one source pair
// serialize via a lock node with a unique key.
CREATE CONSTRAINT mqtt_mapping_source_lock_unique IF NOT EXISTS
FOR (l:MqttMappingSourceLock)
REQUIRE l.source_key IS UNIQUE;

CREATE INDEX mqtt_mapping_source_lock_source_key IF NOT EXISTS
FOR (l:MqttMappingSourceLock)
ON (l.source_key);

// ----------------------------------------------------------------------------
// Relationships are created by repository code paths in the same transaction.
// Existing MQTT data should continue to operate if this migration is run.
// ----------------------------------------------------------------------------
// No-op here: relationship existence is validated by runtime queries.

// Rollback hints (manual, in emergency only):
//   DROP CONSTRAINT mqtt_metric_mapping_id_unique;
//   DROP INDEX mqtt_metric_mapping_source_status;
//   DROP INDEX mqtt_metric_mapping_target_status;
//   DROP INDEX mqtt_metric_mapping_status;
//   DROP INDEX mqtt_metric_mapping_created_at;
//   DROP INDEX mqtt_metric_mapping_updated_at;
//   DROP CONSTRAINT mqtt_mapping_source_lock_unique;
//   DROP INDEX mqtt_mapping_source_lock_source_key;

