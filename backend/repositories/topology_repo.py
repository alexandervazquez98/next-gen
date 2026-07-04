# pyright: reportArgumentType=false
from __future__ import annotations

import importlib
import json
import re
from typing import Any

from config import get_icmp_settings
from database import get_db
from models.core import Node
from polling.icmp_measurements import ICMP_JITTER_METRIC_ID, ICMP_LATENCY_METRIC_ID
from services.tunnel_health import (
    TUNNEL_MEDIA,
    IcmpReason,
    LinkIdentity,
    TunnelAuthoritySample,
    TunnelHealthResponse,
    TunnelIcmpSample,
    encode_link_id,
    normalize_tunnel_health,
)

_relationship_types = importlib.import_module("services.relationship_types")
LISTABLE_RELATIONSHIP_TYPES = _relationship_types.LISTABLE_RELATIONSHIP_TYPES
SUPPORTED_CI_RELATIONSHIP_TYPES = _relationship_types.SUPPORTED_CI_RELATIONSHIP_TYPES
cypher_relationship_union = _relationship_types.cypher_relationship_union
validate_ci_relationship_type = _relationship_types.validate_ci_relationship_type


def get_nodes(
    allowed_locations: list[str] | None = None, is_admin: bool = False
) -> list[dict[str, Any]]:
    driver = get_db()
    query = "MATCH (n:CI)"
    params = {}
    if not is_admin:
        if not allowed_locations:
            return []
        query += " WHERE n.location_name IN $allowed_locations "
        params["allowed_locations"] = allowed_locations
    query += """
        OPTIONAL MATCH (n)-[:CATEGORIZED_AS]->(c:Category)
        OPTIONAL MATCH (n)-[r:HAS_METRIC]->(m:MetricDef)
        RETURN n, c.name as category, c.icon_key as category_icon_key, collect({
            name: m.id, protocol: m.protocol, status: r.status, value: r.last_value, last_updated: r.last_updated
        }) as metrics
        """
    with driver.session() as session:
        result = session.run(query, **params)
        return [
            {
                "node": r["n"],
                "category": r["category"],
                "category_icon_key": r["category_icon_key"],
                "metrics": r["metrics"],
            }
            for r in result
        ]


def upsert_node(node: Node) -> None:
    driver = get_db()
    snmp_str = json.dumps(node.snmp) if isinstance(node.snmp, dict) else node.snmp
    query = """
    MERGE (n:CI {id: $id})
    SET n.name = $label, n.layer = $type, n.status = $status, n.ip = $ip, n.owner = $owner,
        n.location_name = $loc_name, n.brand = $brand, n.model = $model, n.serialNumber = $serial,
        n.firmwareVersion = $firmware, n.snmp = $snmp, n.pollingInterval = $polling, n.updated_at = datetime()
    """
    # Slice 1 (feat-324): persist CI public_ip alongside the existing fields.
    # The setter is included unconditionally so existing CIs without a public_ip
    # are explicitly written as None (no backfill) and the column stays queryable.
    query += ", n.public_ip = $public_ip"
    if node.location and "lat" in node.location and "long" in node.location:
        query += ", n.location = point({latitude: $lat, longitude: $lng})"
    query += "\nWITH n MERGE (c:Category {name: $type}) MERGE (n)-[:CATEGORIZED_AS]->(c)"
    if node.owner:
        query += "\nWITH n MERGE (o:OwnerGroup {name: $owner}) MERGE (n)-[:OWNED_BY]->(o)"
    if node.brand and node.model:
        query += "\nWITH n MERGE (h:HardwareModel {brand: $brand, model: $model}) MERGE (n)-[:IS_MODEL]->(h)"
    with driver.session() as session:
        session.run(
            query,
            id=node.id,
            label=node.label,
            type=node.type,
            status=node.status,
            ip=node.ip,
            owner=node.owner,
            loc_name=node.location_name,
            brand=node.brand,
            model=node.model,
            serial=node.serialNumber or "",
            firmware=node.firmwareVersion or "",
            snmp=snmp_str,
            polling=node.pollingInterval,
            lat=node.location.get("lat") if node.location else 0,
            lng=node.location.get("long") if node.location else 0,
            public_ip=node.public_ip,
        )


def delete_node(node_id: str) -> None:
    driver = get_db()
    with driver.session() as session:
        session.run("MATCH (n:CI {id: $id}) DETACH DELETE n", id=node_id)


def get_node_usage(node_id: str) -> int:
    driver = get_db()
    with driver.session() as session:
        res = session.run(
            "MATCH (n:CI {id: $id})-[r]-() RETURN count(r) as count", id=node_id
        ).single()
        return res["count"] if res else 0


def get_valid_owners_and_layers() -> tuple[set[str], set[str]]:
    driver = get_db()
    with driver.session() as session:
        res_o = session.run("MATCH (o:OwnerGroup) RETURN o.name as name")
        res_c = session.run("MATCH (c:Category) RETURN c.name as name")
        return {r["name"] for r in res_o}, {r["name"] for r in res_c}


