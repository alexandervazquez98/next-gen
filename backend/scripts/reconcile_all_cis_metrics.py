"""
Standalone script to reconcile metrics for all existing CIs in the database.
Run with: python backend/scripts/reconcile_all_cis_metrics.py

This is a one-time operation that:
1. Queries all CIs from Neo4j via topology_repo
2. For each CI, calls reconcile_node_metrics()
3. Logs progress and results
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from database import get_db
from services.metric_service import reconcile_node_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def get_all_cis() -> list[dict]:
    """
    Query all CIs from Neo4j (admin-style, no location filtering).
    Returns list of node dicts with id, name, brand, model, layer.
    """
    driver = get_db()
    query = """
        MATCH (n:CI)
        RETURN n.id as id, n.name as name, n.brand as brand,
               n.model as model, n.layer as layer
    """
    with driver.session() as session:
        results = session.run(query)
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "brand": r["brand"],
                "model": r["model"],
                "layer": r["layer"],
            }
            for r in results
        ]


def main():
    logger.info("Starting CI metrics reconciliation...")

    all_cis = get_all_cis()
    total = len(all_cis)

    if total == 0:
        logger.warning("No CIs found in database.")
        return

    logger.info(f"Found {total} CIs to process.")

    assigned_count = 0
    error_count = 0
    processed = 0

    for ci in all_cis:
        processed += 1
        ci_id = ci.get("id") or "<unknown>"

        if processed % 50 == 0 or processed == total:
            logger.info(f"Progress: {processed}/{total} CIs processed...")

        try:
            # Get current metric links before reconciliation
            driver = get_db()
            with driver.session() as session:
                before_result = session.run(
                    "MATCH (n:CI {id: $id})-[r:HAS_METRIC]->(m:MetricDef) RETURN count(r) as count",
                    id=ci_id,
                )
                before_count = before_result.single()["count"] if before_result else 0

            # Reconcile
            reconcile_node_metrics(ci)

            # Get metric links after reconciliation
            with driver.session() as session:
                after_result = session.run(
                    "MATCH (n:CI {id: $id})-[r:HAS_METRIC]->(m:MetricDef) RETURN count(r) as count",
                    id=ci_id,
                )
                after_count = after_result.single()["count"] if after_result else 0

            if after_count > before_count:
                assigned_count += 1
                logger.info(f"[{processed}/{total}] {ci_id} ({ci.get('name', 'N/A')}): "
                            f"metrics {before_count} -> {after_count} (+{after_count - before_count} assigned)")
            else:
                logger.info(f"[{processed}/{total}] {ci_id} ({ci.get('name', 'N/A')}): "
                            f"metrics unchanged ({after_count})")

        except Exception as e:
            error_count += 1
            logger.error(f"[{processed}/{total}] {ci_id}: ERROR — {e}")

    logger.info("=" * 60)
    logger.info("Reconciliation complete.")
    logger.info(f"  Total CIs processed : {total}")
    logger.info(f"  New metric assignments: {assigned_count}")
    logger.info(f"  Errors              : {error_count}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()