import os
import platform
import time
import schedule
import random
import sys
import subprocess
from datetime import datetime
from typing import Dict

# Add root and backend to python path to verify imports work
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../backend'))

import logging

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)
from repositories.metric_repo import insert_metric_value, bulk_insert_metrics
from postgres_db import SessionLocal
from config import get_icmp_settings, get_polling_pipeline_settings

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
            logger.warning(f"Ping failed for {ip}: {e}")
            return 0.0
        except subprocess.TimeoutExpired:
            return 0.0
    return 0.0

def fetch_snmp_value(ip, community, oid, port=161):
    """Perform a real SNMP GET."""
    if not SNMP_AVAILABLE:
        return None

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

        if error_indication or error_status:
            return None

        value = var_binds[0][1]
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    except Exception:
        return None


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


def poll_snmp():
    start_time = time.time()
    polling_settings = get_polling_pipeline_settings()
    print(f"[{datetime.now().isoformat()}] Starting Real-World Polling Cycle...")
    db = SessionLocal()
    metrics_to_save = []
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
                protocol = record["protocol"]
                ip = record["ip"]
                
                if not ip:
                    print(f"Skipping {node_id}: No IP address.")
                    continue

                val = None
                icmp_settings = get_icmp_settings()
                if protocol.upper() == "ICMP":
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
                elif protocol == "SNMP" and record["oid"]:
                    val = fetch_snmp_value(ip, record["community"], record["oid"], int(record["port"]))
                
                if val is not None:
                    metrics_to_save.append({
                        "node_id": node_id,
                        "metric_id": mid,
                        "value": val,
                        "time": datetime.utcnow()
                    })

                    # Update last_polled to respect the interval
                    session.run("""
                        MATCH (n:CI {id: $nid})-[r:HAS_METRIC]->(m:MetricDef {id: $mid})
                        SET r.last_polled = datetime()
                    """, nid=node_id, mid=mid)
                else:
                    failed_count += 1

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

            # Perform Bulk Insert at the end of the cycle
            if metrics_to_save:
                bulk_insert_metrics(db, metrics_to_save)
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
