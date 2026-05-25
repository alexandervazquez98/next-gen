import os
import platform
import time
import schedule
import random
import sys
import subprocess
from datetime import datetime
from typing import Any, Dict

# Add root and backend to python path to verify imports work
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../backend'))

import logging

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)
from repositories.metric_repo import insert_metric_value, bulk_insert_metrics
from postgres_db import SessionLocal
from config import get_icmp_settings, get_polling_pipeline_settings
from services.polling_event_lifecycle import (
    EVENT_TYPE_COLLECTION_FAILURE,
    FAILURE_FAMILY_SNMP_NO_RESPONSE,
    SOURCE_PROTOCOL_SNMP,
    is_snmp_no_response_failure,
    normalized_protocol,
)

# SNMP Support
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

# Connection
URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

driver = GraphDatabase.driver(URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

def verify_connection():
    max_retries = 60
    for i in range(max_retries):
        try:
            driver.verify_connectivity()
            print("Connected to Neo4j!")
            return
        except Exception as e:
            print(f"Waiting for Neo4j... ({i+1}/{max_retries})")
            time.sleep(2)
    raise Exception("Could not connect to Neo4j after multiple retries")

# Module-level consecutive failure counter for ICMP debounce (keyed by node_id)
# NOTE: This dict grows unbounded. If a node is deleted from Neo4j, its entry remains.
# For production, consider persisting this to Neo4j or using a bounded cache (e.g. LRU).
_consecutive_failures: Dict[str, int] = {}


def fetch_icmp_ping(ip: str, timeout_ms: int = 3000, retries: int = 2) -> float:
    """Perform ICMP ping with configurable timeout and retry.

    Args:
        ip: Target IP address.
        timeout_ms: Timeout per ping attempt in milliseconds.
        retries: Number of additional attempts after initial failure.

    Returns:
        1.0 if any ping attempt succeeds, 0.0 if all attempts fail.
    """
    attempts = retries + 1
    system = platform.system().lower()

    for attempt in range(attempts):
        try:
            if system == 'windows':
                cmd = ['ping', '-n', '1', '-w', str(timeout_ms), ip]
            else:
                timeout_sec = max(1, timeout_ms // 1000)
                cmd = ['ping', '-c', '1', '-W', str(timeout_sec), ip]
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if result.returncode == 0:
                return 1.0
        except OSError as e:
            logger.warning(f"Ping attempt {attempt + 1}/{attempts} failed for {ip}: {e}")
            continue
        except subprocess.TimeoutExpired as e:
            logger.warning(f"Ping attempt {attempt + 1}/{attempts} timed out for {ip}: {e}")
            continue
    return 0.0

def fetch_snmp_value(ip, community, oid, port=161, include_status=False):
    """Perform a real SNMP GET.

    By default this preserves the legacy float/None contract. The active worker
    requests structured status so only real timeout/no-data failures become
    SNMP_NO_RESPONSE collection-failure events.
    """
    def result(value, status, error):
        return (value, status, error) if include_status else value

    if not SNMP_AVAILABLE:
        return result(None, "ERROR", "PySNMP not installed")

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
            error_message = str(error_indication)
            status = (
                "TIMEOUT"
                if is_snmp_no_response_failure(SOURCE_PROTOCOL_SNMP, "ERROR", {"message": error_message})
                else "ERROR"
            )
            return result(None, status, error_message)
        if error_status:
            error = f"{error_status.prettyPrint()} at {error_index and var_binds[int(error_index) - 1][0] or '?'}"
            return result(None, "ERROR", error)

        value = var_binds[0][1]
        try:
            return result(float(value), "OK", None)
        except (ValueError, TypeError) as exc:
            return result(None, "ERROR", str(exc))
    except Exception as exc:
        return result(None, "ERROR", str(exc))


def _coerce_snmp_fetch_result(raw: Any) -> tuple[float | None, str, str | None]:
    if isinstance(raw, tuple) and len(raw) == 3:
        value, status, error = raw
        return value, str(status or "ERROR"), None if error is None else str(error)
    if raw is None:
        return None, "TIMEOUT", "No SNMP response received before timeout"
    return raw, "OK", None


def _log_observe_only_cycle(settings, metrics_count, collected_count, failed_count, duration, jobs_per_min):
    """Emit PR1 baseline telemetry without changing polling behavior."""
    if not settings.pipeline_observe_only:
        return
    logger.info(
        "polling_observe_cycle",
        extra={
            "polling": {
                "metrics_processed": metrics_count,
                "metrics_collected": collected_count,
                "metrics_failed": failed_count,
                "cycle_duration": round(duration, 2),
                "jobs_per_min": jobs_per_min,
                "pipeline_observe_only": True,
            }
        },
    )


def _dedupe_snmp_collection_failures(failures):
    deduped = {}
    for row in failures:
        key = (row.get("node_id"), row.get("metric_id"), row.get("failure_family"))
        deduped[key] = row
    return list(deduped.values())


def _refresh_snmp_collection_failures(session, failures):
    failures = _dedupe_snmp_collection_failures(failures)
    if not failures:
        return
    session.run("""
        UNWIND $failures AS row
        MATCH (n:CI {id: row.node_id})
        MATCH (m:MetricDef {id: row.metric_id})
        OPTIONAL MATCH (existing:Event {ci_id: row.node_id, metric_id: row.metric_id})
        WHERE existing.status IN ['OPEN', 'ACK', 'RECOVERED']
          AND (
            existing.event_type = 'COLLECTION_FAILURE'
            OR (existing.event_type IS NULL AND existing.message STARTS WITH 'Metric Collection Failed:')
          )
          AND (existing.failure_family = 'SNMP_NO_RESPONSE' OR existing.failure_family IS NULL)
          AND (existing.source_protocol IS NULL OR toUpper(existing.source_protocol) = row.source_protocol)
        WITH row, n, m, head(collect(existing)) AS existing
        FOREACH (_ IN CASE WHEN existing IS NULL THEN [1] ELSE [] END |
            CREATE (created:Event {
                id: randomUUID(), ci_id: row.node_id, metric_id: row.metric_id,
                status: 'OPEN', severity: row.severity, message: row.message,
                event_type: row.event_type, failure_family: row.failure_family,
                source_protocol: row.source_protocol, created_at: datetime(),
                last_seen: datetime(), ack: false, correlation_type: 'ROOT',
                root_cause_ci_id: row.node_id
            })
            MERGE (n)-[:HAS_EVENT]->(created)
            MERGE (created)-[:TRIGGERED_BY]->(m)
        )
        FOREACH (_ IN CASE WHEN existing IS NULL THEN [] ELSE [1] END |
            SET existing.status = 'OPEN', existing.severity = row.severity,
                existing.message = row.message, existing.last_seen = datetime(),
                existing.recovered_at = NULL, existing.ack = false,
                existing.event_type = row.event_type,
                existing.failure_family = row.failure_family,
                existing.source_protocol = row.source_protocol
            MERGE (n)-[:HAS_EVENT]->(existing)
            MERGE (existing)-[:TRIGGERED_BY]->(m)
        )
    """, failures=failures)


def _recover_snmp_collection_failures(session, updates):
    recoveries = [u for u in updates if str(u.get("protocol") or "").upper() == SOURCE_PROTOCOL_SNMP]
    if not recoveries:
        return
    session.run("""
        UNWIND $recoveries AS row
        MATCH (:CI {id: row.node_id})-[:HAS_EVENT]->(e:Event {metric_id: row.metric_id})
        WHERE e.status IN ['OPEN', 'ACK']
          AND (
            e.event_type = 'COLLECTION_FAILURE'
            OR (e.event_type IS NULL AND e.message STARTS WITH 'Metric Collection Failed:')
          )
          AND (e.failure_family = 'SNMP_NO_RESPONSE' OR e.failure_family IS NULL)
          AND (e.source_protocol IS NULL OR toUpper(e.source_protocol) = row.protocol)
        SET e.status = 'RECOVERED',
            e.recovered_at = datetime(),
            e.message = 'Metric collection recovered. Latest sample collected by legacy SNMP worker'
        WITH e
        CALL {
            WITH e
            MATCH (pe:Event)-[:TRIGGERED_BY]->(m:MetricDef)
            WHERE pe.root_cause_ci_id = e.ci_id
              AND pe.correlation_type = 'PROPAGATED'
              AND pe.status IN ['OPEN', 'ACK']
              AND coalesce(m.can_propagate, true) = true
            SET pe.status = 'RECOVERED', pe.recovered_at = datetime()
            RETURN count(pe) AS propagated_recovered
        }
        RETURN e
    """, recoveries=recoveries)


def poll_snmp():
    start_time = time.time()
    polling_settings = get_polling_pipeline_settings()
    print(f"[{datetime.now().isoformat()}] Starting Real-World Polling Cycle...")
    db = SessionLocal()
    metrics_to_save = []
    latest_updates = []
    failure_updates = []
    metrics_count = 0
    failed_count = 0
    try:
        with driver.session() as session:
            # Enhanced query: Get CI credentials and Metric metadata
            result = session.run("""
                MATCH (n:CI)-[r:HAS_METRIC]->(m:MetricDef)
                WITH n, r, m, 
                     coalesce(m.polling_interval, 60) as interval,
                     coalesce(r.last_polled, datetime({year:1970})) as last_p
                WHERE duration.between(last_p, datetime()).seconds >= interval
                RETURN n.id as node_id, n.ip as ip, 
                       coalesce(n.snmp_community, 'public') as community,
                       coalesce(n.snmp_port, 161) as port,
                       m.id as metric_id, m.protocol as protocol, m.oid as oid,
                       interval
            """)
            
            # Use iterator to process one by one
            for record in result:
                metrics_count += 1
                node_id = record["node_id"]
                mid = record["metric_id"]
                protocol = normalized_protocol(record["protocol"])
                ip = record["ip"]
                
                if not ip:
                    print(f"Skipping {node_id}: No IP address.")
                    continue

                val = None
                icmp_settings = get_icmp_settings()
                if protocol == "ICMP":
                    val = fetch_icmp_ping(ip, timeout_ms=icmp_settings.timeout_ms, retries=icmp_settings.retries)
                    # Debounce logic: track consecutive failures per node
                    if val == 0:
                        _consecutive_failures[node_id] = _consecutive_failures.get(node_id, 0) + 1
                        if _consecutive_failures[node_id] >= icmp_settings.debounce_count:
                            # DOWN event: store CRITICAL status and reset counter
                            session.run(
                                "MATCH (n:CI {id: $id}) SET n.status = $status, n.last_seen = datetime()",
                                id=node_id, status="CRITICAL"
                            )
                            _consecutive_failures[node_id] = 0
                            # Don't record metric for this cycle (debounce suppressed it)
                            val = None
                        else:
                            # Below threshold: suppress metric recording until threshold
                            val = None
                    else:
                        # Success: reset counter and proceed normally
                        _consecutive_failures[node_id] = 0
                snmp_status = "OK"
                snmp_error = None
                if protocol == SOURCE_PROTOCOL_SNMP and record["oid"]:
                    val, snmp_status, snmp_error = _coerce_snmp_fetch_result(
                        fetch_snmp_value(
                            ip,
                            record["community"],
                            record["oid"],
                            int(record["port"]),
                            include_status=True,
                        )
                    )
                
                if val is not None:
                    metrics_to_save.append({
                        "node_id": node_id,
                        "metric_id": mid,
                        "value": val,
                        "time": datetime.utcnow()
                    })

                    latest_updates.append({
                        "node_id": node_id,
                        "metric_id": mid,
                        "value": val,
                        "protocol": protocol,
                    })
                else:
                    failed_count += 1
                    if is_snmp_no_response_failure(
                        protocol,
                        snmp_status,
                        {"message": snmp_error},
                    ):
                        failure_updates.append({
                            "node_id": node_id,
                            "metric_id": mid,
                            "severity": "WARNING",
                            "message": f"Metric Collection Failed: {snmp_error or 'No SNMP response received before timeout'}",
                            "event_type": EVENT_TYPE_COLLECTION_FAILURE,
                            "failure_family": FAILURE_FAMILY_SNMP_NO_RESPONSE,
                            "source_protocol": SOURCE_PROTOCOL_SNMP,
                        })

            # Update collector status in Neo4j
            duration_current = time.time() - start_time
            jobs_per_min = round((len(metrics_to_save) / duration_current) * 60, 1) if duration_current > 0 else 0.0
            session.run("""
                MERGE (c:CollectorStatus {id: 'main'})
                SET c.last_run = datetime(),
                    c.status = 'RUNNING',
                    c.cis_monitored = $cis,
                    c.metrics_collected = $collected,
                    c.metrics_failed = $failed,
                    c.cycle_duration = $duration,
                    c.jobs_per_min = $jobs_per_min
            """, cis=metrics_count, collected=len(metrics_to_save), failed=failed_count, duration=round(duration_current, 2), jobs_per_min=jobs_per_min)
            _log_observe_only_cycle(
                polling_settings,
                metrics_count,
                len(metrics_to_save),
                failed_count,
                duration_current,
                jobs_per_min,
            )
            _refresh_snmp_collection_failures(session, failure_updates)

            # Perform Bulk Insert at the end of the cycle. Only publish latest
            # values to Neo4j after Timescale persistence succeeds, so the UI
            # does not advertise samples that failed durable storage.
            if metrics_to_save:
                bulk_insert_metrics(db, metrics_to_save)
                for update in latest_updates:
                    if update["protocol"].upper() == "ICMP" and update["value"] == 1.0:
                        session.run(
                            "MATCH (n:CI {id: $id}) SET n.status = $status, n.last_seen = datetime()",
                            id=update["node_id"],
                            status="OK",
                        )
                    session.run("""
                        MATCH (n:CI {id: $nid})-[r:HAS_METRIC]->(m:MetricDef {id: $mid})
                        SET r.last_polled = datetime(),
                            r.last_value = $val,
                            r.last_updated = datetime(),
                            r.status = $status,
                            r.last_message = $msg
                    """, nid=update["node_id"], mid=update["metric_id"], val=update["value"], status="OK", msg="Latest sample collected by legacy SNMP worker")
                _recover_snmp_collection_failures(session, latest_updates)
                print(f"[{datetime.now().isoformat()}] Bulk saved {len(metrics_to_save)} metrics to TimescaleDB.")

        duration = time.time() - start_time
        if metrics_count > 0:
            print(f"[{datetime.now().isoformat()}] Cycle Complete: {metrics_count} metrics processed ({failed_count} failed) in {duration:.2f}s.")

    except Exception as e:
        print(f"Error during dynamic polling cycle: {e}")
    finally:
        db.close()

def job():
    try:
        polling_settings = get_polling_pipeline_settings()
        if polling_settings.snmp_leased_worker_enabled:
            from polling.snmp_worker import run_leased_snmp_worker_once

            db = SessionLocal()
            try:
                run_leased_snmp_worker_once(db, settings=polling_settings)
            finally:
                db.close()
            return
        poll_snmp()
    except Exception as e:
        print(f"Error in polling job: {e}")

# Run once every 10 seconds
schedule.every(10).seconds.do(job)

if __name__ == "__main__":
    print("NEX-GEN Real-World SNMP Engine Starting...")
    if not SNMP_AVAILABLE:
        print("WARNING: PySNMP not found. SNMP polling will be unavailable.")
    verify_connection()
    print("Engine Running. Waiting for scheduled tasks...")
    while True:
        schedule.run_pending()
        time.sleep(1)
