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
    
    # Pre-process location point
    loc_point = "null"
    if node.location and 'lat' in node.location and 'long' in node.location:
        loc_point = f"point({{latitude: {node.location['lat']}, longitude: {node.location['long']}}})"
    
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
    if loc_point != "null":
        query += f", n.location = {loc_point}"
    
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
            serial=serial, firmware=firmware, snmp=snmp_str, polling=node.pollingInterval
        )

def create_default_ping_metric(node_id: str, label: str):
    driver = get_db()
    ping_criteria = json.dumps({"names": [label]})
    ping_id = f"PING-{label}"
    with driver.session() as session:
        session.run("""
            MERGE (m:MetricDef {id: $mid})
            SET m.protocol = 'ICMP',
            m.description = 'Monitoreo via ping ICMP',
            m.applicable_to = $criteria,
            m.warning = 0,
            m.critical = 0,
            m.oid = 'ICMP' 
        """, mid=ping_id, criteria=ping_criteria)

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
                n.pollingInterval = $polling,
                n.snmp = $snmp
            SET n += $metadata
            
            WITH n
            MERGE (c:Category {name: $type})
            MERGE (n)-[:CATEGORIZED_AS]->(c)
            
            WITH n
            WHERE $owner <> ''
            MATCH (o:OwnerGroup {name: $owner})
            MERGE (n)-[:OWNED_BY]->(o)
        """, 
        id=nid, label=label, type=ntype, status=status, ip=ip, 
        brand=brand, model=model, serial=serial, firmware=firmware,
        lat=lat, long=long, polling=polling, snmp=snmp_str,
        metadata=metadata, owner=owner)

def get_template_data() -> (List[str], List[str]):
    driver = get_db()
    with driver.session() as session:
        res_o = session.run("MATCH (o:OwnerGroup) RETURN o.name as name ORDER BY o.name")
        owners_list = [record["name"] for record in res_o]
        res_c = session.run("MATCH (c:Category) RETURN c.name as name ORDER BY c.name")
        layers_list = [record["name"] for record in res_c]
    return owners_list, layers_list

# --- Link Operations ---

def get_links() -> List[Dict[str, Any]]:
    driver = get_db()
    with driver.session() as session:
        query = """
            MATCH (a)-[r]->(b)
            WHERE (a:CI OR a:Metric) AND (b:CI OR b:Metric) 
              AND NOT type(r) = 'CATEGORIZED_AS'
              AND NOT type(r) = 'OWNED_BY'
              AND a.id IS NOT NULL AND b.id IS NOT NULL
            RETURN 
                a.id as source, 
                COALESCE(a.display_name, a.name, a.label, a.id) as source_label,
                b.id as target, 
                COALESCE(b.display_name, b.name, b.label, b.id) as target_label,
                type(r) as rel
        """
        result = session.run(query)
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
        session.run(f"MATCH (a:CI {{id: $source}})-[r:{rel_type}]->(b:CI {{id: $target}}) DELETE r", 
                    source=source, target=target)

def get_full_graph_data() -> (List[Dict[str, Any]], List[Dict[str, Any]]):
    driver = get_db()
    with driver.session() as session:
        # Fetch all nodes with their labels
        nodes_result = session.run("MATCH (n) RETURN n, labels(n) as labels")
        nodes = []
        for record in nodes_result:
            node = record["n"]
            labels = record["labels"]
            
            # TODO: Move Logic for type determination/label text to Service or simplify here?
            # Keeping it raw here is better, let Service format it? 
            # Or keep it here to encapsulate neo4j specifics (like labels object).
            # I will return raw nodes and relationships, let service process.
            
            # Actually, extracting properties to a dict is safer here
            node_props = dict(node)
            node_props["_labels"] = labels
            # Fallback ID handled in service? No, let's ensure ID here.
            nodes.append(node_props)

        # Fetch all relationships
        links_result = session.run("MATCH (a)-[r]->(b) RETURN a, r, b")
        links = []
        for record in links_result:
            # We need IDs to link them.
            # Using element ID might be safer if custom ID is missing, but sticking to logic
            links.append({
                "source_node": dict(record["a"]),
                "target_node": dict(record["b"]),
                "type": record["r"].type
            })
                
        return nodes, links
