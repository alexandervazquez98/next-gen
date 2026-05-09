// RTU/Sensor Schema Migration — PR #1 Foundation
// ============================================================
// Neo4j migration script for RTU/MQTT Telemetry Infrastructure.
// Run this BEFORE deploying PR #1.
//
// Creates:
// - RTU node label with unique constraints
// - Sensor node label with unique composite index
// - Constraints for RTU.id and RTU.mqtt_topic uniqueness
// - Index for Sensor lookup by (rtu_id, register_addr)

// ── RTU Node ─────────────────────────────────────────────────────────────────

// RTU is a CI subtype (layer="RTU") representing a BLIIoT S475E device.
// Properties mirror the RTUResponse Pydantic model.

// Unique constraint on RTU.id
CREATE CONSTRAINT rtu_id_unique IF NOT EXISTS
FOR (r:RTU) REQUIRE r.id IS UNIQUE;

// Unique constraint on RTU.mqtt_topic
CREATE CONSTRAINT rtu_mqtt_topic_unique IF NOT EXISTS
FOR (r:RTU) REQUIRE r.mqtt_topic IS UNIQUE;

// ── Sensor Node ────────────────────────────────────────────────────────────────

// Sensor nodes belong to an RTU via HAS_SENSOR relationship.
// Composite key: (rtu_id, register_addr, sensor_type) for uniqueness.
// register_addr range: 0-319 (Modbus protocol limit)
// register_count range: 1-4 registers per sensor reading

// Composite unique index for sensor identity (upsert target)
CREATE INDEX sensor_rtu_addr_type IF NOT EXISTS
FOR (s:Sensor) REQUIRE (s.rtu_id, s.register_addr, s.sensor_type);

// Index for fast sensor lookup by RTU
CREATE INDEX sensor_rtu_id IF NOT EXISTS
FOR (s:Sensor) REQUIRE s.rtu_id;

// ── Relationships ─────────────────────────────────────────────────────────────

// RTU-[:LOCATED_AT]->Location (one-to-many)
//
// RTU.mqtt_topic format: rtu/{location_id}/{rtu_id}/telemetry
// This ensures topic uniqueness per RTU regardless of cluster topology.

// RTU-[:HAS_SENSOR]->Sensor (one-to-many, cascade on RTU delete)
//
// Cascade behavior: when RTU is DETACH DELETE'd, all HAS_SENSOR
// relationships and Sensor nodes are removed automatically.

// ── Notes ─────────────────────────────────────────────────────────────────────
// IF NOT EXISTS prevents re-run errors on repeated executions.
// All constraints/indexes are forward-compatible with Neo4j 5.x.
// Drop with: DROP CONSTRAINT rtu_id_unique, etc.