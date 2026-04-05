from __future__ import annotations

import asyncio
import ast
import json
import logging
import subprocess
import time
from datetime import datetime
from typing import Any, Dict

from database import get_db

logger = logging.getLogger(__name__)

try:
    from pysnmp.hlapi import (
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        getCmd,
    )

    SNMP_AVAILABLE = True
except ImportError:
    SNMP_AVAILABLE = False
    logger.warning("PySNMP not installed. SNMP features will be disabled.")

LAST_COLLECTION_TIME = None
COLLECTOR_STATUS = "STOPPED"
GLOBAL_STATS = {
    "cis_monitored": 0,
    "metrics_collected": 0,
    "metrics_failed": 0,
    "cycle_duration": 0.0,
    "jobs_per_min": 0.0,
}


def get_collector_status():
    return {
        "last_run": LAST_COLLECTION_TIME,
        "status": COLLECTOR_STATUS,
        "stats": GLOBAL_STATS,
    }


def _parse_snmp_config(snmp_raw: Any) -> Dict[str, Any]:
    if not snmp_raw:
        return {}
    if isinstance(snmp_raw, dict):
        return snmp_raw
    try:
        return json.loads(snmp_raw)
    except Exception:
        try:
            return ast.literal_eval(snmp_raw)
        except Exception:
            return {}


def resolve_event_snapshot(session, ci_id: str) -> Dict[str, Any]:
    record = session.run(
        """
        MATCH (ci:CI {id: $ci_id})
        OPTIONAL MATCH (ci)-[:BELONGS_TO]->(bs:BusinessService)
        OPTIONAL MATCH (bs)-[:USES_SLA]->(sc:ServiceCatalog)
        RETURN ci.locationName AS site,
               bs.id AS business_service_id,
               bs.name AS business_service_name,
               bs.tier AS business_service_tier,
               bs.owner_t1 AS owner_t1,
               bs.owner_t2 AS owner_t2,
               bs.owner_t3 AS owner_t3,
               bs.impacted_users_count AS impacted_users,
               sc.id AS service_catalog_id,
               sc.category AS service_category,
               sc.service_tier AS service_tier,
               sc.sla_minutes AS sla_minutes
        """,
        ci_id=ci_id,
    ).single()

    if not record:
        return {}

    return {
        "business_service_id": record.get("business_service_id"),
        "business_service_name": record.get("business_service_name"),
        "business_service_tier": record.get("business_service_tier"),
        "owner_t1": record.get("owner_t1"),
        "owner_t2": record.get("owner_t2"),
        "owner_t3": record.get("owner_t3"),
        "impacted_users": record.get("impacted_users"),
        "site": record.get("site"),
        "service_catalog_id": record.get("service_catalog_id"),
        "service_category": record.get("service_category"),
        "service_tier": record.get("service_tier"),
        "sla_minutes": record.get("sla_minutes"),
    }


async def snmp_collector_loop():
    if not SNMP_AVAILABLE:
        logger.warning("SNMP Collector disabled due to missing pysnmp.")
        return

    global LAST_COLLECTION_TIME, COLLECTOR_STATUS

    driver = get_db()
    COLLECTOR_STATUS = "RUNNING"

    while True:
        try:
            logger.info("[Collector] Starting Poll Cycle (Thread Offload)...")
            start_time = time.time()
            stats = await asyncio.to_thread(run_snmp_cycle_sync, driver)
            elapsed = time.time() - start_time
            LAST_COLLECTION_TIME = datetime.now().isoformat()

            GLOBAL_STATS["cycle_duration"] = round(elapsed, 2)
            GLOBAL_STATS["cis_monitored"] = stats.get("cis", 0)
            GLOBAL_STATS["metrics_collected"] = stats.get("total", 0)
            GLOBAL_STATS["metrics_failed"] = stats.get("errors", 0)
            if elapsed > 0:
                GLOBAL_STATS["jobs_per_min"] = round(
                    (stats.get("total", 0) / elapsed) * 60, 1
                )

            logger.info(
                "[Collector] Cycle finished in %.2fs. Stats: %s", elapsed, GLOBAL_STATS
            )
            await asyncio.sleep(60)
        except Exception as exc:
            logger.error("[Collector] Critical Loop Error: %s", exc, exc_info=True)
            COLLECTOR_STATUS = "ERROR"
            await asyncio.sleep(10)


