import time
import os
import schedule
import random
import sys

# Add root and backend to python path to verify imports work
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../backend'))

from neo4j import GraphDatabase
from backend.repositories.metric_repo import insert_metric_value
from backend.postgres_db import SessionLocal

# Connection
URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
AUTH = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password"))

driver = GraphDatabase.driver(URI, auth=AUTH)

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

def poll_snmp():
    print("Starting Dynamic SNMP Polling Cycle...")
    db = SessionLocal()
    try:
        with driver.session() as session:
            # Get CIs and their specific assigned metrics with their intervals
            # Logic: Only pick those where (now - last_polled) >= polling_interval
            result = session.run("""
                MATCH (n:CI)-[r:HAS_METRIC]->(m:MetricDef)
                WITH n, r, m, 
                     coalesce(m.polling_interval, 60) as interval,
                     coalesce(r.last_polled, datetime({year:1970})) as last_p
                WHERE duration.between(last_p, datetime()).seconds >= interval
                RETURN n.id as node_id, m.id as metric_id, interval
            """)
            
            records = list(result)
            if not records:
                print("No metrics due for polling in this cycle.")
                return

            print(f"Polling {len(records)} due metrics.")

            for record in records:
                node_id = record["node_id"]
                mid = record["metric_id"]
                
                print(f"Polling {node_id} for {mid} (Interval: {record['interval']}s)")
                
                # Simulation Logic
                val = 0.0
                if mid == 'cpu_usage':
                    val = float(random.randint(10, 95))
                elif mid == 'status_code':
                    val = 1.0 # Always UP for sim
                elif 'ping' in mid.lower():
                    val = float(random.randint(20, 100)) # ms latency
                else:
                    val = float(random.randint(0, 100))
                
                # Update History in TimescaleDB
                insert_metric_value(db, node_id, mid, val)
                
                # Update last_polled on the relationship in Neo4j
                session.run("""
                    MATCH (n:CI {id: $nid})-[r:HAS_METRIC]->(m:MetricDef {id: $mid})
                    SET r.last_polled = datetime()
                """, nid=node_id, mid=mid)
                
                # Update real-time props if needed
                if mid == 'cpu_usage':
                    status = 'CRITICAL' if val > 90 else 'OK'
                    session.run("""
                        MATCH (n:CI {id: $id}) 
                        SET n.cpu_load = $cpu, n.status = $status, n.last_seen = datetime()
                    """, id=node_id, cpu=val, status=status)

    except Exception as e:
        print(f"Error during dynamic polling cycle: {e}")
    finally:
        db.close()

def job():
    try:
        poll_snmp()
    except Exception as e:
        print(f"Error in polling job: {e}")

# Run every 10 seconds
schedule.every(10).seconds.do(job)

if __name__ == "__main__":
    print("SNMP Engine Starting (TimescaleDB Enabled)...")
    verify_connection()
    print("SNMP Engine Running")
    while True:
        schedule.run_pending()
        time.sleep(1)
