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

def delete_metric(metric_id: str) -> Dict[str, str]:
    """Delete a Metric Definition."""
    driver = get_db()
    with driver.session() as session:
        session.run("MATCH (m:MetricDef {id: $id}) DETACH DELETE m", id=metric_id)
    return {"message": "Metric deleted"}

def get_applicable_metrics(node_id: str) -> List[Dict[str, Any]]:
    """
    Get all eligible metrics for a specific Node based on its properties (Brand, Model, Layer).
    """
    driver = get_db()
    with driver.session() as session:
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
        
        # 2. Fetch All Metric Definitions
        res_metrics = session.run("MATCH (m:MetricDef) RETURN m")
        applicable_metrics = []
        
        # 3. Filter Metrics based on criteria (AND logic)
        for rec in res_metrics:
            m = rec["m"]
            criteria_json = m.get("applicable_to")
            if not criteria_json:
                continue
                
            try:
                criteria = json.loads(criteria_json)
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

def reconcile_node_metrics(node: Dict[str, Any]):
    """
    Re-evaluates metric applicability for a Node after an update.
    1. Removes :HAS_METRIC relationships for metrics that NO LONGER apply.
    2. Adds :HAS_METRIC relationships for metrics that NOW apply.
    """
    from repositories.topology_repo import link_metric_to_node
    
    node_id = node.get("id")
    if not node_id: return
    
    applicable = get_applicable_metrics(node_id)
    applicable_ids = [m["id"] for m in applicable]
    
    driver = get_db()
    with driver.session() as session:
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
                  # Pass default thresholds from the definition to the individual link
                  link_metric_to_node(node_id, mid, warning=m.get("warning"), critical=m.get("critical"))
             else:
                  # Fix: Update properties if they differ from defaults (ensures rule changes propagate)
                  curr = linked_metrics[mid]
                  if curr["warn"] != m.get("warning") or curr["crit"] != m.get("critical"):
                      logger.info(f"Updating thresholds for existing metric {mid} on Node {node_id}")
                      link_metric_to_node(node_id, mid, warning=m.get("warning"), critical=m.get("critical"))
