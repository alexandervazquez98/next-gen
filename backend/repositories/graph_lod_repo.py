"""Graph LOD repository (#391 PR1).

Wraps the Neo4j aggregation queries for ``GET /graph/overview``. The
contract slice (#390, shipped v1.17.6) defined the value objects and DTOs;
this module owns the runtime Cypher that consumes them.

Hard rule (REQ-OVERVIEW-2): visible-set filtering happens BEFORE
aggregation, in the WHERE clause. A non-admin principal without
``allowed_locations`` MUST NOT trigger any database query.
"""
from __future__ import annotations

from typing import Any

from database import get_db


def aggregate_overview_clusters(
    allowed_locations: list[str] | None = None,
    is_admin: bool = False,
) -> list[dict[str, Any]]:
    """Aggregate CIs into ``location`` clusters visible to the principal.

    Returns a list of dicts shaped as ``OverviewCluster`` rows:

    .. code-block:: python

       {
           "cluster_id": "location:HQ-Madrid",
           "display_label": "HQ-Madrid",
           "visible_node_count": 42,
           "visible_link_count": 17,
           "aggregate_redacted": False,
           "suppression_reason": None,
       }

    For non-admin principals without scope, returns ``[]`` without hitting
    the database. For admin principals, aggregates over the full visible
    graph (no WHERE clause on location).
    """
    # Hard rule: no auth -> no DB query. See test_graph_consumer_authorization.
    if not is_admin and not allowed_locations:
        return []
    driver = get_db()
    query = _build_query(is_admin=is_admin)
    params: dict[str, Any] = {}
    if not is_admin:
        params["allowed_locations"] = allowed_locations
    with driver.session() as session:
        result = session.run(query, **params)
        return [dict(record) for record in result]


def _build_query(is_admin: bool) -> str:
    """Build the aggregation Cypher with or without the visible-set WHERE."""
    location_filter = (
        "" if is_admin else " WHERE n.location_name IN $allowed_locations "
    )
    return f"""
        MATCH (n:CI)
        {location_filter}
        WITH n.location_name AS location_name,
             collect(DISTINCT n) AS nodes
        WITH location_name,
             size(nodes) AS visible_node_count
        RETURN
            'location:' + coalesce(location_name, '__unassigned__') AS cluster_id,
            coalesce(location_name, 'Unassigned') AS display_label,
            visible_node_count,
            0 AS visible_link_count,
            false AS aggregate_redacted,
            null AS suppression_reason
        ORDER BY cluster_id
    """