def bulk_insert_node(
    nid,
    label,
    ntype,
    status,
    ip,
    brand,
    model,
    serial,
    firmware,
    lat,
    long,
    polling,
    snmp_str,
    metadata,
    owner,
):
    driver = get_db()
    with driver.session() as session:
        session.run(
            """
            MERGE (n:CI {id: $id})
            SET n.name = $label, n.layer = $type, n.status = $status, n.ip = $ip, n.brand = $brand, n.model = $model,
                n.serialNumber = $serial, n.firmwareVersion = $firmware, n.location = point({latitude: $lat, longitude: $long}),
                n.location_name = $loc_name, n.pollingInterval = $polling, n.snmp = $snmp
            SET n += $metadata
            WITH n MERGE (c:Category {name: $type}) MERGE (n)-[:CATEGORIZED_AS]->(c)
            WITH n WHERE $owner <> '' MERGE (o:OwnerGroup {name: $owner}) MERGE (n)-[:OWNED_BY]->(o)
        """,
            id=nid,
            label=label,
            type=ntype,
            status=status,
            ip=ip,
            brand=brand,
            model=model,
            serial=serial,
            firmware=firmware,
            lat=lat,
            long=long,
            loc_name=metadata.get("location_name"),
            polling=polling,
            snmp=snmp_str,
            metadata=metadata,
            owner=owner,
        )


# Valid relationship types for injection prevention
_VALID_RELATIONSHIPS = SUPPORTED_CI_RELATIONSHIP_TYPES


def _validate_relationship(rel: str) -> str:
    """Validate and sanitize relationship type. Raises ValueError if invalid."""
    return validate_ci_relationship_type(rel)


# Valid node labels for injection prevention
_VALID_NODE_LABELS = frozenset(
    {"CI", "MetricDef", "Category", "OwnerGroup", "HardwareModel", "User"}
)


def _validate_node_label(label: str) -> str:
    """Validate node label. Raises ValueError if invalid."""
    if label not in _VALID_NODE_LABELS:
        raise ValueError(f"Invalid node label: {label}")
    return label


def _row_value(row, key: str, default=None):
    if row is None:
        return default
    if hasattr(row, "get"):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _authority_from_tunnel_row(row) -> TunnelAuthoritySample | None:
    state = _row_value(row, "tunnel_authority_state")
    if state not in {"UP", "DOWN"}:
        return None
    return TunnelAuthoritySample(
        state=state,
        source=_row_value(row, "tunnel_authority_source"),
        observed_at=_row_value(row, "tunnel_authority_observed_at"),
    )


def _icmp_from_tunnel_row(row) -> TunnelIcmpSample | None:
    available = _row_value(row, "tunnel_icmp_available")
    latency_ms = _row_value(row, "tunnel_icmp_latency_ms")
    error = _row_value(row, "tunnel_icmp_error")
    reason = _row_value(row, "tunnel_icmp_reason")
    if available is None and latency_ms is None and error is None and reason is None:
        return None
    return TunnelIcmpSample(
        available=bool(available),
        latency_ms=latency_ms,
        error=error,
        reason=reason if reason in IcmpReason.__args__ else None,
    )


def get_tunnel_health_link(
    identity: LinkIdentity,
    allowed_locations: list[str] | None = None,
    is_admin: bool = False,
) -> TunnelHealthResponse | None:
    """Read latest tunnel health for one eligible, scoped CI-to-CI tunnel link."""
    rel = _validate_relationship(identity.relationship)
    if identity.medium not in TUNNEL_MEDIA:
        raise ValueError(f"Invalid tunnel medium: {identity.medium}")
    if not is_admin and not allowed_locations:
        return None

    driver = get_db()
    query = f"""
        MATCH (a:CI {{id: $source}})-[r:{rel}]->(b:CI {{id: $target}})
        WHERE r.medium = $medium
          AND r.medium IN $eligible_media
    """
    params: dict[str, Any] = {
        "source": identity.source,
        "target": identity.target,
        "medium": identity.medium,
        "eligible_media": sorted(TUNNEL_MEDIA),
    }
    if not is_admin:
        query += (
            " AND (a.location_name IN $allowed_locations OR b.location_name IN $allowed_locations)"
        )
        params["allowed_locations"] = allowed_locations
    query += """
        RETURN a.id AS source_id,
               a.public_ip AS source_public_ip,
               b.id AS target_id,
               b.public_ip AS target_public_ip,
               type(r) AS relationship,
               r.medium AS medium,
               r.tunnel_health_status AS tunnel_health_status,
               r.tunnel_authority_state AS tunnel_authority_state,
               r.tunnel_authority_source AS tunnel_authority_source,
               r.tunnel_authority_observed_at AS tunnel_authority_observed_at,
               r.tunnel_icmp_available AS tunnel_icmp_available,
               r.tunnel_icmp_latency_ms AS tunnel_icmp_latency_ms,
               r.tunnel_icmp_error AS tunnel_icmp_error,
               r.tunnel_icmp_reason AS tunnel_icmp_reason,
               r.tunnel_observed_at AS tunnel_observed_at
    """
    with driver.session() as session:
        row = session.run(query, **params).single()
    if not row:
        return None

    link_id = encode_link_id(identity)
    missing_public_ip = not _row_value(row, "source_public_ip") or not _row_value(
        row, "target_public_ip"
    )
    return normalize_tunnel_health(
        link_id=link_id,
        source=_row_value(row, "source_id"),
        target=_row_value(row, "target_id"),
        relationship=_row_value(row, "relationship"),
        medium=_row_value(row, "medium"),
        authority=_authority_from_tunnel_row(row),
        icmp=_icmp_from_tunnel_row(row),
        missing_public_ip=missing_public_ip,
        observed_at=_row_value(row, "tunnel_observed_at"),
    )


