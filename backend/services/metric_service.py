import json
import uuid
import logging
from typing import List, Dict, Any, Optional
from database import get_db
from models.core import MetricDef
from services.metric_operation_guard import metric_operation_guard
from services.operation_timing import timed_operation

logger = logging.getLogger(__name__)


def _normalize_criteria_values(values: List[str]) -> List[str]:
    return [value.strip().lower() for value in values if isinstance(value, str) and value.strip()]


def metric_matches_ci(criteria: Optional[Dict[str, List[str]]], ci: Dict[str, Any]) -> bool:
    criteria = criteria or {}

    ci_name = str(ci.get("name") or "").strip().lower()
    ci_id = str(ci.get("id") or "").strip().lower()
    ci_brand = str(ci.get("brand") or "").strip().lower()
    ci_model = str(ci.get("model") or "").strip().lower()
    ci_layer = str(ci.get("layer") or "").strip().lower()

    requested_names = _normalize_criteria_values(criteria.get("names", []))
    excluded_names = _normalize_criteria_values(criteria.get("excluded_names", []))
    requested_brands = _normalize_criteria_values(criteria.get("brands", []))
    requested_models = _normalize_criteria_values(criteria.get("models", []))
    requested_layers = _normalize_criteria_values(criteria.get("layers", []))

    if requested_names and ci_name not in requested_names and ci_id not in requested_names:
        return False

    if requested_brands and ci_brand not in requested_brands:
        return False

    if requested_models and ci_model not in requested_models:
        return False

    if requested_layers and ci_layer not in requested_layers:
        return False

    has_positive_filters = any(
        [requested_names, requested_brands, requested_models, requested_layers]
    )
    if not has_positive_filters:
        return False

    if excluded_names and (ci_name in excluded_names or ci_id in excluded_names):
        return False

    return True

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
                except Exception:
                    logger.warning("Failed to parse applicable_to for metric %s", m.get("id"), exc_info=True)

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
                "polling_interval": m.get("polling_interval", 60),
                "can_propagate": m.get("can_propagate", True),
                # CLI-specific fields
                "cli_command": m.get("cli_command"),
                "cli_target": m.get("cli_target"),
                "cli_value_extractor": m.get("cli_value_extractor"),
                "cli_credential_ref": m.get("cli_credential_ref"),
                "cli_escalation_script": m.get("cli_escalation_script"),
                "cli_protocol": m.get("cli_protocol"),
                "cli_timeout": m.get("cli_timeout"),
            })
        return metrics


