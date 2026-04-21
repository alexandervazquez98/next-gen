from typing import List, Dict, Any, Optional, Set
import json
from neo4j import Driver
from database import get_db
from models.core import Node, Link

def get_nodes(allowed_locations: Optional[List[str]] = None, is_admin: bool = False) -> List[Dict[str, Any]]:
    driver = get_db()
    
    # Base Query
    query = """
        MATCH (n:CI)
    """
    
    params = {}
    
    # Apply Scoping
    if not is_admin:
        if not allowed_locations:
             return []
        
        query += " WHERE n.location_name IN $allowed_locations "
        params["allowed_locations"] = allowed_locations

    query += """
        OPTIONAL MATCH (n)-[:CATEGORIZED_AS]->(c:Category)
        OPTIONAL MATCH (n)-[r:HAS_METRIC]->(m:MetricDef)
        RETURN n, c.name as category, collect({
            name: m.id, 
            protocol: m.protocol,
            status: r.status,
            value: r.last_value,
            last_updated: r.last_updated
        }) as metrics
    """

    with driver.session() as session:
        result = session.run(query, **params)
        nodes = []
        for record in result:
            node = record["n"]
            category = record["category"]
            metrics_data = record["metrics"]
            nodes.append({
                "node": node,
                "category": category,
                "metrics": metrics_data
            })
        return nodes

def upsert_node(node: Node) -> None:
    driver = get_db()
    
    # JSON Serialize SNMP (if dict)
    snmp_str = node.snmp
    if isinstance(node.snmp, dict):
        snmp_str = json.dumps(node.snmp)
    
    owner = node.owner
    loc_name = node.location_name
    brand = node.brand
    model = node.model
    serial = node.serialNumber or ""
    firmware = node.firmwareVersion or ""

    query = f"""
    MERGE (n:CI {{id: $id}})
    SET n.name = $label,
        n.layer = $type,
        n.status = $status,
        n.ip = $ip,
        n.owner = $owner,
        n.location_name = $loc_name,
        n.brand = $brand,
        n.model = $model,
        n.serialNumber = $serial,
        n.firmwareVersion = $firmware,
        n.snmp = $snmp, 
        n.pollingInterval = $polling,
        n.updated_at = datetime()
    """
    
    # Parameterized coordinates to avoid injection
    if node.location and 'lat' in node.location and 'long' in node.location:
        query += ", n.location = point({latitude: $lat, longitude: $lng})"

    query += """
    WITH n
    MERGE (c:Category {name: $type})
    MERGE (n)-[:CATEGORIZED_AS]->(c)
    """
    
    if owner:
        query += """
        WITH n
        MERGE (o:OwnerGroup {name: $owner})
        MERGE (n)-[:OWNED_BY]->(o)
        """

    if brand and model:
        query += """
        WITH n
        MERGE (h:HardwareModel {brand: $brand, model: $model})
        MERGE (n)-[:IS_MODEL]->(h)
        """

    with driver.session() as session:
        session.run(query, 
            id=node.id, label=node.label, type=node.type, status=node.status, 
            ip=node.ip, owner=owner, loc_name=loc_name, brand=brand, model=model,
            serial=serial, firmware=firmware, snmp=snmp_str, polling=node.pollingInterval,
            lat=node.location.get('lat') if node.location else 0,
            lng=node.location.get('long') if node.location else 0
        )

def delete_node(node_id: str) -> None:
    driver = get_db()
    with driver.session() as session:
        session.run("MATCH (n:CI {id: $id}) DETACH DELETE n", id=node_id)

def get_node_usage(node_id: str) -> int:
    driver = get_db()
    with driver.session() as session:
        result = session.run("MATCH (n:CI {id: $id})-[r]-() RETURN count(r) as count", id=node_id)
        count = result.single()["count"]
        return count

def get_valid_owners_and_layers() -> (Set[str], Set[str]):
    driver = get_db()
    with driver.session() as session:
        res_o = session.run("MATCH (o:OwnerGroup) RETURN o.name as name")
        valid_owners = {r["name"] for r in res_o}
        res_c = session.run("MATCH (c:Category) RETURN c.name as name")
        valid_layers = {r["name"] for r in res_c}
    return valid_owners, valid_layers