def save_latest_tunnel_health(identity: LinkIdentity, health: TunnelHealthResponse) -> None:
    """Persist latest-only tunnel health as scalar properties on the relationship."""
    rel = _validate_relationship(identity.relationship)
    if identity.medium not in TUNNEL_MEDIA:
        raise ValueError(f"Invalid tunnel medium: {identity.medium}")
    driver = get_db()
    query = f"""
        MATCH (a:CI {{id: $source}})-[r:{rel}]->(b:CI {{id: $target}})
        WHERE r.medium = $medium
        SET r.tunnel_health_status = $status,
            r.tunnel_authority_state = $authority_state,
            r.tunnel_authority_source = $authority_source,
            r.tunnel_authority_observed_at = $authority_observed_at,
            r.tunnel_icmp_available = $icmp_available,
            r.tunnel_icmp_latency_ms = $icmp_latency_ms,
            r.tunnel_icmp_error = $icmp_error,
            r.tunnel_icmp_reason = $icmp_reason,
            r.tunnel_observed_at = $observed_at
    """
    with driver.session() as session:
        session.run(
            query,
            source=identity.source,
            target=identity.target,
            medium=identity.medium,
            status=health.status,
            authority_state=health.authority.state,
            authority_source=health.authority.source,
            authority_observed_at=health.authority.observed_at,
            icmp_available=health.icmp.available,
            icmp_latency_ms=health.icmp.latency_ms,
            icmp_error=health.icmp.error,
            icmp_reason=health.icmp.reason,
            observed_at=health.observed_at,
        )


def get_template_data():
    driver = get_db()
    with driver.session() as session:
        res_o = session.run("MATCH (o:OwnerGroup) RETURN o.name as name ORDER BY o.name")
        res_c = session.run("MATCH (c:Category) RETURN c.name as name ORDER BY c.name")
        return [r["name"] for r in res_o], [r["name"] for r in res_c]


def get_links(allowed_locations=None, is_admin=False):
    driver = get_db()
    rel_union = cypher_relationship_union(LISTABLE_RELATIONSHIP_TYPES)
    query = f"""
        MATCH (a)-[r:{rel_union}]->(b)
        WHERE (a:CI OR a:MetricDef) AND (b:CI OR b:MetricDef)
          AND a.id IS NOT NULL AND b.id IS NOT NULL
    """
    params = {}
    if not is_admin:
        if not allowed_locations:
            return []
        query += (
            " AND (a.location_name IN $allowed_locations OR b.location_name IN $allowed_locations) "
        )
        params["allowed_locations"] = allowed_locations
    # Slice 1 (feat-324): tunnel medium is an optional relationship property;
    # return it only when present so legacy consumers see no shape change.
    query += " RETURN a.id as s, COALESCE(a.name, a.id) as sl, b.id as t, COALESCE(b.name, b.id) as tl, type(r) as rel, r.medium as medium"
    with driver.session() as session:
        links = []
        for r in session.run(query, **params):
            link = {
                "source": r["s"],
                "source_label": r["sl"],
                "target": r["t"],
                "target_label": r["tl"],
                "relationship": r["rel"],
            }
            medium = r.get("medium")
            if medium:
                link["medium"] = medium
            links.append(link)
        return links


def create_link(source, target, relationship, medium=None):
    driver = get_db()
    rel = _validate_relationship(relationship)
    # Slice 1 (feat-324): persist tunnel medium on the relationship when set.
    # Non-tunnel calls continue to pass medium=None which is a no-op setter.
    set_clause = ""
    params = {"s": source, "t": target}
    if medium is not None:
        set_clause = " SET r.medium = $medium"
        params["medium"] = medium
    query = f"MATCH (a {{id: $s}}), (b {{id: $t}}) WHERE a.id = $s AND b.id = $t MERGE (a)-[r:{rel}]->(b){set_clause}"
    with driver.session() as session:
        session.run(query, **params)


def get_endpoint_types(source_id: str, target_id: str) -> dict:
    """Look up the `layer` of each endpoint CI by id.

    Returns ``{"source_type": str | None, "target_type": str | None}`` so the
    hub-obligatorio validator can reason about endpoints that arrive without
    an explicit type (e.g. legacy CI records whose layer is stored only on
    the node itself). Missing endpoints surface as ``None``.
    """
    driver = get_db()
    with driver.session() as session:
        result = session.run(
            "MATCH (a:CI {id: $source_id}), (b:CI {id: $target_id}) "
            "RETURN a.layer AS source_type, b.layer AS target_type",
            source_id=source_id,
            target_id=target_id,
        ).single()
    if not result:
        return {"source_type": None, "target_type": None}
    return {
        "source_type": result.get("source_type"),
        "target_type": result.get("target_type"),
    }


