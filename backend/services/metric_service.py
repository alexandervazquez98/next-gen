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

def get_metric_usage(metric_id: str) -> Dict[str, Any]:
    """
    Analyze how many CIs currently match this metric's criteria.
    """
    driver = get_db()
    with driver.session() as session:
        result = session.run("MATCH (m:MetricDef {id: $id}) RETURN m.applicable_to as apt", id=metric_id)
        record = result.single()
        if not record: return {"count": 0, "criteria": "None"}
        
        criteria = {}
        try: criteria = json.loads(record["apt"] or "{}")
        except: pass
            
        models = criteria.get("models", [])
        brands = criteria.get("brands", [])
        layers = criteria.get("layers", [])
        names = criteria.get("names", [])
        excluded_names = criteria.get("excluded_names", [])
        
        # 1. Base Query: CIs that already have this metric assigned/collected
        query = """
            MATCH (n:CI)-[:HAS_METRIC]->(m:MetricDef {id: $id})
            RETURN n.id as id, n.name as name, n.ip as ip, n.model as model, n.brand as brand
        """
        
        # 2. Add CIs matching criteria (if any)
        if models or brands or layers or names:
            query += """
            UNION
            MATCH (n:CI)
            WHERE (n.model IN $models OR n.brand IN $brands OR n.layer IN $layers OR n.name IN $names OR n.id IN $names)
            RETURN n.id as id, n.name as name, n.ip as ip, n.model as model, n.brand as brand
            """
            
        result = session.run(query, id=metric_id, models=models, brands=brands, layers=layers, names=names)
        cis = [dict(record) for record in result]
        
        # Deduplicate and Apply Exclusions
        unique_cis = {}
        for ci in cis:
             if ci['name'] not in excluded_names and ci['id'] not in excluded_names:
                 unique_cis[ci['id']] = ci
        
        cis_list = list(unique_cis.values())
        return {"count": len(cis_list), "cis": cis_list, "criteria": criteria}

def promote_metric_node(ci_id: str, metric_name: str, display_name: Optional[str] = None) -> Dict[str, str]:
    """
    Promote a specific metric property of a CI to a first-class Graph Node.
    """
    driver = get_db()
    metric_id = str(uuid.uuid4())
    display = display_name or metric_name
    
    with driver.session() as session:
        session.run("""
            MATCH (ci:CI {id: $ci_id})
            MERGE (m:Metric {name: $name, display_name: $display, source_ci: $ci_id})
            ON CREATE SET m.id = $id, m.created_at = datetime()
            MERGE (ci)-[:HAS_METRIC]->(m)
            RETURN m
        """, ci_id=ci_id, name=metric_name, display=display, id=metric_id)
        
    return {"message": "Metric promoted to Node", "id": metric_id, "label": display}

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
        
        for rec in res_metrics:
            m = rec["m"]
            criteria_json = m.get("applicable_to")
            if not criteria_json:
                continue
                
            try:
                criteria = json.loads(criteria_json)
                
                # Check specifics (Direct Name Match)
                req_names = [n.strip().lower() for n in criteria.get("names", [])]
                if req_names and (node_name in req_names or node_ci_id in req_names):
                    applicable_metrics.append({
                        "id": m.get("id"),
                        "name": m.get("id"),
                        "description": m.get("description"),
                        "unit": m.get("unit")
                    })
                    continue

                # Check Categories (Brand/Model/Layer)
                req_brands = [b.strip().lower() for b in criteria.get("brands", [])]
                req_models = [m.strip().lower() for m in criteria.get("models", [])]
                req_layers = [l.strip().lower() for l in criteria.get("layers", [])]
                
                match = False
                if req_brands and brand in req_brands: match = True
                if req_models and model in req_models: match = True
                if req_layers and layer in req_layers: match = True
                
                if match:
                    applicable_metrics.append({
                        "id": m.get("id"),
                        "name": m.get("id"), 
                        "description": m.get("description"),
                        "unit": m.get("unit")
                    })
            except Exception as e:
                logger.error(f"Error parsing metric criteria: {e}")
                pass
                
        return applicable_metrics

