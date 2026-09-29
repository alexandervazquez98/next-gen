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


def aggregate_detail_subgraph(
    cluster_id: str,
    allowed_locations: list[str] | None = None,
    is_admin: bool = False,
    limit: int = 100,
) -> dict[str, Any] | None:
    """Fetch the bounded subgraph for a single cluster visible to the principal.

    Returns ``None`` if the cluster is not visible to the principal
    (hidden-absent parity, REQ-DETAIL-4). Returns a dict with cluster
    metadata, nodes, links, and ``has_more`` for the bounded subgraph.

    For non-admin principals without scope, returns ``None`` without
    hitting the database.
    """
    # Hard rule: no auth -> no DB query.
    if not is_admin and not allowed_locations:
        return None
    driver = get_db()
    query, params = _build_detail_query(
        cluster_id=cluster_id,
        is_admin=is_admin,
        limit=limit,
        allowed_locations=allowed_locations,
    )
    with driver.session() as session:
        result = session.run(query, **params)
        records = [dict(record) for record in result]
    if not records:
        return None
    row = records[0]
    return {
        "cluster": {
            "cluster_id": cluster_id,
            "display_label": row.get("display_label", cluster_id.split(":", 1)[1]),
            "visible_node_count": int(row.get("visible_node_count", 0)),
            "visible_link_count": int(row.get("visible_link_count", 0)),
        },
        "nodes": row.get("nodes") or [],
        "links": row.get("links") or [],
        "has_more": bool(row.get("has_more", False)),
    }


def _build_query(is_admin: bool) -> str:
    """Build the aggregation Cypher with or without the visible-set WHERE.

    #524 — joins ``(n)-[:HAS_EVENT]->(e:Event)`` and aggregates per-cluster
    severity counts so the Geo View can color cluster markers by worst
    severity at country zoom (Tier 2 of the LOD perf migration). Also
    aggregates ``avg(n.location.lat)`` / ``avg(n.location.long)`` as the
    cluster centroid, which the Geo View uses to place markers on the
    map. The rounding happens in the service layer (safe_geo_precision).

    Active = ``status IN ['OPEN', 'ACK']``. RECOVERED and CLOSED events
    are EXCLUDED — the Geo View marks a CI OK when its underlying
    condition clears, and we don't want cluster markers to keep
    painting red after the system healed.

    REQ-9 sensitivity policy: the join is at the cluster aggregate
    level only; per-CI severity is never disclosed.
    """
    location_filter = "" if is_admin else " WHERE n.location_name IN $allowed_locations "
    return f"""
        MATCH (n:CI)
        {location_filter}
        OPTIONAL MATCH (n)-[:HAS_EVENT]->(e:Event)
          WHERE e.status IN ['OPEN', 'ACK']
        WITH n.location_name AS location_name,
             count(DISTINCT n) AS visible_node_count,
             sum(CASE WHEN e.severity = 'CRITICAL' THEN 1 ELSE 0 END) AS critical_count,
             sum(CASE WHEN e.severity = 'WARNING' THEN 1 ELSE 0 END) AS warning_count,
             count(e) AS event_count,
             avg(n.location.lat) AS centroid_lat,
             avg(n.location.long) AS centroid_long
        RETURN
            'location:' + coalesce(location_name, '__unassigned__') AS cluster_id,
            coalesce(location_name, 'Unassigned') AS display_label,
            visible_node_count,
            0 AS visible_link_count,
            false AS aggregate_redacted,
            null AS suppression_reason,
            critical_count,
            warning_count,
            event_count,
            coalesce(centroid_lat, 0.0) AS centroid_lat,
            coalesce(centroid_long, 0.0) AS centroid_long
        ORDER BY cluster_id
    """


def _build_detail_query(
    *,
    cluster_id: str,
    is_admin: bool,
    limit: int,
    allowed_locations: list[str] | None,
) -> tuple[str, dict[str, Any]]:
    """Build the bounded-subgraph Cypher for the detail endpoint.

    Returns one row per cluster_id, with nodes/links aggregated via
    collect(). Authorization happens BEFORE aggregation: a cluster
    whose visible nodes are empty produces no row, returning None for
    the hidden-absent parity case.
    """
    location_filter = "" if is_admin else " AND n.location_name IN $allowed_locations "
    # Extract the axis key from cluster_id (e.g., "location:HQ-Madrid" -> "HQ-Madrid")
    axis_key = cluster_id.split(":", 1)[1] if ":" in cluster_id else cluster_id
    query = f"""
        MATCH (n:CI)
        WHERE (n.location_name = $axis_key OR n.location_name = $unassigned_label)
        {location_filter}
        WITH collect(DISTINCT n) AS nodes
        WITH nodes,
             size(nodes) AS visible_node_count,
             size(nodes) > $limit AS has_more
        OPTIONAL MATCH (n)-[r]->(m)
        WHERE n IN nodes AND (m.location_name = $axis_key OR m.location_name = $unassigned_label)
        {location_filter}
        WITH nodes, visible_node_count, has_more,
             collect(DISTINCT {{
                 source_node_id: n.id,
                 target_node_id: m.id,
                 relationship: type(r)
             }}) AS links,
             [n IN nodes[..$limit] | {{
                 id: n.id,
                 display_label: coalesce(n.name, n.id),
                 kind: coalesce(labels(n), ['CI'])[0],
                 ci_type: coalesce(n.layer, 'CI'),
                 allowed_public_axes: []
             }}] AS nodes_page
        RETURN
            $display_label AS display_label,
            visible_node_count,
            size(links) AS visible_link_count,
            nodes_page AS nodes,
            links[..$limit] AS links,
            has_more
    """
    params: dict[str, Any] = {
        "axis_key": axis_key,
        "unassigned_label": "__unassigned__",
        "display_label": axis_key if axis_key != "__unassigned__" else "Unassigned",
        "limit": limit,
    }
    if not is_admin:
        params["allowed_locations"] = allowed_locations
    return query, params
