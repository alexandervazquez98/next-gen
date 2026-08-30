// ITSM Service Catalog and Ticket/Folio migration.
//
// This migration introduces identity constraints and query indexes for the new
// ITSM Service Catalog and Ticket/Folio domains while preserving backward
// compatibility with existing legacy ServiceCatalog nodes.
//
// Runtime policy:
// - Fail-fast at startup on duplicate or invalid ServiceCatalog identities.
// - Compatibility backfill runs before strict preflight validation.
// - Conflicts are rejected before constraints are allowed to continue.
// - Startup remains deterministic because identity checks run before constraints.
//
// Notes:
// - Idempotent statements use IF NOT EXISTS.
// - This migration is additive and does not delete or mutate existing Event nodes.
// - Event snapshot fields on Event nodes are intentionally left untouched.

// -----------------------------------------------------------------------------
// Managed value-stream dictionary bootstrap
// -----------------------------------------------------------------------------
// Value streams use the existing MetricDictionary node model, scoped by
// dictionary_key. These idempotent seeds make a clean-slate deployment usable
// without weakening active-value validation.
CREATE CONSTRAINT value_stream_dictionary_value IF NOT EXISTS
FOR (value:MetricDictionary) REQUIRE (value.dictionary_key, value.value) IS UNIQUE;

CREATE INDEX metric_dictionary_key IF NOT EXISTS
FOR (value:MetricDictionary) ON (value.dictionary_key);

MERGE (operate:MetricDictionary {dictionary_key: 'value_stream', value: 'operate'})
ON CREATE SET operate.label = 'Operate', operate.active = true;

MERGE (deliver:MetricDictionary {dictionary_key: 'value_stream', value: 'deliver'})
ON CREATE SET deliver.label = 'Deliver', deliver.active = true;

// -----------------------------------------------------------------------------
// ServiceCatalog constraints and indexes
// -----------------------------------------------------------------------------

CREATE CONSTRAINT service_catalog_service_id IF NOT EXISTS
FOR (sc:ServiceCatalog) REQUIRE sc.service_id IS UNIQUE;

CREATE INDEX service_catalog_active IF NOT EXISTS
FOR (sc:ServiceCatalog) ON (sc.active);

CREATE INDEX service_catalog_id IF NOT EXISTS
FOR (sc:ServiceCatalog) ON (sc.id);

// -----------------------------------------------------------------------------
// TicketFolio constraints and indexes
// -----------------------------------------------------------------------------

CREATE CONSTRAINT ticket_folio_ticket_id IF NOT EXISTS
FOR (tf:TicketFolio) REQUIRE tf.ticket_id IS UNIQUE;

CREATE CONSTRAINT ticket_sequence_name IF NOT EXISTS
FOR (seq:TicketSequence) REQUIRE seq.name IS UNIQUE;

MERGE (seq:TicketSequence {name: 'ticket_folio'})
ON CREATE SET seq.next_value = 0;

CREATE INDEX ticket_folio_status IF NOT EXISTS
FOR (tf:TicketFolio) ON (tf.status);

CREATE INDEX ticket_folio_service_catalog_id IF NOT EXISTS
FOR (tf:TicketFolio) ON (tf.service_catalog_id);

CREATE INDEX ticket_folio_archived IF NOT EXISTS
FOR (tf:TicketFolio) ON (tf.archived);

// -----------------------------------------------------------------------------
// Compatibility backfill helper (additive only)
// -----------------------------------------------------------------------------
// Historical nodes currently storing legacy fields are still expected and should
// remain readable. The following mapping keeps the new domain shape additive:
// - sc.service_id = coalesce(sc.service_id, sc.id)
// - sc.name = coalesce(sc.name, sc.category, sc.id)
// - sc.tier = coalesce(sc.tier, sc.service_tier)
// - sc.sla_target_minutes = coalesce(sc.sla_target_minutes, sc.sla_minutes, 0)
//
// Runtime startup applies the additive compatibility backfill before strict
// duplicate/conflict checks and before enabling constraints. This backfill does
// not modify any Event snapshots or event-derived history.

// -----------------------------------------------------------------------------
// Relationship note for future extension (not implemented here)
// -----------------------------------------------------------------------------
// Optional future relationship kept as derived-only in WU2:
// MATCH (sc:ServiceCatalog)<-[:FOR_SERVICE]-(tf:TicketFolio)
//
// No relationship mutation is performed in this migration.

// -----------------------------------------------------------------------------
// Rollback notes (manual)
// -----------------------------------------------------------------------------
// - DROP CONSTRAINT service_catalog_service_id;
// - DROP INDEX service_catalog_active;
// - DROP INDEX service_catalog_id;
// - DROP CONSTRAINT ticket_folio_ticket_id;
// - DROP INDEX ticket_folio_status;
// - DROP INDEX ticket_folio_service_catalog_id;
// - DROP INDEX ticket_folio_archived;