def reconcile_node_metrics(node: Dict[str, Any]):
    """
    Re-evaluates metric applicability for a Node after an update.
    1. Removes :HAS_METRIC relationships for metrics that NO LONGER apply (and aren't explicit).
    2. Adds :HAS_METRIC relationships for metrics that NOW apply.
    
    With AppliedDictionary overlay: effective = (applicable ∪ dict_metrics) - excluded + extra
    """
    from services.dictionary_service import get_metrics_from_dictionary

    driver = get_db()
    node_id = node.get("id")
    if not node_id:
        return

    # Get currently applicable metrics based on brand/model criteria
    applicable = get_applicable_metrics(node_id)
    applicable_ids = set(m["id"] for m in applicable)

    # Lookup AppliedDictionary overlay (if any)
    dict_metric_ids: set[str] = set()
    excluded: set[str] = set()
    extra: set[str] = set()

    with driver.session() as session:
        ad_result = session.run("""
            MATCH (ci:CI {id: $nid})-[:HAS_DICTIONARY]->(ad:AppliedDictionary)
            OPTIONAL MATCH (ad)-[:REFERENCE_DICTIONARY]->(md:MetricDictionary)
            RETURN ad.dictionary_id AS dictionary_id,
                   ad.excluded_metrics AS excluded_metrics,
                   ad.extra_metrics AS extra_metrics,
                   md.id AS md_id
        """, nid=node_id).single()

        if ad_result and ad_result.get("dictionary_id"):
            dictionary_id = ad_result["dictionary_id"]
            excluded = set(ad_result.get("excluded_metrics") or [])
            extra = set(ad_result.get("extra_metrics") or [])

            # Fetch dictionary metric_ids via HAS_METRIC rel (handle deleted dict gracefully)
            if ad_result.get("md_id") and dictionary_id:
                try:
                    dict_metric_ids = set(get_metrics_from_dictionary(dictionary_id))
                except Exception:
                    logger.warning(f"Failed to fetch dictionary '{dictionary_id}' metrics — treating as empty")
                    dict_metric_ids = set()

            logger.info(
                f"AppliedDictionary overlay: dict={dictionary_id}, "
                f"excluded={excluded}, extra={extra}"
            )

    # Compute effective metric set
    # Formula: (applicable ∪ dict_metrics) - excluded ∪ extra
    # Parentheses required because | and - have same precedence and left-to-right would mis-evaluate
    effective_ids = ((applicable_ids | dict_metric_ids) - excluded) | extra

    with driver.session() as session:
        # 1. Fetch CURRENTLY LINKED metrics
        result = session.run("""
            MATCH (n:CI {id: $nid})-[r:HAS_METRIC]->(m:MetricDef)
            RETURN m.id as mid, m.applicable_to as apt
        """, nid=node_id)

        linked_metrics = {rec["mid"]: rec["apt"] for rec in result}

        # 2. Determine Removals
        for mid, apt_json in linked_metrics.items():
            if mid not in effective_ids:
                # Check if explicitly named (Safety check)
                is_explicit = False
                try:
                    apt = json.loads(apt_json or "{}")
                    names = apt.get("names", [])
                    if node.get("name") in names or node_id in names:
                        is_explicit = True
                except Exception:
                    pass

                if not is_explicit:
                    logger.info(f"Removing obsolete metric {mid} from Node {node_id}")
                    session.run("""
                        MATCH (n:CI {id: $nid})-[r:HAS_METRIC]->(m:MetricDef {id: $mid})
                        DELETE r
                    """, nid=node_id, mid=mid)

        # 3. Determine Additions — use effective_ids so dictionary/extras are included
        for mid in effective_ids:
            if mid not in linked_metrics:
                logger.info(f"Auto-assigning metric {mid} to Node {node_id}")
                result = session.run("""
                    MATCH (n:CI {id: $nid})
                    MATCH (m:MetricDef {id: $mid})
                    MERGE (n)-[:HAS_METRIC]->(m)
                    SET n.updated_at = datetime()
                """, nid=node_id, mid=mid)
                # Log warning if MetricDef doesn't exist (MERGE silently skipped)
                # Only check nodes_created when result supports it (not in test FakeResult)
                try:
                    if hasattr(result, 'consume') and result.consume().counters.nodes_created == 0:
                        logger.warning(f"MetricDef '{mid}' not found — skipped for Node {node_id}")
                except (AttributeError, TypeError):
                    pass  # FakeResult in tests or other mock doesn't support consume()
