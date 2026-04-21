import time
import os
import schedule
import random
import sys
import subprocess
from datetime import datetime

# Add root and backend to python path to verify imports work
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../backend'))

from neo4j import GraphDatabase
from backend.repositories.metric_repo import insert_metric_value
from backend.postgres_db import SessionLocal

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

def fetch_icmp_ping(ip):
    """Perform a real ICMP ping."""
    try:
        ping_flag = "-n" if os.name == "nt" else "-c"
        # Run ping with 1 packet, 1s timeout
        result = subprocess.run(
            ["ping", ping_flag, "1", "-w", "1000", ip],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode == 0:
            return 1.0
        return 0.0
    except Exception:
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

def poll_snmp():
    start_time = time.time()
    print(f"[{datetime.now().isoformat()}] Starting Real-World Polling Cycle...")
    db = SessionLocal()
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
            
            # Use iterator to process one by one, avoiding OOM for large CI sets
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
                if protocol == "ICMP" or "ping" in mid.lower():
                    val = fetch_icmp_ping(ip)
                elif protocol == "SNMP" and record["oid"]:
                    val = fetch_snmp_value(ip, record["community"], record["oid"], int(record["port"]))
                
                if val is not None:
                    insert_metric_value(db, node_id, mid, val)
                    
                    if mid == 'status_code' or 'ping' in mid.lower():
                        status = 'OK' if val > 0 else 'CRITICAL'
                        session.run("MATCH (n:CI {id: $id}) SET n.status = $status, n.last_seen = datetime()", 
                                   id=node_id, status=status)
                    
                    # Success: Update last_polled to respect the interval
                    session.run("""
                        MATCH (n:CI {id: $nid})-[r:HAS_METRIC]->(m:MetricDef {id: $mid})
                        SET r.last_polled = datetime()
                    """, nid=node_id, mid=mid)
                else:
                    failed_count += 1
                    # Fail: We DON'T update last_polled here, so it stays eligible for polling 
                    # in the next 10s engine loop (retry logic).

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