def update_link(source, target, relationship, medium=None):
    """Update an existing relationship, optionally setting `medium`.

    If the relationship already carries a medium value, the new value (when
    provided) overwrites it. Pass ``medium=None`` to leave the existing
    value untouched.
    """
    driver = get_db()
    rel = _validate_relationship(relationship)
    set_clause = ""
    params = {"s": source, "t": target}
    if medium is not None:
        set_clause = " SET r.medium = $medium"
        params["medium"] = medium
    query = (
        f"MATCH (a {{id: $s}})-[r:{rel}]->(b {{id: $t}}) "
        f"WHERE a.id = $s AND b.id = $t{set_clause}"
    )
    with driver.session() as session:
        session.run(query, **params)


def delete_link(source, target, relationship):
    driver = get_db()
    rel = _validate_relationship(relationship)
    with driver.session() as session:
        session.run(f"MATCH (a {{id: $s}})-[r:{rel}]->(b {{id: $t}}) DELETE r", s=source, t=target)


def _get_nodes_by_filter(filter_obj, is_admin, allowed_locations):
    driver = get_db()
    label = filter_obj.get("label", "CI")
    where, params = [], {}

    # Priority 1: Explicit ID list
    if filter_obj.get("ids"):
        where.append("n.id IN $ids")
        params["ids"] = filter_obj["ids"]
    # Priority 2: Singular ID (from dropdowns)
    elif filter_obj.get("id"):
        where.append("n.id = $id")
        params["id"] = filter_obj["id"]
    # Priority 3: Metadata Filters (Layer, Brand, Model)
    else:
        if filter_obj.get("layer"):
            where.append("n.layer = $layer")
            params["layer"] = filter_obj["layer"]
        if filter_obj.get("brand"):
            where.append("n.brand = $brand")
            params["brand"] = filter_obj["brand"]
        if filter_obj.get("model"):
            where.append("n.model = $model")
            params["model"] = filter_obj["model"]
        if filter_obj.get("searchTerm"):
            where.append("(n.name =~ $search OR n.ip =~ $search OR n.location_name =~ $search)")
            params["search"] = f"(?i).*{filter_obj['searchTerm']}.*"

    if not is_admin and allowed_locations and label == "CI":
        where.append("n.location_name IN $allowed")
        params["allowed"] = allowed_locations

    q = f"MATCH (n:{_validate_node_label(label)})"
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " RETURN n"

    with driver.session() as session:
        res = session.run(q, **params)
        return [record["n"] for record in res]


def count_potential_links(source_filter, target_filter, allowed_locations=None, is_admin=False):
    src_nodes = _get_nodes_by_filter(source_filter, is_admin, allowed_locations)
    tgt_nodes = _get_nodes_by_filter(target_filter, is_admin, allowed_locations)

    src_ids = list(set([n["id"] for n in src_nodes]))
    tgt_ids = list(set([n["id"] for n in tgt_nodes]))

    total = len(src_ids) * len(tgt_ids)
    return {
        "total": total,
        "source_samples": [n["name"] for n in src_nodes[:5]],
        "target_samples": [n["name"] for n in tgt_nodes[:5]],
    }


def execute_mass_links(
    source_filter, target_filter, relationship, allowed_locations=None, is_admin=False
):
    driver = get_db()
    rel = _validate_relationship(relationship)
    src_nodes = _get_nodes_by_filter(source_filter, is_admin, allowed_locations)
    tgt_nodes = _get_nodes_by_filter(target_filter, is_admin, allowed_locations)

    src_ids = list(set([n["id"] for n in src_nodes]))
    tgt_ids = list(set([n["id"] for n in tgt_nodes]))

    label_a = source_filter.get("label", "CI")
    label_b = target_filter.get("label", "CI")

    query = f"MATCH (a:{label_a}), (b:{label_b}) WHERE a.id IN $src_ids AND b.id IN $tgt_ids AND a.id <> b.id MERGE (a)-[r:{rel}]->(b) RETURN count(r) as total"

    with driver.session() as session:
        res = session.run(query, src_ids=src_ids, tgt_ids=tgt_ids)
        rec = res.single()
        stats = res.consume()
        total = rec["total"] if rec else 0
        return {
            "total": total,
            "created": stats.counters.relationships_created,
            "verified": total - stats.counters.relationships_created,
        }


def execute_mass_delete(
    source_filter, target_filter, relationship, allowed_locations=None, is_admin=False
):
    driver = get_db()
    rel = _validate_relationship(relationship)
    src_nodes = _get_nodes_by_filter(source_filter, is_admin, allowed_locations)
    tgt_nodes = _get_nodes_by_filter(target_filter, is_admin, allowed_locations)
    src_ids = list(set([n["id"] for n in src_nodes]))
    tgt_ids = list(set([n["id"] for n in tgt_nodes]))

    label_a = source_filter.get("label", "CI")
    label_b = target_filter.get("label", "CI")

    query = f"MATCH (a:{label_a})-[r:{rel}]->(b:{label_b}) WHERE a.id IN $src_ids AND b.id IN $tgt_ids DELETE r RETURN count(*) as total"
    with driver.session() as session:
        r = session.run(query, src_ids=src_ids, tgt_ids=tgt_ids).single()
        return {"deleted": r["total"] if r else 0}


