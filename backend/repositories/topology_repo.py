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

def get_template_data() -> (List[str], List[str]):
    driver = get_db()
    with driver.session() as session:
        res_o = session.run("MATCH (o:OwnerGroup) RETURN o.name as name ORDER BY o.name")
        owners_list = [record["name"] for record in res_o]
        res_c = session.run("MATCH (c:Category) RETURN c.name as name ORDER BY c.name")
        layers_list = [record["name"] for record in res_c]
    return owners_list, layers_list

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

def _build_mass_where(source_filter: dict, target_filter: dict, allowed_locations: Optional[List[str]] = None, is_admin: bool = False):
    """Internal helper to build WHERE clauses for mass operations."""
    src_clauses = []
    target_clauses = []
    params = {}
    
    # Source Set
    if source_filter.get("layer"):
        src_clauses.append("a.layer = $src_layer")
        params["src_layer"] = source_filter["layer"]
    if source_filter.get("location"):
        src_clauses.append("a.location_name = $src_location")
        params["src_location"] = source_filter["location"]
    if source_filter.get("name"):
        src_clauses.append("a.name = $src_name")
        params["src_name"] = source_filter["name"]
    
    # Forceful Global Scoping for Source
    if not is_admin:
        src_clauses.append("a.location_name IN $src_allowed")
        params["src_allowed"] = allowed_locations or []
        
    # Target Set
    if target_filter.get("layer"):
        target_clauses.append("b.layer = $target_layer")
        params["target_layer"] = target_filter["layer"]
    if target_filter.get("location"):
        target_clauses.append("b.location_name = $target_location")
        params["target_location"] = target_filter["location"]
    if target_filter.get("name"):
        target_clauses.append("b.name = $target_name")
        params["target_name"] = target_filter["name"]

    # Forceful Global Scoping for Target
    if not is_admin:
        target_clauses.append("b.location_name IN $target_allowed")
        params["target_allowed"] = allowed_locations or []
        
    src_where = ""
    if src_clauses:
        src_where = " WHERE " + " AND ".join(src_clauses)
        
    target_where = ""
    if target_clauses:
        target_where = " WHERE " + " AND ".join(target_clauses)
        
    return src_where, target_where, params

def count_potential_links(source_filter: dict, target_filter: dict, allowed_locations: Optional[List[str]] = None, is_admin: bool = False) -> Dict[str, Any]:
    """Simulates the mass link operation by returning the potential link count and samples."""
    driver = get_db()
    src_where, target_where, params = _build_mass_where(source_filter, target_filter, allowed_locations, is_admin)
    
    # Optimized query structure: Filter a, then filter b, then return Cartesian count + samples
    query = f"""
    MATCH (a:CI){src_where}
    WITH collect(a) as source_nodes
    MATCH (b:CI){target_where}
    WITH source_nodes, collect(b) as target_nodes
    UNWIND source_nodes as a
    UNWIND target_nodes as b
    WITH a, b WHERE a.id <> b.id
    RETURN count(*) as total, 
           collect(DISTINCT a.name)[..5] as source_samples,
           collect(DISTINCT b.name)[..5] as target_samples
    """
    
    with driver.session() as session:
        result = session.run(query, **params)
        record = result.single()
        if not record:
             return {"total": 0, "source_samples": [], "target_samples": []}
        return {
            "total": record["total"],
            "source_samples": record["source_samples"],
            "target_samples": record["target_samples"]
        }

def execute_mass_links(source_filter: dict, target_filter: dict, relationship: str, allowed_locations: Optional[List[str]] = None, is_admin: bool = False):
    """Executes a Cartesian MERGE between two sets of nodes."""
    driver = get_db()
    src_where, target_where, params = _build_mass_where(source_filter, target_filter, allowed_locations, is_admin)
    
    rel_type = relationship.upper().replace(" ", "_")
    if not all(c.isalnum() or c == '_' for c in rel_type):
        raise ValueError("Invalid relationship type")

    # Early filtering and prevention of self-links
    query = f"""
    MATCH (a:CI){src_where}
    MATCH (b:CI){target_where}
    WHERE a.id <> b.id
    MERGE (a)-[r:{rel_type}]->(b) 
    RETURN count(r) as total
    """
    
    with driver.session() as session:
        result = session.run(query, **params)
        summary = result.consume()
        total = result.single()["total"]
        created = summary.counters.relationships_created
        verified = total - created
        return {
            "total": total,
            "created": created,
            "verified": verified
        }

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

        # Fetch relationships
        links_query = f"MATCH (a:CI)-[r]->(b:CI){where_str.replace('n.', 'a.')} AND {where_str.replace('n.', 'b.')} RETURN a, r, b"
        links_result = session.run(links_query, **params)
        links = [{
            "source_node": dict(record["a"]),
            "target_node": dict(record["b"]),
            "type": record["r"].type
        } for record in links_result]
                
        return nodes, links