def get_metric(metric_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single metric definition with its persisted fields."""
    driver = get_db()
    with driver.session() as session:
        record = session.run("MATCH (m:MetricDef {id: $id}) RETURN m", id=metric_id).single()
        if not record:
            return None

        m = record["m"]
        criteria = {}
        if m.get("applicable_to"):
            try:
                criteria = json.loads(m.get("applicable_to"))
            except Exception:
                criteria = {}

        return {
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
            "polling_interval": m.get("polling_interval", 60),
            "can_propagate": m.get("can_propagate", True),
            # CLI-specific fields
            "cli_command": m.get("cli_command"),
            "cli_target": m.get("cli_target"),
            "cli_value_extractor": m.get("cli_value_extractor"),
            "cli_credential_ref": m.get("cli_credential_ref"),
            "cli_escalation_script": m.get("cli_escalation_script"),
            "cli_protocol": m.get("cli_protocol"),
            "cli_timeout": m.get("cli_timeout"),
        }


def _reconcile_metric_assignments(metric_id: str, criteria: Optional[Dict[str, List[str]]]) -> None:
    """Keep persisted HAS_METRIC links aligned with criteria-based applicability."""
    affected_nodes: list[Dict[str, Any]] = []
    with timed_operation(logger, "metric.reconcile_assignments", metric_id=metric_id):
        driver = get_db()
        with driver.session() as session:
            result = session.run(
                """
                MATCH (n:CI)
                OPTIONAL MATCH (n)-[:HAS_METRIC]->(m:MetricDef {id: $metric_id})
                RETURN n AS node, m IS NOT NULL AS currently_linked
                """,
                metric_id=metric_id,
            )
            affected_nodes = [
                dict(record["node"])
                for record in result
                if record["currently_linked"] or metric_matches_ci(criteria, dict(record["node"]))
            ]

        for node in affected_nodes:
            reconcile_node_metrics(node)

    logger.info(
        "Metric assignment reconciliation affected %s nodes",
        len(affected_nodes),
        extra={
            "operation": "metric.reconcile_assignments.counts",
            "metric_id": metric_id,
            "affected_count": len(affected_nodes),
        },
    )

def create_metric(metric: MetricDef) -> Dict[str, str]:
    """
    Define a new Metric for monitoring.
    """
    with metric_operation_guard(metric.id):
        with timed_operation(logger, "metric.create", metric_id=metric.id):
            driver = get_db()
            criteria_str = json.dumps(metric.applicable_to) if metric.applicable_to else "{}"

            with driver.session() as session:
                session.run("""
                    MERGE (m:MetricDef {id: $id})
                    SET m.protocol = $prot, m.warning = $warn, m.critical = $crit,
                        m.oid = $oid, m.dataType = $dtype, m.unit = $unit,
                        m.description = $desc, m.applicable_to = $criteria,
                        m.operator = $operator, m.criticality = $criticality,
                        m.polling_interval = $polling_interval,
                        m.can_propagate = $can_propagate,
                        m.cli_command = $cli_command,
                        m.cli_target = $cli_target,
                        m.cli_value_extractor = $cli_value_extractor,
                        m.cli_credential_ref = $cli_credential_ref,
                        m.cli_escalation_script = $cli_escalation_script,
                        m.cli_protocol = $cli_protocol,
                        m.cli_timeout = $cli_timeout
                """, id=metric.id, prot=metric.protocol, warn=metric.warning,
                     crit=metric.critical, oid=metric.oid, dtype=metric.dataType,
                     unit=metric.unit, desc=metric.description, criteria=criteria_str,
                     operator=metric.operator or ">=", criticality=metric.criticality or 1,
                     polling_interval=metric.polling_interval or 60,
                     can_propagate=metric.can_propagate,
                     cli_command=metric.cli_command,
                     cli_target=metric.cli_target,
                     cli_value_extractor=metric.cli_value_extractor,
                     cli_credential_ref=metric.cli_credential_ref,
                     cli_escalation_script=metric.cli_escalation_script,
                     cli_protocol=metric.cli_protocol,
                     cli_timeout=metric.cli_timeout)

            _reconcile_metric_assignments(metric.id, metric.applicable_to)
            return {"message": "Metric defined"}

def delete_metric(metric_id: str) -> Dict[str, Any]:
    """Delete a Metric Definition and retire active collection failures.

    Historical Timescale samples are intentionally retained. Metric deletion is
    about stopping future collection and removing graph applicability, not
    purging telemetry history.
    """
    with metric_operation_guard(metric_id):
        with timed_operation(logger, "metric.delete", metric_id=metric_id):
            driver = get_db()
            with driver.session() as session:
                with session.begin_transaction() as tx:
                    event_result = tx.run(
                        """
                        MATCH (e:Event)
                        WHERE e.status IN ['OPEN', 'ACK']
                          AND (
                            e.metric_id = $id
                            OR EXISTS {
                              MATCH (e)-[:TRIGGERED_BY]->(:MetricDef {id: $id})
                            }
                          )
                          AND (
                            e.event_type = 'COLLECTION_FAILURE'
                            OR (e.event_type IS NULL AND e.message STARTS WITH 'Metric Collection Failed:')
                          )
                        SET e.status = 'RECOVERED',
                            e.recovered_at = datetime(),
                            e.last_seen = datetime(),
                            e.message = 'Metric collection retired because metric definition was deleted',
                            e.ack = false
                        RETURN count(DISTINCT e) AS events_recovered
                        """,
                        id=metric_id,
                    )
                    event_record = event_result.single()
                    raw_events_recovered = event_record.get("events_recovered", 0) if event_record else 0
                    events_recovered = raw_events_recovered if isinstance(raw_events_recovered, int) else 0

                    delete_result = tx.run(
                        """
                        MATCH (m:MetricDef {id: $id})
                        WITH collect(m) AS metrics
                        FOREACH (metric IN metrics | DETACH DELETE metric)
                        RETURN size(metrics) AS deleted
                        """,
                        id=metric_id,
                    )
                    delete_record = delete_result.single()
                    raw_deleted_count = delete_record.get("deleted", 0) if delete_record else 0
                    deleted_count = raw_deleted_count if isinstance(raw_deleted_count, int) else 1

            deleted = deleted_count > 0
            return {
                "message": "Metric deleted" if deleted else "Metric not found",
                "metric_id": metric_id,
                "deleted": deleted,
                "events_recovered": events_recovered,
                "history_retained": True,
            }

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
        except Exception:
            logger.warning("Failed to parse applicable_to for metric %s", metric_id, exc_info=True)
            
        models = criteria.get("models", [])
        brands = criteria.get("brands", [])
        layers = criteria.get("layers", [])
        names = criteria.get("names", [])
        excluded_names = criteria.get("excluded_names", [])
        
        # 1. Base Query: CIs that already have this metric assigned/collected
        query = """
            MATCH (n:CI)-[:HAS_METRIC]->(m:MetricDef {id: $id})
            RETURN n.id as id, n.name as name, n.ip as ip, n.model as model, n.brand as brand, n.layer as layer
        """
        
        # 2. Add CIs matching criteria candidates, then filter with the same applicability logic used elsewhere.
        if models or brands or layers or names:
            query += """
            UNION
            MATCH (n:CI)
            WHERE (
                ($models <> [] AND n.model IN $models)
                OR ($brands <> [] AND n.brand IN $brands)
                OR ($layers <> [] AND n.layer IN $layers)
                OR ($names <> [] AND (n.name IN $names OR n.id IN $names))
            )
            RETURN n.id as id, n.name as name, n.ip as ip, n.model as model, n.brand as brand, n.layer as layer
            """

        result = session.run(query, id=metric_id, models=models, brands=brands, layers=layers, names=names)
        cis = [dict(record) for record in result]
        
        # Deduplicate and Apply Exclusions
        unique_cis = {}
        for ci in cis:
            if metric_matches_ci(criteria, ci):
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
                if metric_matches_ci(criteria, node):
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

    with timed_operation(logger, "metric.reconcile_node", ci_id=node_id):
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
            add_count = 0
            remove_count = 0

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
                        remove_count += 1

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
                    add_count += 1
                    # Log warning if MetricDef doesn't exist (MERGE silently skipped)
                    # Only check nodes_created when result supports it (not in test FakeResult)
                    try:
                        if hasattr(result, 'consume') and result.consume().counters.nodes_created == 0:
                            logger.warning(f"MetricDef '{mid}' not found — skipped for Node {node_id}")
                    except (AttributeError, TypeError):
                        pass  # FakeResult in tests or other mock doesn't support consume()

        logger.info(
            "Node metric reconciliation counts",
            extra={
                "operation": "metric.reconcile_node.counts",
                "ci_id": node_id,
                "applicable_count": len(applicable_ids),
                "linked_count": len(linked_metrics),
                "add_count": add_count,
                "remove_count": remove_count,
            },
        )