def execute_mass_update(
    source_filter, target_filter, old_rel, new_rel, allowed_locations=None, is_admin=False
):
    driver = get_db()
    o_rel = _validate_relationship(old_rel)
    n_rel = _validate_relationship(new_rel)
    src_nodes = _get_nodes_by_filter(source_filter, is_admin, allowed_locations)
    tgt_nodes = _get_nodes_by_filter(target_filter, is_admin, allowed_locations)
    src_ids = list(set([n["id"] for n in src_nodes]))
    tgt_ids = list(set([n["id"] for n in tgt_nodes]))

    label_a = source_filter.get("label", "CI")
    label_b = target_filter.get("label", "CI")

    query = f"MATCH (a:{label_a})-[o:{o_rel}]->(b:{label_b}) WHERE a.id IN $src_ids AND b.id IN $tgt_ids DELETE o MERGE (a)-[n:{n_rel}]->(b) RETURN count(n) as total"
    with driver.session() as session:
        r = session.run(query, src_ids=src_ids, tgt_ids=tgt_ids).single()
        return {"updated": r["total"] if r else 0}


def get_filtered_graph_data(
    layer=None, location=None, owner=None, allowed_locations=None, is_admin=False
):
    driver = get_db()
    where, params = [], {}

    def normalize_filter(value):
        if not value:
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return [part.strip() for part in str(value).split(",") if part.strip()]

    layers = normalize_filter(layer)
    locations = normalize_filter(location)
    owners = normalize_filter(owner)
    if layers:
        where.append("n.layer IN $layers")
        params["layers"] = layers
    if locations:
        where.append("n.location_name IN $locations")
        params["locations"] = locations
    if owners:
        where.append("n.owner IN $owners")
        params["owners"] = owners
    if not is_admin and allowed_locations:
        where.append("n.location_name IN $allowed_locations")
        params["allowed_locations"] = allowed_locations
    w_str = ("WHERE " + " AND ".join(where)) if where else ""
    with driver.session() as session:
        # Build the query: include every scoped CI. Geographic coordinates are optional
        # and are only reconstructed for frontend map placement when present.
        node_query = f"""
            MATCH (n:CI)
            {w_str}
            OPTIONAL MATCH (n)-[r:HAS_METRIC]->(m:MetricDef)
            RETURN n,
                   CASE WHEN n.location IS NULL THEN null ELSE n.location.latitude END as lat,
                   CASE WHEN n.location IS NULL THEN null ELSE n.location.longitude END as lng,
                   labels(n) as labels,
                   collect({{
                       name: m.id,
                       protocol: m.protocol,
                       status: r.status,
                       value: r.last_value,
                       last_updated: r.last_updated
                   }}) as metrics
        """
        nodes = []
        for r in session.run(node_query, **params):
            node_data = dict(r["n"])
            node_data["_labels"] = r["labels"]

            # Serialize node properties (for metadata)
            for k, v in node_data.items():
                if hasattr(v, "isoformat"):
                    node_data[k] = v.isoformat()

            # Filter out null metrics (from collect in Neo4j) and serialize
            metrics = []
            for m in r["metrics"]:
                if m.get("name") is not None:
                    if hasattr(m.get("last_updated"), "isoformat"):
                        m["last_updated"] = m["last_updated"].isoformat()
                    metrics.append(m)
            node_data["metrics"] = metrics

            # Reconstruct location object for frontend
            if r["lat"] is not None and r["lng"] is not None:
                node_data["location"] = {"lat": r["lat"], "long": r["lng"]}
            nodes.append(node_data)

        # Build link WHERE clause: apply location/owner/layer filters to BOTH endpoints with OR
        # This ensures links are shown if EITHER endpoint matches the filter
        # Security constraint (allowed_locations) is ALWAYS AND'd - never mixed with OR
        link_filters = []
        security_filter = None
        for cond in where:
            # Extract security filter to apply separately
            if "allowed_locations" in cond:
                # Transform to apply to both endpoints a and b
                security_filter = cond.replace("n.", "a.") + " OR " + cond.replace("n.", "b.")
                continue
            if "n." in cond:
                # Replace n. prefix with a. and b. for the link query
                link_filters.append(cond.replace("n.", "a."))
                link_filters.append(cond.replace("n.", "b."))

        # Build the link query with proper AND/OR structure:
        # Security is always AND'd, user filters are OR'd per condition group
        link_conditions = []
        if security_filter:
            link_conditions.append(f"({security_filter})")
        if link_filters:
            # Group by pairs: each original condition produces [a.version, b.version]
            # Join each pair with OR, then join all pairs with AND
            # link_filters is [a.cond1, b.cond1, a.cond2, b.cond2, ...]
            # We need to pair them: (a.cond1 OR b.cond1) AND (a.cond2 OR b.cond2)
            paired = []
            for i in range(0, len(link_filters), 2):
                paired.append(f"({link_filters[i]} OR {link_filters[i+1]})")
            link_conditions.append(" AND ".join(paired))
        l_where = (" WHERE " + " AND ".join(link_conditions)) if link_conditions else ""
        # Slice 1 (feat-324): include r.medium in the link payload when set;
        # legacy non-tunnel links stay shape-compatible for downstream
        # consumers (link_service.get_full_graph only forwards medium when
        # truthy).
        links = []
        for r in session.run(f"MATCH (a:CI)-[r]->(b:CI){l_where} RETURN a, r, b", **params):
            link_entry = {
                "source_node": dict(r["a"]),
                "target_node": dict(r["b"]),
                "type": r["r"].type,
            }
            medium = getattr(r["r"], "medium", None)
            if medium:
                link_entry["medium"] = medium
            links.append(link_entry)
        return nodes, links