def bulk_insert_node(
    nid: str, label: str, ntype: str, status: str, ip: str, 
    brand: str, model: str, serial: str, firmware: str,
    lat: float, long: float, polling: int, snmp_str: str,
    metadata: dict, owner: str
):
    driver = get_db()
    with driver.session() as session:
        session.run("""
            MERGE (n:CI {id: $id})
            SET n.name = $label,
                n.layer = $type,
                n.status = $status,
                n.ip = $ip,
                n.brand = $brand,
                n.model = $model,
                n.serialNumber = $serial,
                n.firmwareVersion = $firmware,
                n.location = point({latitude: $lat, longitude: $long}),
                n.location_name = $loc_name,
                n.pollingInterval = $polling,
                n.snmp = $snmp
            SET n += $metadata
            
            WITH n
            MERGE (c:Category {name: $type})
            MERGE (n)-[:CATEGORIZED_AS]->(cat)
            
            WITH n
            WHERE $owner <> ''
            MERGE (o:OwnerGroup {name: $owner})
            MERGE (n)-[:OWNED_BY]->(o)
        """, 
        id=nid, label=label, type=ntype, status=status, ip=ip, 
        brand=brand, model=model, serial=serial, firmware=firmware,
        lat=lat, long=long, loc_name=metadata.get('location_name'),
        polling=polling, snmp=snmp_str,
        metadata=metadata, owner=owner)

# --- Link Operations ---

def get_links(allowed_locations: Optional[List[str]] = None, is_admin: bool = False) -> List[Dict[str, Any]]:
    driver = get_db()
    with driver.session() as session:
        query = """
            MATCH (a)-[r]->(b)
            WHERE (a:CI OR a:MetricDef) AND (b:CI OR b:MetricDef) 
              AND NOT type(r) = 'CATEGORIZED_AS'
              AND NOT type(r) = 'OWNED_BY'
              AND NOT type(r) = 'IS_MODEL'
              AND a.id IS NOT NULL AND b.id IS NOT NULL
        """
        
        params = {}
        if not is_admin:
            if not allowed_locations: return []
            query += " AND (a.location_name IN $allowed_locations OR b.location_name IN $allowed_locations) "
            params["allowed_locations"] = allowed_locations

        query += """
            RETURN 
                a.id as source, 
                COALESCE(a.display_name, a.name, a.label, a.id) as source_label,
                b.id as target, 
                COALESCE(b.display_name, b.name, b.label, b.id) as target_label,
                type(r) as rel
        """
        result = session.run(query, **params)
        return [{
            "source": record["source"],
            "source_label": record["source_label"],
            "target": record["target"],
            "target_label": record["target_label"],
            "relationship": record["rel"]
        } for record in result if record["source"] and record["target"]]

def create_link(source: str, target: str, relationship: str) -> None:
    driver = get_db()
    rel_type = relationship.upper().replace(" ", "_")
    with driver.session() as session:
        session.run(f"""
            MATCH (a), (b) 
            WHERE a.id = $source AND b.id = $target
            MERGE (a)-[r:{rel_type}]->(b)
        """, source=source, target=target)

def delete_link(source: str, target: str, relationship: str) -> None:
    driver = get_db()
    rel_type = relationship.upper().replace(" ", "_")
    with driver.session() as session:
        session.run(f"MATCH (a {{id: $source}})-[r:{rel_type}]->(b {{id: $target}}) DELETE r",
                    source=source, target=target)

def link_metric_to_node(node_id: str, metric_id: str, warning: float = None, critical: float = None):
    driver = get_db()
    with driver.session() as session:
        session.run("""
            MATCH (n:CI {id: $nid})
            MATCH (m:MetricDef {id: $mid})
            MERGE (n)-[r:HAS_METRIC]->(m)
            SET r.warning_threshold = $warning,
                r.critical_threshold = $critical
        """, nid=node_id, mid=metric_id, warning=warning, critical=critical)

def get_filtered_graph_data(layer: str = None, location: str = None, owner: str = None, allowed_locations: List[str] = None, is_admin: bool = False) -> (List[Dict[str, Any]], List[Dict[str, Any]]):
    driver = get_db()
    
    where_clauses = []
    params = {}
    if layer:
        where_clauses.append("n.layer = $layer")
        params["layer"] = layer
    if location:
        where_clauses.append("n.location_name = $location")
        params["location"] = location
    if owner:
        where_clauses.append("n.owner = $owner")
        params["owner"] = owner
    
    if not is_admin:
        if not allowed_locations: return [], []
        where_clauses.append("n.location_name IN $allowed_locations")
        params["allowed_locations"] = allowed_locations

    where_str = ""
    if where_clauses:
        where_str = " WHERE " + " AND ".join(where_clauses)

    with driver.session() as session:
        # Fetch nodes
        nodes_query = f"MATCH (n:CI){where_str} RETURN n, labels(n) as labels"
        nodes_result = session.run(nodes_query, **params)
        nodes = [dict(record["n"], _labels=record["labels"]) for record in nodes_result]

        # Fetch relationships (ensure both ends match filters and scoping)
        links_query = f"MATCH (a:CI)-[r]->(b:CI){where_str.replace('n.', 'a.')} AND {where_str.replace('n.', 'b.')} RETURN a, r, b"
        links_result = session.run(links_query, **params)
        links = [{
            "source_node": dict(record["a"]),
            "target_node": dict(record["b"]),
            "type": record["r"].type
        } for record in links_result]
                
        return nodes, links
