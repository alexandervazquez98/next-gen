from typing import List, Dict, Any, Optional, Set
import json
from neo4j import Driver
from database import get_db
from models.core import Node, Link

def get_nodes(allowed_locations: Optional[List[str]] = None, is_admin: bool = False) -> List[Dict[str, Any]]:
    driver = get_db()
    query = "MATCH (n:CI)"
    params = {}
    if not is_admin:
        if not allowed_locations: return []
        query += " WHERE n.location_name IN $allowed_locations "
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
        result = session.run("MATCH (n:CI {id: $id})-[r]-() RETURN count(r) as count", id=node_id).single()
        return result["count"] if result else 0

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
    rel = relationship.upper().replace(" ", "_")
    with driver.session() as session:
        session.run(f"MATCH (a), (b) WHERE a.id = $s AND b.id = $t MERGE (a)-[r:{rel}]->(b)", s=source, t=target)

def delete_link(source, target, relationship):
    driver = get_db()
    rel = relationship.upper().replace(" ", "_")
    with driver.session() as session:
        session.run(f"MATCH (a {{id: $s}})-[r:{rel}]->(b {{id: $t}}) DELETE r", s=source, t=target)

def _build_where_v2(alias, filter_obj, is_admin, allowed_locations):
    where, params = [], {}
    if filter_obj.get("ids"):
        where.append(f"{alias}.id IN ${alias}_ids")
        params[f"{alias}_ids"] = filter_obj["ids"]
    elif filter_obj.get("layer"):
        where.append(f"{alias}.layer = ${alias}_layer")
        params[f"{alias}_layer"] = filter_obj["layer"]
    elif filter_obj.get("searchTerm"):
        where.append(f"({alias}.name =~ ${alias}_search OR {alias}.ip =~ ${alias}_search OR {alias}.location_name =~ ${alias}_search)")
        params[f"{alias}_search"] = f"(?i).*{filter_obj['searchTerm']}.*"
    if not is_admin and allowed_locations and filter_obj.get("label", "CI") == "CI":
        where.append(f"{alias}.location_name IN ${alias}_allowed")
        params[f"{alias}_allowed"] = allowed_locations
    return ("(" + " AND ".join(where) + ")") if where else "true", params

def count_potential_links(source_filter, target_filter, allowed_locations=None, is_admin=False):
    driver = get_db()
    w_a, p_a = _build_where_v2("a", source_filter, is_admin, allowed_locations)
    w_b, p_b = _build_where_v2("b", target_filter, is_admin, allowed_locations)
    query = f"MATCH (a:{source_filter.get('label','CI')}), (b:{target_filter.get('label','CI')}) WHERE {w_a} AND {w_b} RETURN count(*) as total, collect(a.name)[0..5] as s, collect(b.name)[0..5] as t"
    with driver.session() as session:
        r = session.run(query, **{**p_a, **p_b}).single()
        return {"total": r["total"], "source_samples": r["s"], "target_samples": r["t"]}

def execute_mass_links(source_filter, target_filter, relationship, allowed_locations=None, is_admin=False):
    driver = get_db()
    rel = relationship.upper().replace(" ", "_")
    w_a, p_a = _build_where_v2("a", source_filter, is_admin, allowed_locations)
    w_b, p_b = _build_where_v2("b", target_filter, is_admin, allowed_locations)
    query = f"MATCH (a:{source_filter.get('label','CI')}), (b:{target_filter.get('label','CI')}) WHERE {w_a} AND {w_b} AND a.id <> b.id MERGE (a)-[r:{rel}]->(b) RETURN count(r) as total"
    with driver.session() as session:
        res = session.run(query, **{**p_a, **p_b})
        rec = res.single()
        stats = res.consume()
        return {"total": rec["total"], "created": stats.counters.relationships_created, "verified": rec["total"] - stats.counters.relationships_created}

def execute_mass_delete(source_filter, target_filter, relationship, allowed_locations=None, is_admin=False):
    driver = get_db()
    rel = relationship.upper().replace(" ", "_")
    w_a, p_a = _build_where_v2("a", source_filter, is_admin, allowed_locations)
    w_b, p_b = _build_where_v2("b", target_filter, is_admin, allowed_locations)
    query = f"MATCH (a:{source_filter.get('label','CI')}), (b:{target_filter.get('label','CI')}) WHERE {w_a} AND {w_b} MATCH (a)-[r:{rel}]->(b) DELETE r RETURN count(r) as total"
    with driver.session() as session:
        r = session.run(query, **{**p_a, **p_b}).single()
        return {"deleted": r["total"]}

def execute_mass_update(source_filter, target_filter, old_rel, new_rel, allowed_locations=None, is_admin=False):
    driver = get_db()
    o_rel, n_rel = old_rel.upper().replace(" ","_"), new_rel.upper().replace(" ","_")
    w_a, p_a = _build_where_v2("a", source_filter, is_admin, allowed_locations)
    w_b, p_b = _build_where_v2("b", target_filter, is_admin, allowed_locations)
    query = f"MATCH (a:{source_filter.get('label','CI')}), (b:{target_filter.get('label','CI')}) WHERE {w_a} AND {w_b} MATCH (a)-[o:{o_rel}]->(b) DELETE o MERGE (a)-[n:{n_rel}]->(b) RETURN count(n) as total"
    with driver.session() as session:
        r = session.run(query, **{**p_a, **p_b}).single()
        return {"updated": r["total"]}

def get_filtered_graph_data(layer=None, location=None, owner=None, allowed_locations=None, is_admin=False):
    driver = get_db()
    where, params = [], {}
    if layer: where.append("n.layer = $layer"); params["layer"] = layer
    if location: where.append("n.location_name = $location"); params["location"] = location
    if owner: where.append("n.owner = $owner"); params["owner"] = owner
    if not is_admin and allowed_locations: where.append("n.location_name IN $allowed_locations"); params["allowed_locations"] = allowed_locations
    w_str = (" WHERE " + " AND ".join(where)) if where else ""
    with driver.session() as session:
        nodes = [dict(r["n"], _labels=r["labels"]) for r in session.run(f"MATCH (n:CI){w_str} RETURN n, labels(n) as labels", **params)]
        l_where = (" WHERE " + " AND ".join([c.replace("n.", "a.") for c in where] + [c.replace("n.", "b.") for c in where])) if where else ""
        links = [{"source_node": dict(r["a"]), "target_node": dict(r["b"]), "type": r["r"].type} for r in session.run(f"MATCH (a:CI)-[r]->(b:CI){l_where} RETURN a, r, b", **params)]
        return nodes, links