def run_snmp_cycle_sync(driver):
    with driver.session() as session:
        cis_result = session.run(
            """
            MATCH (n:CI)
            WHERE n.ip IS NOT NULL AND n.status <> 'EXCEPTION'
            RETURN n
        """
        )
        cis = [dict(record["n"]) for record in cis_result]
        logger.info("[Collector] Found %s candidate CIs for monitoring.", len(cis))

        metrics_result = session.run("MATCH (m:MetricDef) RETURN m")
        metrics = []
        for record in metrics_result:
            metric = dict(record["m"])
            criteria = {}
            if metric.get("applicable_to"):
                try:
                    criteria = json.loads(metric.get("applicable_to"))
                except Exception:
                    criteria = {}

            metrics.append(
                {
                    "id": metric.get("id"),
                    "name": metric.get("name") or metric.get("id"),
                    "oid": metric.get("oid"),
                    "protocol": metric.get("protocol"),
                    "criticality": metric.get("criticality", 1),
                    "warning": metric.get("warning"),
                    "critical": metric.get("critical"),
                    "operator": metric.get("operator", ">="),
                    "applicable_to": criteria,
                }
            )

    total_metrics = 0
    total_errors = 0
    for ci in cis:
        executed, errors = process_ci_metrics(ci, metrics, driver)
        total_metrics += executed
        total_errors += errors

    return {"cis": len(cis), "total": total_metrics, "errors": total_errors}


def process_ci_metrics(ci, metrics, driver):
    snmp_conf = _parse_snmp_config(ci.get("snmp"))
    ci_brand = ci.get("brand", "").lower() if ci.get("brand") else ""
    ci_model = ci.get("model", "").lower() if ci.get("model") else ""
    ci_layer = ci.get("layer", "").lower() if ci.get("layer") else ""

    target_metrics = []
    for metric in metrics:
        criteria = metric.get("applicable_to", {})
        match = False
        requested_names = [name.strip().lower() for name in criteria.get("names", [])]

        if requested_names and (
            ci.get("name", "").lower() in requested_names
            or ci.get("id", "").lower() in requested_names
        ):
            match = True
        else:
            requested_brands = [brand.lower() for brand in criteria.get("brands", [])]
            requested_models = [model.lower() for model in criteria.get("models", [])]
            requested_layers = [layer.lower() for layer in criteria.get("layers", [])]

            if requested_brands and ci_brand in requested_brands:
                match = True
            if requested_models and ci_model in requested_models:
                match = True
            if requested_layers and ci_layer in requested_layers:
                match = True

        excluded_names = [
            name.strip().lower() for name in criteria.get("excluded_names", [])
        ]
        if match and (
            ci.get("name", "").lower() in excluded_names
            or ci.get("id", "").lower() in excluded_names
        ):
            match = False

        if match and (metric.get("oid") or metric.get("protocol") == "ICMP"):
            target_metrics.append(metric)

    executed = 0
    errors = 0
    for target_metric in target_metrics:
        try:
            executed += 1
            if target_metric.get("protocol") == "SNMP" and (
                not snmp_conf or not snmp_conf.get("readCommunity")
            ):
                continue

            value, status, error_message = poll_metric(ci, target_metric, snmp_conf)
            store_metric_result(ci, target_metric, value, status, error_message, driver)
        except Exception as exc:
            errors += 1
            logger.error(
                "[Collector] Error processing metric %s for %s: %s",
                target_metric.get("name"),
                ci.get("name"),
                exc,
                exc_info=True,
            )

    return executed, errors


