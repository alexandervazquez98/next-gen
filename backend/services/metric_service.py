import json
import uuid
import logging
from typing import List, Dict, Any, Optional
from database import get_db
from models.core import MetricDef

logger = logging.getLogger(__name__)

def get_metrics() -> List[Dict[str, Any]]:
    """
    Fetch all Metric Definitions.
    Includes details like OID, thresholds, unit, and applicable criteria.
    """
    driver = get_db()
    with driver.session() as session:
        result = session.run("MATCH (m:MetricDef) RETURN m")
        metrics = []
        for record in result:
            m = record["m"]
            criteria = {}
            if m.get("applicable_to"):
                try: criteria = json.loads(m.get("applicable_to"))
                except: pass

            metrics.append({
                "id": m.get("id"),
                "protocol": m.get("protocol"),
                "warning": m.get("warning"),
                "critical": m.get("critical"),
                "oid": m.get("oid"),
                "dataType": m.get("dataType"),
                "unit": m.get("unit"),
                "description": m.get("description"),
                "operator": m.get("operator", ">="),
                "criticality": m.get("criticality", 1),
                "applicable_to": criteria,
                "polling_interval": m.get("polling_interval", 60)
            })
        return metrics

def create_metric(metric: MetricDef) -> Dict[str, str]:
    """
    Define a new Metric for monitoring.
    """
    driver = get_db()
    criteria_str = json.dumps(metric.applicable_to) if metric.applicable_to else "{}"
    
    with driver.session() as session:
        session.run("""
            MERGE (m:MetricDef {id: $id})
            SET m.protocol = $prot, m.warning = $warn, m.critical = $crit,
                m.oid = $oid, m.dataType = $dtype, m.unit = $unit,
                m.description = $desc, m.applicable_to = $criteria,
                m.operator = $operator, m.criticality = $criticality,
                m.polling_interval = $polling_interval
        """, id=metric.id, prot=metric.protocol, warn=metric.warning, 
             crit=metric.critical, oid=metric.oid, dtype=metric.dataType,
             unit=metric.unit, desc=metric.description, criteria=criteria_str,
             operator=metric.operator or ">=", criticality=metric.criticality or 1,
             polling_interval=metric.polling_interval or 60)
    return {"message": "Metric defined"}

def delete_metric(metric_id: str, force: bool = False) -> Dict[str, Any]:
    """
    Delete a Metric Definition. 
    If force=True, removes all assignments and related events.
    """
    driver = get_db()
    usage = get_metric_usage(metric_id)
    
    if usage["node_count"] > 0 and not force:
        # Prevent accidental deletion of metrics in use
        return {
            "error": "IN_USE", 
            "message": f"Metric is currently assigned to {usage['node_count']} nodes. Use force=True to delete anyway.",
            "usage": usage
        }

    with driver.session() as session:
        if force:
            # 1. Remove HAS_METRIC relationships across the whole graph
            session.run("MATCH (:CI)-[r:HAS_METRIC]->(m:MetricDef {id: $id}) DELETE r", id=metric_id)
            # 2. Delete events associated with this metric (optional but recommended for cleanup)
            session.run("MATCH (e:Event)-[:TRIGGERED_BY]->(m:MetricDef {id: $id}) DETACH DELETE e", id=metric_id)
        
        # 3. Finally delete the metric definition itself
        session.run("MATCH (m:MetricDef {id: $id}) DETACH DELETE m", id=metric_id)
        
    return {"message": "Metric deleted", "force_applied": force, "impact": usage}

def get_metric_usage(metric_id: str) -> Dict[str, Any]:
    """
    Calculate the impact of a metric: how many nodes use it and how many active events it has.
    """
    driver = get_db()
    with driver.session() as session:
        result = session.run("""
            MATCH (m:MetricDef {id: $id})
            OPTIONAL MATCH (n:CI)-[:HAS_METRIC]->(m)
            OPTIONAL MATCH (e:Event)-[:TRIGGERED_BY]->(m)
            RETURN count(DISTINCT n) as node_count, count(DISTINCT e) as event_count
        """, id=metric_id).single()
        
        if not result:
            return {"node_count": 0, "event_count": 0}
            
        return {
            "node_count": result["node_count"],
            "event_count": result["event_count"]
        }

def get_applicable_metrics(node_id: str, metrics_catalog: Optional[List[Dict[str, Any]]] = None, session=None) -> List[Dict[str, Any]]:
    """
    Get all eligible metrics for a specific Node based on its properties (Brand, Model, Layer).
    """
    if session:
        return _get_applicable_metrics_impl(node_id, metrics_catalog, session)
    
    driver = get_db()
    with driver.session() as session:
        return _get_applicable_metrics_impl(node_id, metrics_catalog, session)