def get_cis_relationship_summary(ci_ids: list[str], allowed_locations=None, is_admin=False) -> dict:
    """
    Batch-fetch CI relationship summary for a set of CI ids.
    Returns {ci_id: {asSource: [{otherId, otherLabel, type}], asTarget: [...]}}.
    Applies the same location scoping pattern used by /links and caps at 1000 ids.
    """
    if not ci_ids:
        return {}
    ci_ids = list(ci_ids)[:1000]
    summary: dict[str, dict] = {cid: {"asSource": [], "asTarget": []} for cid in ci_ids}
    if not is_admin and not allowed_locations:
        return summary

    driver = get_db()
    rel_union = cypher_relationship_union(SUPPORTED_CI_RELATIONSHIP_TYPES)
    query = f"""
        MATCH (a:CI)-[r:{rel_union}]->(b:CI)
    """
    params: dict[str, Any] = {"ci_ids": ci_ids}
    if is_admin:
        query += " WHERE (a.id IN $ci_ids OR b.id IN $ci_ids)"
    else:
        query += """
        WHERE ((a.id IN $ci_ids AND a.location_name IN $allowed_locations)
            OR (b.id IN $ci_ids AND b.location_name IN $allowed_locations))
        """
        params["allowed_locations"] = allowed_locations
    query += """
        RETURN a.id AS source_id, COALESCE(a.name, a.id) AS source_label, a.location_name AS source_location,
               b.id AS target_id, COALESCE(b.name, b.id) AS target_label, b.location_name AS target_location,
               type(r) AS rel_type
    """
    with driver.session() as session:
        results = session.run(query, **params)
        records = list(results)  # Consume all records inside the session block
    allowed_set = set(allowed_locations or [])
    for row in records:
        src, tgt, rel = row["source_id"], row["target_id"], row["rel_type"]
        src_label, tgt_label = row["source_label"], row["target_label"]
        source_visible = is_admin or row.get("source_location") in allowed_set
        target_visible = is_admin or row.get("target_location") in allowed_set
        # If ci_ids contains source, it appears as "source" in the rel
        if src in summary and source_visible:
            summary[src]["asSource"].append({"otherId": tgt, "otherLabel": tgt_label, "type": rel})
        # If ci_ids contains target, it appears as "target" in the rel
        if tgt in summary and target_visible:
            summary[tgt]["asTarget"].append({"otherId": src, "otherLabel": src_label, "type": rel})

    return summary


def find_open_parent_event(ci_id: str, max_depth: int = 3) -> dict[str, Any] | None:
    """
    Traverse parent CIs via DEPENDS_ON/HOSTED_ON/CONNECTS_TO relationships up to max_depth levels.
    Return the first OPEN/ACK event found on a parent CI, plus root_cause_ci_id.

    Returns dict with keys: {parent_event_id, root_cause_ci_id, correlation_type}
    or None if no parent has an open event.

    Traversal: DEPENDS_ON, HOSTED_ON, CONNECTS_TO up to max_depth levels.
    """
    driver = get_db()
    with driver.session() as session:
        result = session.run(
            f"""
            MATCH (ci:CI {{id: $ci_id}})
            MATCH (ci)-[r:DEPENDS_ON|HOSTED_ON|CONNECTS_TO*1..{max_depth}]->(parent:CI)
            MATCH (parent)-[:HAS_EVENT]->(pe:Event)
            WHERE pe.status IN ['OPEN', 'ACK']
            RETURN pe.id AS parent_event_id,
                   pe.ci_id AS parent_ci_id,
                   pe.correlation_type AS correlation_type,
                   pe.root_cause_ci_id AS root_cause_ci_id
            ORDER BY CASE pe.severity WHEN 'CRITICAL' THEN 1 WHEN 'WARNING' THEN 2 ELSE 3 END ASC, pe.created_at ASC
            LIMIT 1
            """,
            ci_id=ci_id,
        ).single()

        if not result:
            return None

        return {
            "parent_event_id": result["parent_event_id"],
            "root_cause_ci_id": result.get("root_cause_ci_id") or result["parent_ci_id"],
            "correlation_type": result.get("correlation_type"),
        }


