// feat-539 / S1: backfill canonical CI -> PhysicalLink connectivity.
//
// Existing PhysicalLink rows keep their endpoint list as the source of truth.
// When both endpoint CI nodes exist, create the two canonical CONNECTED_VIA
// edges. MERGE makes the statement safe to re-run without duplicating edges.
// This migration does not touch CI-to-CI relationships.
MATCH (pl:PhysicalLink)
WHERE size(pl.endpoints) = 2
WITH pl, pl.endpoints[0] AS endpoint_a_id, pl.endpoints[1] AS endpoint_b_id
MATCH (endpoint_a:CI {id: endpoint_a_id})
MATCH (endpoint_b:CI {id: endpoint_b_id})
MERGE (endpoint_a)-[:CONNECTED_VIA]->(pl)
MERGE (endpoint_b)-[:CONNECTED_VIA]->(pl);
