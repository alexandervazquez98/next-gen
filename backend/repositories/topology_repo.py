from typing import List, Dict, Any, Optional, Set
import json
from neo4j import Driver
from database import get_db
from models.core import Node, Link

def get_nodes(allowed_locations: Optional[List[str]] = None, is_admin: bool = False) -> List[Dict[str, Any]]:
    driver = get_db()
    query = "MATCH (n:CI) WHERE n.location IS NOT NULL AND n.location.latitude IS NOT NULL AND n.location.longitude IS NOT NULL"
    params = {}
    if not is_admin:
        if not allowed_locations: return []
        query += " AND n.location_name IN $allowed_locations "
        params["allowed_locations"] = allowed_locations
    query += """
        OPTIONAL MATCH (n)-[:CATEGORIZED_AS]->(c:Category)
        OPTIONAL MATCH (n)-[r:HAS_METRIC]->(m:MetricDef)
        RETURN n, c.name as category, collect({
            name: m.id, protocol: m.protocol, status: r.status, value: r.last_value, last_updated: r.last_updated
        }) as metrics
    """
    with driver.session() as session:
        result = session.run(query, **params)
        return [{"node": r["n"], "category": r["category"], "metrics": r["metrics"]} for r in result]

def upsert_node(node: Node) -> None:
    driver = get_db()
    snmp_str = json.dumps(node.snmp) if isinstance(node.snmp, dict) else node.snmp
    query = """
    MERGE (n:CI {id: $id})
    SET n.name = $label, n.layer = $type, n.status = $status, n.ip = $ip, n.owner = $owner,
        n.location_name = $loc_name, n.brand = $brand, n.model = $model, n.serialNumber = $serial,
        n.firmwareVersion = $firmware, n.snmp = $snmp, n.pollingInterval = $polling, n.updated_at = datetime()
    """
    if node.location and 'lat' in node.location and 'long' in node.location:
        query += ", n.location = point({latitude: $lat, longitude: $lng})"
    query += "\nWITH n MERGE (c:Category {name: $type}) MERGE (n)-[:CATEGORIZED_AS]->(c)"
    if node.owner:
        query += "\nWITH n MERGE (o:OwnerGroup {name: $owner}) MERGE (n)-[:OWNED_BY]->(o)"
    if node.brand and node.model:
        query += "\nWITH n MERGE (h:HardwareModel {brand: $brand, model: $model}) MERGE (n)-[:IS_MODEL]->(h)"
    with driver.session() as session:
        session.run(query, id=node.id, label=node.label, type=node.type, status=node.status, ip=node.ip, 
                    owner=node.owner, loc_name=node.location_name, brand=node.brand, model=node.model,
                    serial=node.serialNumber or "", firmware=node.firmwareVersion or "", snmp=snmp_str, 
                    polling=node.pollingInterval, lat=node.location.get('lat') if node.location else 0,
                    lng=node.location.get('long') if node.location else 0)

def delete_node(node_id: str) -> None:
    driver = get_db()
    with driver.session() as session:
        session.run("MATCH (n:CI {id: $id}) DETACH DELETE n", id=node_id)

def get_node_usage(node_id: str) -> int:
    driver = get_db()
    with driver.session() as session:
        res = session.run("MATCH (n:CI {id: $id})-[r]-() RETURN count(r) as count", id=node_id).single()
        return res["count"] if res else 0

def get_valid_owners_and_layers() -> (Set[str], Set[str]):
    driver = get_db()
    with driver.session() as session:
        res_o = session.run("MATCH (o:OwnerGroup) RETURN o.name as name")
        res_c = session.run("MATCH (c:Category) RETURN c.name as name")
        return {r["name"] for r in res_o}, {r["name"] for r in res_c}

def bulk_insert_node(nid, label, ntype, status, ip, brand, model, serial, firmware, lat, long, polling, snmp_str, metadata, owner):
    driver = get_db()
    with driver.session() as session:
        session.run("""
            MERGE (n:CI {id: $id})
            SET n.name = $label, n.layer = $type, n.status = $status, n.ip = $ip, n.brand = $brand, n.model = $model,
                n.serialNumber = $serial, n.firmwareVersion = $firmware, n.location = point({latitude: $lat, longitude: $long}),
                n.location_name = $loc_name, n.pollingInterval = $polling, n.snmp = $snmp
            SET n += $metadata
            WITH n MERGE (c:Category {name: $type}) MERGE (n)-[:CATEGORIZED_AS]->(c)
            WITH n WHERE $owner <> '' MERGE (o:OwnerGroup {name: $owner}) MERGE (n)-[:OWNED_BY]->(o)
        """, id=nid, label=label, type=ntype, status=status, ip=ip, brand=brand, model=model, serial=serial, firmware=firmware,
        lat=lat, long=long, loc_name=metadata.get('location_name'), polling=polling, snmp=snmp_str, metadata=metadata, owner=owner)

# Valid relationship types for injection prevention
_VALID_RELATIONSHIPS = frozenset({"CONNECTS_TO", "HOSTED_ON", "DEPENDS_ON", "MANAGES", "USES", "PROVIDES"})

def _validate_relationship(rel: str) -> str:
    """Validate and sanitize relationship type. Raises ValueError if invalid."""
    clean = rel.upper().replace(" ", "_")
    if clean not in _VALID_RELATIONSHIPS:
        raise ValueError(f"Invalid relationship type: {rel}")
    return clean

