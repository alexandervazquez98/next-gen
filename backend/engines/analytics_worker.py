import time
import os
import schedule
from neo4j import GraphDatabase
import random

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

def run_analytics():
    print("Running AI Diagnostics...")
    try:
        with driver.session() as session:
            # Simple Logic: Find Critical nodes and 'auto-fix' them occasionally
            result = session.run("MATCH (n:CI {status: 'CRITICAL'}) RETURN n.id as id")
            critical_nodes = [record["id"] for record in result]
            
            for node_id in critical_nodes:
                if random.random() > 0.7: # 30% chance to auto-fix
                    print(f"AI Agent auto-resolving issue on {node_id}...")
                    session.run("""
                        MATCH (n:CI {id: $id})
                        SET n.status = 'OK', n.cpu_load = 40, n.resolution = 'Auto-scaled by AI'
                    """, id=node_id)
    except Exception as e:
        print(f"Error during analytics job: {e}")

schedule.every(30).seconds.do(run_analytics)

if __name__ == "__main__":
    print("Analytics Engine Starting...")
    verify_connection()
    print("Analytics Engine Running")
    
    # Run once immediately
    run_analytics()
    
    while True:
        schedule.run_pending()
        time.sleep(1)
