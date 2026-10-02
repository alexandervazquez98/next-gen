// PR feat-323-physical-link-model: PhysicalLink metadata model + CONNECTED_VIA relationship.
//
// Slice 1/4 of fiber-optic / physical-link visualization. Decouples the
// physical-link data model from the existing tunnel Link.medium enum.
//
// Why each statement (query evidence from code exploration):
//   :PhysicalLink.id   — uniqueness constraint; backend lookups will use
//                        MATCH (pl:PhysicalLink {id: $id}) as the primary
//                        detail lookup, mirroring the :CI.id pattern from 008.
//   :PhysicalLink.type — supporting index; slice 2 (#444) will filter the
//                        topology render by physical link type, and slice 3
//                        (#439) will aggregate utilization per type.
//   :CONNECTED_VIA     — relationship from CI to PhysicalLink. Created lazily
//                        by the application layer; this migration does not
//                        pre-create it (Neo4j does not require explicit
//                        relationship-type registration).
//
// Idempotency:
//   Every statement uses IF NOT EXISTS so the migration can be re-applied
//   safely. Both the constraint and the index will be no-ops on re-run.
//
// Hard constraints (from #323 body):
//   - Do NOT modify the existing tunnel `medium` field (Literal["vpn","sd_wan","satellite"]).
//   - Do NOT change the existing relationship shape used by tunnel visualization.
//   - PhysicalLink coexists with tunnel links; both queryable independently.
//
// PREFLIGHT (recommended before applying to a live database):
//   PhysicalLink is a new node label; no pre-existing data to collide with.
//   Still worth a quick read-only sanity check:
//     MATCH (n:PhysicalLink) RETURN count(n);
//
// Ownership: feat/323-physical-link-model
// Rollback one-liner:
//   DROP CONSTRAINT physical_link_id_unique IF EXISTS;
//   DROP INDEX physical_link_type IF EXISTS;
CREATE CONSTRAINT physical_link_id_unique IF NOT EXISTS
FOR (pl:PhysicalLink) REQUIRE pl.id IS UNIQUE;

CREATE INDEX physical_link_type IF NOT EXISTS
FOR (pl:PhysicalLink) ON (pl.type);
