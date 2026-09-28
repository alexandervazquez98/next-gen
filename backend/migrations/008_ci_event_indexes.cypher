// PR feat-523-ci-event-neo4j-indexes: Neo4j indexes for CI and Event labels.
//
// Creates uniqueness constraints on :CI.id and :Event.id plus supporting indexes
// on properties used in verified query filters. All statements are IF NOT EXISTS
// so the migration is idempotent and can be re-applied on every cold start.
//
// Why each index (query evidence from code exploration):
//   :CI.id           — uniqueness constraint; topology_repo.py:66 MERGE {id} is the hottest
//                       write path; without it MERGE does a full label scan
//   :Event.id        — uniqueness constraint; event_service.py:1034,1223,1612,1187 do
//                       MATCH (e:Event {id}) as the primary detail lookup
//   event_ci_id      — index on Event.ci_id; event_writer.py:439 dedups COLLECTION_FAILURE
//                       with MATCH (:Event {ci_id, metric_id}) — ci_id is leading
//   event_metric_id  — index on Event.metric_id; event_writer.py:439,491 dedup on
//                       {metric_id, event_type} in two dedup paths
//   ci_status        — index on CI.status; analytics_worker.py:30 filters status='CRITICAL'
//   ci_location_name — index on CI.location_name; topology_repo.py:480 scopes non-admin
//                       users by location with WHERE n.location_name IN $allowed_locations
//   ci_test_seed     — index on CI.test_seed; used to seed synthetic CIs in tests
//   event_status     — index on Event.status; event_service.py:734,783 and event_writer.py:491
//                       filter with WHERE status IN ['OPEN','ACK']. Neo4j range indexes
//                       explicitly support list membership (IN) — this is not a full scan.
//   event_test_seed  — index on Event.test_seed; used to seed synthetic events in tests
//
// Indexes deliberately NOT added:
//   Event.event_type — filtered at event_writer.py:491 inside a compound dedup predicate
//                       already led by metric_id; a second single-column index would be
//                       redundant for that shape.
//
// PREFLIGHT — READ BEFORE APPLYING TO A LIVE DATABASE:
//   Both uniqueness constraints FAIL if duplicates already exist. Uniqueness was only
//   ever maintained by convention (MERGE {id: $id} in topology_repo.py:66), never by a
//   constraint, so drift is possible. Check first — if either query returns rows, this
//   migration will abort and nothing will be applied:
//     MATCH (c:CI)   WITH c.id AS id, count(*) AS n WHERE n > 1 RETURN id, n LIMIT 20;
//     MATCH (e:Event) WITH e.id AS id, count(*) AS n WHERE n > 1 RETURN id, n LIMIT 20;
//
// Ownership: perf/523-ci-event-neo4j-indexes
// Rollback one-liner:
//   DROP CONSTRAINT ci_id_unique IF EXISTS;
//   DROP CONSTRAINT event_id_unique IF EXISTS;
//   DROP INDEX event_ci_id IF EXISTS;
//   DROP INDEX event_metric_id IF EXISTS;
//   DROP INDEX ci_status IF EXISTS;
//   DROP INDEX ci_location_name IF EXISTS;
//   DROP INDEX ci_test_seed IF EXISTS;
//   DROP INDEX event_status IF EXISTS;
//   DROP INDEX event_test_seed IF EXISTS;

CREATE CONSTRAINT ci_id_unique IF NOT EXISTS
FOR (c:CI) REQUIRE c.id IS UNIQUE;

CREATE CONSTRAINT event_id_unique IF NOT EXISTS
FOR (e:Event) REQUIRE e.id IS UNIQUE;

CREATE INDEX event_ci_id IF NOT EXISTS
FOR (e:Event) ON (e.ci_id);

CREATE INDEX event_metric_id IF NOT EXISTS
FOR (e:Event) ON (e.metric_id);

CREATE INDEX ci_status IF NOT EXISTS
FOR (c:CI) ON (c.status);

CREATE INDEX ci_location_name IF NOT EXISTS
FOR (c:CI) ON (c.location_name);

CREATE INDEX ci_test_seed IF NOT EXISTS
FOR (c:CI) ON (c.test_seed);

CREATE INDEX event_status IF NOT EXISTS
FOR (e:Event) ON (e.status);

CREATE INDEX event_test_seed IF NOT EXISTS
FOR (e:Event) ON (e.test_seed);