def _get_applicable_metrics_impl(node_id: str, metrics_catalog: Optional[List[Dict[str, Any]]], session) -> List[Dict[str, Any]]:
    # 1. Fetch Node
    result = session.run("MATCH (n:CI {id: $id}) RETURN n", id=node_id)
    record = result.single()
    if not record:
        return []
    
    node = record["n"]
    brand = (node.get("brand") or "").strip().lower()
    model = (node.get("model") or "").strip().lower()
    layer = (node.get("layer") or "").strip().lower()
    node_name = (node.get("name") or "").strip().lower()
    node_ci_id = (node.get("id") or "").strip().lower()
    
    # 2. Use Catalog if provided, else Fetch All Metric Definitions
    if metrics_catalog is not None:
        metrics_defs = metrics_catalog
    else:
        res_metrics = session.run("MATCH (m:MetricDef) RETURN m")
        metrics_defs = []
        for rec in res_metrics:
            m = rec["m"]
            criteria_json = m.get("applicable_to")
            metrics_defs.append({
                "id": m.get("id"),
                "description": m.get("description"),
                "unit": m.get("unit"),
                "warning": m.get("warning"),
                "critical": m.get("critical"),
                "applicable_to_json": criteria_json
            })
    
    applicable_metrics = []
    
    # 3. Filter Metrics based on criteria (AND logic)
    for m in metrics_defs:
        criteria_json = m.get("applicable_to_json") if metrics_catalog is None else json.dumps(m.get("applicable_to"))
        if not criteria_json:
            continue
            
        try:
            criteria = json.loads(criteria_json) if isinstance(criteria_json, str) else criteria_json
            
            # CANDADO DE SEGURIDAD: Si todos los campos de filtro están vacíos, la métrica NO aplica a nadie.
            # Esto evita la asignación masiva accidental al crear una métrica sin reglas.
            has_filters = any([
                criteria.get("names") and len(criteria["names"]) > 0,
                criteria.get("brands") and len(criteria["brands"]) > 0,
                criteria.get("models") and len(criteria["models"]) > 0,
                criteria.get("layers") and len(criteria["layers"]) > 0
            ])
            
            if not has_filters:
                continue

            match = True
            
            # Check direct Name/ID match
            req_names = [n.strip().lower() for n in criteria.get("names", [])]
            if req_names and not (node_name in req_names or node_ci_id in req_names):
                match = False

            # Check Category (Brand)
            req_brands = [b.strip().lower() for b in criteria.get("brands", [])]
            if req_brands and brand not in req_brands:
                match = False
                
            # Check Model
            req_models = [m.strip().lower() for m in criteria.get("models", [])]
            if req_models and model not in req_models:
                match = False
                
            # Check Network Layer
            req_layers = [l.strip().lower() for l in criteria.get("layers", [])]
            if req_layers and layer not in req_layers:
                match = False

            if match:
                applicable_metrics.append({
                    "id": m.get("id"),
                    "name": m.get("id"),
                    "description": m.get("description"),
                    "unit": m.get("unit"),
                    "warning": m.get("warning"),
                    "critical": m.get("critical")
                })
        except Exception as e:
            logger.error(f"Error parsing metric criteria for {m.get('id')}: {e}")
            pass
            
    return applicable_metrics

def reconcile_node_metrics(node: Dict[str, Any], metrics_catalog: Optional[List[Dict[str, Any]]] = None, session=None):
    """
    Re-evaluates metric applicability for a Node after an update.
    1. Removes :HAS_METRIC relationships for metrics that NO LONGER apply.
    2. Adds :HAS_METRIC relationships for metrics that NOW apply.
    """
    from repositories.topology_repo import link_metric_to_node
    
    node_id = node.get("id")
    if not node_id: return
    
    applicable = get_applicable_metrics(node_id, metrics_catalog=metrics_catalog, session=session)
    applicable_ids = [m["id"] for m in applicable]
    
    if session:
        _reconcile_impl(node_id, applicable, applicable_ids, session)
    else:
        driver = get_db()
        with driver.session() as session:
            _reconcile_impl(node_id, applicable, applicable_ids, session)

def _reconcile_impl(node_id: str, applicable: List[Dict], applicable_ids: List[str], session):
    from repositories.topology_repo import link_metric_to_node
    # 1. Fetch CURRENTLY LINKED metrics and their thresholds
    result = session.run("""
        MATCH (n:CI {id: $nid})-[r:HAS_METRIC]->(m:MetricDef)
        RETURN m.id as mid, m.applicable_to as apt, r.warning_threshold as warn, r.critical_threshold as crit
    """, nid=node_id)

    linked_metrics = {rec["mid"]: {"apt": rec["apt"], "warn": rec["warn"], "crit": rec["crit"]} for rec in result}

    # 2. Determine Removals
    for mid in linked_metrics.keys():
        if mid not in applicable_ids:
            logger.info(f"Removing obsolete metric {mid} from Node {node_id}")
            session.run("""
                MATCH (n:CI {id: $nid})-[r:HAS_METRIC]->(m:MetricDef {id: $mid})
                DELETE r
            """, nid=node_id, mid=mid)

    # 3. Determine Additions/Updates
    for m in applicable:
            mid = m["id"]
            if mid not in linked_metrics:
                logger.info(f"Auto-assigning new metric {mid} to Node {node_id}")
                # Use driver from session if needed or just use current session if link_metric_to_node supports it
                # link_metric_to_node doesn't currently support session, but it uses get_db()
                link_metric_to_node(node_id, mid, warning=m.get("warning"), critical=m.get("critical"))
            else:
                # Fix: Update properties if they differ from defaults (ensures rule changes propagate)
                curr = linked_metrics[mid]
                if curr["warn"] != m.get("warning") or curr["crit"] != m.get("critical"):
                    logger.info(f"Updating thresholds for existing metric {mid} on Node {node_id}")
                    link_metric_to_node(node_id, mid, warning=m.get("warning"), critical=m.get("critical"))

def promote_metric_node(ci_id: str, metric_name: str, display_name: str = None):
    """
    Promotes a metric of a CI to a first-class Graph Node.
    Useful for visualizing complex metric relationships.
    """
    driver = get_db()
    with driver.session() as session:
        # Check if already promoted or exists
        mid = f"M-{ci_id}-{metric_name}"
        label = display_name or f"{metric_name} of {ci_id}"
        
        session.run("""
            MATCH (n:CI {id: $cid})
            MERGE (m:MetricDef {id: $mid})
            SET m.name = $label, m.is_promoted = true
            MERGE (n)-[:HAS_EXTERNAL_METRIC]->(m)
        """, cid=ci_id, mid=mid, label=label)
    return {"message": "Metric promoted to node", "id": mid}