def build_open_parent_index(
    session, pairs: set[tuple[str, str]]
) -> dict[tuple[str, str], dict[str, Any]]:
    """Batched variant of ``find_open_parent_event`` keyed by ``(ci_id, metric_id)``.

    Walks upstream via ``DEPENDS_ON|HOSTED_ON|CONNECTS_TO`` to depth 3 for every
    requested pair in ONE Cypher pass, mirroring ``find_open_parent_event``.
    Non-propagating metrics (``MetricDef.can_propagate = false``) are filtered
    INSIDE the Cypher (``WHERE coalesce(m.can_propagate, true) = true``) so they
    never appear as keys in the returned dict — callers treat a missing key as
    ROOT (see ``engines.snmp_worker._resolve_correlation``).

    Args:
        session: an open Neo4j driver session.
        pairs: set of ``(ci_id, metric_id)`` tuples to resolve.

    Returns:
        ``{(ci_id, metric_id): {"parent_event_id", "root_cause_ci_id",
        "correlation_type"}}`` for hits. Missing keys = ROOT. Empty input →
        empty dict (no query round-trip).
    """
    if not pairs:
        return {}

    records = session.run(
        """
        UNWIND $pairs AS pair
        MATCH (ci:CI {id: pair.ci_id})
        MATCH (m:MetricDef {id: pair.metric_id})
        WHERE coalesce(m.can_propagate, true) = true
        MATCH (ci)-[:DEPENDS_ON|HOSTED_ON|CONNECTS_TO*1..3]->(parent:CI)
        MATCH (parent)-[:HAS_EVENT]->(pe:Event)
        WHERE pe.status IN ['OPEN', 'ACK']
        WITH pair, pe, parent
        ORDER BY pair.ci_id, pair.metric_id,
                 CASE pe.severity WHEN 'CRITICAL' THEN 1 WHEN 'WARNING' THEN 2 ELSE 3 END ASC,
                 pe.created_at ASC
        WITH pair, head(collect(pe)) AS parent_event
        RETURN pair.ci_id AS ci_id,
               pair.metric_id AS metric_id,
               parent_event.id AS parent_event_id,
               parent_event.ci_id AS parent_ci_id,
               parent_event.root_cause_ci_id AS root_cause_ci_id,
               parent_event.correlation_type AS correlation_type
        """,
        pairs=[{"ci_id": ci_id, "metric_id": metric_id} for ci_id, metric_id in pairs],
    )

    index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in records:
        ci_id = row["ci_id"]
        metric_id = row["metric_id"]
        parent_event_id = row["parent_event_id"]
        if not parent_event_id:
            continue
        index[(ci_id, metric_id)] = {
            "parent_event_id": parent_event_id,
            "root_cause_ci_id": row.get("root_cause_ci_id") or row.get("parent_ci_id"),
            "correlation_type": "PROPAGATED",
        }
    return index


def ensure_icmp_sidecar_metric_defs(session) -> None:
    icmp_settings = get_icmp_settings()
    session.run(
        """
        MERGE (latency:MetricDef {id: $latency_id})
        SET latency.name = 'ICMP Latency',
            latency.protocol = 'ICMP',
            latency.description = 'ICMP ping round-trip latency in milliseconds',
            latency.dataType = 'FLOAT',
            latency.unit = 'ms',
            latency.operator = '>=',
            latency.warning = $latency_warning_ms,
            latency.critical = $latency_critical_ms,
            latency.criticality = coalesce(latency.criticality, 3),
            latency.metric_kind = 'telemetry'
        MERGE (jitter:MetricDef {id: $jitter_id})
        SET jitter.name = 'ICMP Jitter',
            jitter.protocol = 'ICMP',
            jitter.description = 'Absolute delta between consecutive successful ICMP latency samples',
            jitter.dataType = 'FLOAT',
            jitter.unit = 'ms',
            jitter.operator = '>=',
            jitter.criticality = coalesce(jitter.criticality, 1),
            jitter.metric_kind = 'telemetry'
    """,
        latency_id=ICMP_LATENCY_METRIC_ID,
        jitter_id=ICMP_JITTER_METRIC_ID,
        latency_warning_ms=icmp_settings.latency_warning_ms,
        latency_critical_ms=icmp_settings.latency_critical_ms,
    )


def migrate_icmp_sidecar_metrics() -> None:
    """Idempotently link ICMP latency/jitter MetricDefs to existing CIs with IPs."""
    driver = get_db()
    with driver.session() as session:
        ensure_icmp_sidecar_metric_defs(session)
        session.run(
            """
            MATCH (n:CI)
            WHERE n.ip IS NOT NULL AND trim(toString(n.ip)) <> ''
            MATCH (latency:MetricDef {id: $latency_id})
            MATCH (jitter:MetricDef {id: $jitter_id})
            MERGE (n)-[:HAS_METRIC]->(latency)
            MERGE (n)-[:HAS_METRIC]->(jitter)
        """,
            latency_id=ICMP_LATENCY_METRIC_ID,
            jitter_id=ICMP_JITTER_METRIC_ID,
        )