# Valid node labels for injection prevention
_VALID_NODE_LABELS = frozenset({"CI", "MetricDef", "Category", "OwnerGroup", "HardwareModel", "User"})

def _validate_node_label(label: str) -> str:
    """Validate node label. Raises ValueError if invalid."""
    if label not in _VALID_NODE_LABELS:
        raise ValueError(f"Invalid node label: {label}")
    return label

def get_template_data():
    driver = get_db()
    with driver.session() as session:
        res_o = session.run("MATCH (o:OwnerGroup) RETURN o.name as name ORDER BY o.name")
        res_c = session.run("MATCH (c:Category) RETURN c.name as name ORDER BY c.name")
        return [r["name"] for r in res_o], [r["name"] for r in res_c]

def get_links(allowed_locations=None, is_admin=False):
    driver = get_db()
    query = """
        MATCH (a)-[r]->(b)
        WHERE (a:CI OR a:MetricDef) AND (b:CI OR b:MetricDef)
          AND NOT type(r) IN ['CATEGORIZED_AS', 'OWNED_BY', 'IS_MODEL']
          AND a.id IS NOT NULL AND b.id IS NOT NULL
    """
    params = {}
    if not is_admin:
        if not allowed_locations: return []
        query += " AND (a.location_name IN $allowed_locations OR b.location_name IN $allowed_locations) "
        params["allowed_locations"] = allowed_locations
    query += " RETURN a.id as s, COALESCE(a.name, a.id) as sl, b.id as t, COALESCE(b.name, b.id) as tl, type(r) as rel"
    with driver.session() as session:
        return [{"source": r["s"], "source_label": r["sl"], "target": r["t"], "target_label": r["tl"], "relationship": r["rel"]} for r in session.run(query, **params)]

def create_link(source, target, relationship):
    driver = get_db()
    rel = _validate_relationship(relationship)
    with driver.session() as session:
        session.run(f"MATCH (a {{id: $s}}), (b {{id: $t}}) WHERE a.id = $s AND b.id = $t MERGE (a)-[r:{rel}]->(b)", s=source, t=target)

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
        where.append(f"n.id IN $ids")
        params["ids"] = filter_obj["ids"]
    # Priority 2: Singular ID (from dropdowns)
    elif filter_obj.get("id"):
        where.append(f"n.id = $id")
        params["id"] = filter_obj["id"]
    # Priority 3: Metadata Filters (Layer, Brand, Model)
    else:
        if filter_obj.get("layer"):
            where.append(f"n.layer = $layer")
            params["layer"] = filter_obj["layer"]
        if filter_obj.get("brand"):
            where.append(f"n.brand = $brand")
            params["brand"] = filter_obj["brand"]
        if filter_obj.get("model"):
            where.append(f"n.model = $model")
            params["model"] = filter_obj["model"]
        if filter_obj.get("searchTerm"):
            where.append(f"(n.name =~ $search OR n.ip =~ $search OR n.location_name =~ $search)")
            params["search"] = f"(?i).*{filter_obj['searchTerm']}.*"
            
    if not is_admin and allowed_locations and label == "CI":
        where.append(f"n.location_name IN $allowed")
        params["allowed"] = allowed_locations
    
    q = f"MATCH (n:{_validate_node_label(label)})"
    if where: q += " WHERE " + " AND ".join(where)
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
        "target_samples": [n["name"] for n in tgt_nodes[:5]]
    }

def execute_mass_links(source_filter, target_filter, relationship, allowed_locations=None, is_admin=False):
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
        return {"total": total, "created": stats.counters.relationships_created, "verified": total - stats.counters.relationships_created}

def execute_mass_delete(source_filter, target_filter, relationship, allowed_locations=None, is_admin=False):
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

def execute_mass_update(source_filter, target_filter, old_rel, new_rel, allowed_locations=None, is_admin=False):
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

def get_filtered_graph_data(layer=None, location=None, owner=None, allowed_locations=None, is_admin=False):
    driver = get_db()
    where, params = [], {}
    if layer: where.append("n.layer = $layer"); params["layer"] = layer
    if location: where.append("n.location_name = $location"); params["location"] = location
    if owner: where.append("n.owner = $owner"); params["owner"] = owner
    if not is_admin and allowed_locations: where.append("n.location_name IN $allowed_locations"); params["allowed_locations"] = allowed_locations
    w_str = (" WHERE " + " AND ".join(where)) if where else ""
    with driver.session() as session:
        # Build the query: only CIs with valid location coordinates
        node_query = f"""
            MATCH (n:CI)
            WHERE n.location IS NOT NULL AND n.location.latitude IS NOT NULL AND n.location.longitude IS NOT NULL
            {w_str}
            OPTIONAL MATCH (n)-[r:HAS_METRIC]->(m:MetricDef)
            RETURN n, 
                   n.location.latitude as lat, 
                   n.location.longitude as lng, 
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
            if "n." in cond:
                # Replace n. prefix with a. and b. for the link query
                link_filters.append(cond.replace("n.", "a."))
                link_filters.append(cond.replace("n.", "b."))
            # Extract security filter to apply separately
            if "allowed_locations" in cond:
                # Transform to apply to both endpoints a and b
                security_filter = cond.replace("n.", "a.") + " OR " + cond.replace("n.", "b.")

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
        links = [{"source_node": dict(r["a"]), "target_node": dict(r["b"]), "type": r["r"].type} for r in session.run(f"MATCH (a:CI)-[r]->(b:CI){l_where} RETURN a, r, b", **params)]
        return nodes, links
