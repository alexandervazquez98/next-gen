// Migration 002 — Generic Device + Metric schema for pluggable MQTT subscriber.
// ========================================================================
//
// This is an ADDITIVE migration. It does NOT modify existing RTU/Sensor nodes
// created by migration 001. The Device and Metric labels live alongside RTU
// and Sensor so legacy callers (RTUService) and the new MQTT subscriber
// (DeviceMetricRepo) can coexist during the PR3b cutover.
//
// Run: this file is idempotent. Every CREATE uses IF NOT EXISTS, so
// re-running it against an already-migrated database is a no-op.

-- ── Device Node ──────────────────────────────────────────────────────────────
-- Device represents any generic MQTT-publishing device. BLIIoT RTUs, future
-- JSON sensors, and ad-hoc devices all share this label.
--
-- source_topic : the MQTT topic the device publishes on (for diagnostics)
-- parser_name  : the parser registry key (e.g. "bliiot_s475e", "generic_json")
-- first_seen   : timestamp of the FIRST message observed (set on create)
-- last_seen    : timestamp of the MOST RECENT message (updated on each upsert)
-- extra        : JSON string for parser-specific metadata (to avoid property
--                name cardinality bloat in Neo4j)

CREATE CONSTRAINT device_id_unique IF NOT EXISTS
FOR (d:Device) REQUIRE d.id IS UNIQUE;

-- ── Metric Node ─────────────────────────────────────────────────────────────
-- Metric represents a single measurement produced by a Device.
-- One Metric node per (device_id, name) pair, identified by a stable id.

CREATE CONSTRAINT metric_id_unique IF NOT EXISTS
FOR (m:Metric) REQUIRE m.id IS UNIQUE;

-- ── Indexes ─────────────────────────────────────────────────────────────────
-- Indexes for the most common query patterns from DeviceMetricRepo.

-- Lookup devices by source topic (debugging / topic migration)
CREATE INDEX device_source_topic IF NOT EXISTS
FOR (d:Device) ON (d.source_topic);

-- Lookup devices by parser (e.g. "show all bliiot devices")
CREATE INDEX device_parser_name IF NOT EXISTS
FOR (d:Device) ON (d.parser_name);

-- Composite index for the upsert path: "find metric for this device by name"
CREATE INDEX metric_device_name IF NOT EXISTS
FOR (m:Metric) ON (m.device_id, m.name);

-- ── Relationships ────────────────────────────────────────────────────────────
-- The HAS_METRIC relationship between Device and Metric is created implicitly
-- at write-time via MERGE inside DeviceMetricRepo.upsert_metric. Per Cypher
-- best practice, we don't pre-create relationships with no endpoint nodes.

-- ── Notes ────────────────────────────────────────────────────────────────────
-- * IF NOT EXISTS makes this script safe to re-run on an already-migrated DB.
-- * All constraints/indexes are forward-compatible with Neo4j 5.x.
-- * To roll back (only if needed):
--     DROP CONSTRAINT device_id_unique;
--     DROP CONSTRAINT metric_id_unique;
--     DROP INDEX device_source_topic;
--     DROP INDEX device_parser_name;
--     DROP INDEX metric_device_name;