def migrate_icmp_availability_source() -> None:
    """Backfill explicit availability_source for existing ICMP availability metrics/events.

    ICMP latency and jitter sidecars stay telemetry-only and are intentionally
    excluded from the availability source-of-truth tag.
    """
    excluded_metric_ids = [ICMP_LATENCY_METRIC_ID, ICMP_JITTER_METRIC_ID, "mariadb-GS"]
    driver = get_db()
    with driver.session() as session:
        session.run(
            """
            MATCH (m:MetricDef)
            WHERE toUpper(coalesce(m.protocol, '')) = 'ICMP'
              AND NOT m.id IN $excluded_metric_ids
              AND coalesce(m.name, '') <> 'mariadb-GS'
              AND coalesce(m.metric_kind, 'availability') <> 'telemetry'
            SET m.availability_source = coalesce(m.availability_source, 'ICMP'),
                m.metric_kind = coalesce(m.metric_kind, 'availability')
        """,
            excluded_metric_ids=excluded_metric_ids,
        )
        session.run(
            """
            MATCH (e:Event)-[:TRIGGERED_BY]->(m:MetricDef)
            WHERE e.event_type = 'AVAILABILITY'
              AND toUpper(coalesce(e.source_protocol, '')) = 'ICMP'
              AND toUpper(coalesce(m.protocol, '')) = 'ICMP'
              AND m.availability_source IN ['PING', 'ICMP']
              AND NOT m.id IN $excluded_metric_ids
              AND coalesce(m.name, '') <> 'mariadb-GS'
            SET e.availability_source = m.availability_source
        """,
            excluded_metric_ids=excluded_metric_ids,
        )
        session.run(
            """
            MATCH (e:Event)
            WHERE e.event_type = 'AVAILABILITY'
              AND toUpper(coalesce(e.source_protocol, '')) = 'ICMP'
              AND e.metric_id IS NOT NULL
              AND NOT e.metric_id IN $excluded_metric_ids
              AND NOT EXISTS {
                MATCH (e)-[:TRIGGERED_BY]->(:MetricDef)
              }
            SET e.availability_source = coalesce(e.availability_source, 'ICMP')
        """,
            excluded_metric_ids=excluded_metric_ids,
        )


def create_default_ping_metric(node_id: str, node_label: str) -> None:
    """
    Ensure ICMP latency and jitter metrics are available for a CI.

    Do not create a per-CI PING availability MetricDef. The queue scheduler
    derives an internal ICMP availability polling task from these sidecar links
    so latency/jitter can be collected without polluting the metric catalog with
    one ping metric per CI.
    """
    driver = get_db()
    with driver.session() as session:
        ensure_icmp_sidecar_metric_defs(session)
        session.run(
            """
            MATCH (n:CI {id: $node_id})
            MATCH (latency:MetricDef {id: $latency_id})
            MATCH (jitter:MetricDef {id: $jitter_id})
            MERGE (n)-[:HAS_METRIC]->(latency)
            MERGE (n)-[:HAS_METRIC]->(jitter)
        """,
            node_id=node_id,
            latency_id=ICMP_LATENCY_METRIC_ID,
            jitter_id=ICMP_JITTER_METRIC_ID,
        )


def update_node_metadata(node_id: str, metadata: dict) -> bool:
    """
    Update CI node metadata fields (status, pollingInterval, owner, location_name).
    Used by AI agents for restricted metadata updates.
    """
    driver = get_db()
    # Build SET clause for allowed fields
    set_parts = []
    params = {"id": node_id}
    for key, value in metadata.items():
        set_parts.append(f"n.{key} = ${key}")
        params[key] = value

    if not set_parts:
        return False

    query = "MATCH (n:CI {id: $id}) SET n.updated_at = datetime(), n += $metadata"
    with driver.session() as session:
        session.run(query, id=node_id, metadata=metadata)
        return True


# Metacharacters to strip from search terms before using in regex
_REGEX_METACHAR = re.compile(r"[.*+?^${}()|[\]\\]")


def search_nodes(
    term: str, allowed_locations: list[str] | None = None, is_admin: bool = False
) -> list[dict[str, Any]]:
    """
    Search CI nodes by regex across all CI fields (id, name, label, ip, brand, model,
    serialNumber, firmwareVersion, owner, location_name, status).

    Admin users (is_admin=True) search all matching CIs. Non-admin users are scoped
    to their allowed_locations. If allowed_locations is empty for a non-admin,
    returns empty list immediately.

    Args:
        term: Search term (metacharacters will be stripped)
        allowed_locations: List of location names to scope results (for non-admins)
        is_admin: If True, no location filter is applied

    Returns:
        List of node dicts with id, label, ip, status, brand, model fields
    """
    # Non-admin with no location scopes gets nothing
    if not is_admin and not allowed_locations:
        return []

    driver = get_db()

    # Strip regex metacharacters to prevent injection
    safe_term = _REGEX_METACHAR.sub("", term)

    # All CI fields to search across (from spec: id, name, label, ip, brand, model,
    # serialNumber, firmwareVersion, owner, location_name, status)
    # Note: "name" and "label" both map to n.name in the graph
    searchable_fields = [
        "id",
        "name",
        "ip",
        "brand",
        "model",
        "serialNumber",
        "firmwareVersion",
        "owner",
        "location_name",
        "status",
    ]

    # Build OR'd regex conditions
    conditions = [f"n.{f} =~ $search" for f in searchable_fields]
    where_clause = " OR ".join(conditions)

    query = f"MATCH (n:CI) WHERE {where_clause}"

    # Non-admin: scope to allowed locations
    if not is_admin and allowed_locations:
        query += " AND n.location_name IN $allowed_locations"

    query += " RETURN n LIMIT 50"

    with driver.session() as session:
        result = session.run(
            query, search=f"(?i).*{safe_term}.*", allowed_locations=allowed_locations
        )
        nodes = []
        for r in result:
            n = dict(r["n"])
            nodes.append(
                {
                    "id": n.get("id"),
                    "label": n.get("name"),
                    "ip": n.get("ip"),
                    "status": n.get("status", "OK"),
                    "brand": n.get("brand"),
                    "model": n.get("model"),
                }
            )
        return nodes
