"""
Test reconciliation for a single CI (BAJ02-VVU-MEXI-008)
Run: python backend/scripts/test_single_ci_reconcile.py
"""
import sys
sys.path.insert(0, '.')

from database import get_db
from services.metric_service import reconcile_node_metrics

def main():
    node_id = "BAJ02-VVU-MEXI-008"

    with get_db().session() as neo4j:
        result = neo4j.run(
            "MATCH (n:CI) WHERE n.nodeId = $nodeId OR n.name = $nodeId RETURN n.id AS id, n.name AS name, n.brand AS brand, n.model AS model, n.layer AS layer",
            nodeId=node_id
        )
        record = result.single()

    if not record:
        print(f"CI {node_id} not found in database")
        return

    node_dict = {
        "id": record["id"],
        "name": record["name"],
        "brand": record["brand"],
        "model": record["model"],
        "layer": record["layer"]
    }

    print(f"Testing reconcile for CI: {node_dict}")

    with get_db().session() as neo4j:
        before = neo4j.run(
            "MATCH (n:CI {id: $id})-[:HAS_METRIC]->() RETURN count(*) AS count",
            id=node_dict["id"]
        ).single()["count"]
        print(f"Metrics BEFORE reconcile: {before}")

    reconcile_node_metrics(node_dict)

    with get_db().session() as neo4j:
        after = neo4j.run(
            "MATCH (n:CI {id: $id})-[:HAS_METRIC]->() RETURN count(*) AS count",
            id=node_dict["id"]
        ).single()["count"]
        print(f"Metrics AFTER reconcile: {after}")

    if after > before:
        print(f"SUCCESS: {after - before} new metric(s) assigned")
    else:
        print("No new metrics assigned (may already have had correct metrics)")

if __name__ == "__main__":
    main()