def poll_metric(ci, metric_def, snmp_conf):
    proto = str(metric_def.get("protocol", "")).upper().strip()

    if proto == "ICMP":
        import platform

        param = "-n" if platform.system().lower() == "windows" else "-c"
        command = ["ping", param, "1", ci.get("ip")]
        try:
            result = subprocess.call(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return (1, "OK", None) if result == 0 else (0, "OK", None)
        except Exception as exc:
            logger.error("PING Exception for %s: %s", ci.get("ip"), exc)
            return 0, "ERROR", str(exc)

    if metric_def.get("oid") and metric_def.get("oid") != "ICMP" and SNMP_AVAILABLE:
        try:
            oid = metric_def["oid"]
            error_indication, error_status, error_index, var_binds = next(
                getCmd(
                    SnmpEngine(),
                    CommunityData(snmp_conf.get("readCommunity")),
                    UdpTransportTarget(
                        (ci.get("ip"), snmp_conf.get("port", 161)),
                        timeout=1.0,
                        retries=0,
                    ),
                    ContextData(),
                    ObjectType(ObjectIdentity(oid)),
                )
            )

            if error_indication:
                return None, "TIMEOUT", str(error_indication)
            if error_status:
                error = f"{error_status.prettyPrint()} at {error_index and var_binds[int(error_index) - 1][0] or '?'}"
                return None, "ERROR", error
            return str(var_binds[0][1]), "OK", None
        except Exception as exc:
            logger.error("SNMP Error %s: %s", ci.get("id"), exc)
            return None, "ERROR", str(exc)

    return None, "ERROR", "Unknown Protocol or OID"


def store_metric_result(ci, metric_def, val, poll_status, err_msg, driver):
    crit_level = metric_def.get("criticality", 1)
    base_severity = "INFO"
    if crit_level == 2:
        base_severity = "WARNING"
    if crit_level == 3:
        base_severity = "CRITICAL"

    status = "OK"
    severity = "INFO"
    is_breach = False
    message = f"Metric {metric_def.get('name', metric_def['id'])} is OK. Value: {val}"

    if poll_status != "OK":
        status = "CRITICAL"
        severity = base_severity
        is_breach = True
        message = f"Metric Collection Failed: {err_msg or 'Timeout'}"
        val = "N/A"
    elif val is not None:
        try:
            num_val = float(val)
            is_availability_metric = (
                metric_def.get("protocol") == "ICMP"
                or metric_def.get("name") == "mariadb-GS"
            )

            if not is_availability_metric:
                operator = metric_def.get("operator", ">=")

                def check_op(left, right, oper):
                    if oper == ">=":
                        return left >= right
                    if oper == "<=":
                        return left <= right
                    if oper == "==":
                        return left == right
                    if oper == "!=":
                        return left != right
                    return left >= right

                if metric_def.get("critical") is not None and check_op(
                    num_val, float(metric_def["critical"]), operator
                ):
                    status = "CRITICAL"
                    severity = "CRITICAL"
                    is_breach = True
                    message = f"Critical Threshold Breached: {val} {operator} {metric_def['critical']}"
                elif metric_def.get("warning") is not None and check_op(
                    num_val, float(metric_def["warning"]), operator
                ):
                    status = "WARNING"
                    severity = "WARNING"
                    is_breach = True
                    message = f"Warning Threshold Breached: {val} {operator} {metric_def['warning']}"

            if is_availability_metric and float(val) == 0:
                status = "CRITICAL"
                severity = base_severity
                is_breach = True
                message = f"Service/Host Down: {metric_def.get('name')}"
        except ValueError:
            pass

    with driver.session() as session:
        session.run(
            """
            MATCH (n:CI {id: $nid})
            MATCH (m:MetricDef {id: $mid})
            MERGE (n)-[r:HAS_METRIC]->(m)
            SET r.last_value = $val, r.last_updated = datetime(), r.status = $status, r.last_message = $msg

            CREATE (res:MetricResult {
                timestamp: datetime(),
                value: $val,
                status: $status
            })
            CREATE (n)-[:HAS_RESULT]->(res)
            CREATE (res)-[:FOR_METRIC]->(m)
        """,
            nid=ci.get("id"),
            mid=metric_def["id"],
            val=str(val),
            status=status,
            msg=message,
        )

        if is_breach:
            existing = session.run(
                """
                MATCH (existing:Event)
                WHERE existing.ci_id = $nid AND existing.metric_id = $mid AND existing.status IN ['OPEN', 'ACK']
                RETURN existing
                LIMIT 1
            """,
                nid=ci.get("id"),
                mid=metric_def["id"],
            ).single()

            if existing:
                session.run(
                    """
                    MATCH (existing:Event)
                    WHERE existing.ci_id = $nid AND existing.metric_id = $mid AND existing.status IN ['OPEN', 'ACK']
                    SET existing.last_seen = datetime(),
                        existing.message = $msg,
                        existing.severity = $sev
                """,
                    nid=ci.get("id"),
                    mid=metric_def["id"],
                    msg=message,
                    sev=severity,
                )
            else:
                snapshot = resolve_event_snapshot(session, ci.get("id"))
                session.run(
                    """
                    MATCH (n:CI {id: $nid})
                    MATCH (m:MetricDef {id: $mid})
                    CREATE (e:Event {
                        id: randomUUID(),
                        ci_id: $nid,
                        metric_id: $mid,
                        status: 'OPEN',
                        severity: $sev,
                        message: $msg,
                        created_at: datetime(),
                        last_seen: datetime(),
                        ack: false,
                        business_service_id: $business_service_id,
                        business_service_name: $business_service_name,
                        business_service_tier: $business_service_tier,
                        owner_t1: $owner_t1,
                        owner_t2: $owner_t2,
                        owner_t3: $owner_t3,
                        impacted_users: $impacted_users,
                        site: $site,
                        service_catalog_id: $service_catalog_id,
                        service_category: $service_category,
                        service_tier: $service_tier,
                        sla_minutes: $sla_minutes
                    })
                    MERGE (n)-[:HAS_EVENT]->(e)
                    MERGE (e)-[:TRIGGERED_BY]->(m)
                """,
                    nid=ci.get("id"),
                    mid=metric_def["id"],
                    sev=severity,
                    msg=message,
                    **snapshot,
                )
        else:
            session.run(
                """
                MATCH (n:CI {id: $nid})-[:HAS_EVENT]->(e:Event {metric_id: $mid})
                WHERE e.status IN ['OPEN', 'ACK']
                SET e.status = 'RECOVERED', e.recovered_at = datetime(), e.message = $msg
            """,
                nid=ci.get("id"),
                mid=metric_def["id"],
                msg=message,
            )


def run_diagnostic(ci, metric):
    protocol = metric.get("protocol")
    if protocol == "ICMP":
        try:
            ping_flag = "-n" if subprocess.os.name == "nt" else "-c"
            process = subprocess.Popen(
                ["ping", ping_flag, "3", ci.get("ip")],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = process.communicate()
            if process.returncode == 0:
                return f"[SUCCESS] PING CHECK PASSED\nOutput:\n{stdout.decode()}"
            return f"[FAILED] PING CHECK FAILED\nError:\n{stderr.decode() or stdout.decode()}"
        except Exception as exc:
            return f"[ERROR] Diagnostic Error: {str(exc)}"

    if protocol == "SNMP":
        return f"[INFO] SNMP Diagnostic initiated for OID {metric.get('oid')}. \n(Verify connectivity manually to {ci.get('ip')})"

    return f"[INFO] No automated diagnostic available for protocol {protocol}"


def validate_snmp_oid(ip, community, oid, port=161):
    if not SNMP_AVAILABLE:
        return {"success": False, "error": "PySNMP not installed"}

    try:
        error_indication, error_status, error_index, var_binds = next(
            getCmd(
                SnmpEngine(),
                CommunityData(community),
                UdpTransportTarget((ip, port), timeout=2.0, retries=1),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )
        )

        if error_indication:
            return {"success": False, "error": str(error_indication)}
        if error_status:
            return {
                "success": False,
                "error": f"{error_status.prettyPrint()} at {error_index and var_binds[int(error_index) - 1][0] or '?'}",
            }

        value = var_binds[0][1]
        value_type = type(value).__name__
        detected_type = "STRING"
        if "Integer" in value_type or "Gauge" in value_type or "Counter" in value_type:
            detected_type = "INTEGER"
        elif "Float" in value_type:
            detected_type = "FLOAT"

        return {
            "success": True,
            "value": str(value),
            "detectedType": detected_type,
            "rawType": value_type,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
