import os
from neo4j import GraphDatabase
from dotenv import load_dotenv
import pandas as pd

load_dotenv()
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "nexgen_password")

def audit_metrics():
    print(f"\n--- AUDITING METRIC RELATIONSHIPS IN NEO4J ({NEO4J_URI}) ---\n")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    try:
        with driver.session() as session:
            # 1. Overview of All Defined Metrics
            print("1. DEFINED METRICS (MetricDef Nodes):")
            res = session.run("MATCH (m:MetricDef) RETURN m.id, m.protocol, m.unit, m.name")
            metrics = [r.data() for r in res]
            if metrics:
                df = pd.DataFrame(metrics)
                print(df.to_string(index=False))
            else:
                print("   [!] No Metric Definitions found.")

            print("\n" + "-"*60 + "\n")

            # 2. CI -> Metric Attachments
            print("2. CI ASSIGNMENTS (Which CI has which Metric?):")
            res = session.run("""
                MATCH (n:CI)-[:HAS_METRIC]->(m:MetricDef)
                RETURN n.id as CI_ID, n.name as CI_Name, collect(m.id) as Assigned_Metrics
                ORDER BY n.id
            """)
            assignments = [r.data() for r in res]
            if assignments:
                df = pd.DataFrame(assignments)
                print(df.to_string(index=False))
            else:
                print("   [!] No CIs have assigned metrics.")

            print("\n" + "-"*60 + "\n")

            # 3. Orphaned CIs (CIs with NO metrics)
            print("3. ORPHANED CIs (No Metrics Assigned):")
            res = session.run("""
                MATCH (n:CI)
                WHERE NOT (n)-[:HAS_METRIC]->(:MetricDef)
                RETURN n.id as CI_ID, n.name as CI_Name, n.ip as IP, n.layer as Layer
            """)
            orphans = [r.data() for r in res]
            if orphans:
                df = pd.DataFrame(orphans)
                print(df.to_string(index=False))
            else:
                print("   [OK] All CIs have at least one metric.")

    finally:
        driver.close()
    print("\n--- END OF AUDIT ---\n")

if __name__ == "__main__":
    audit_metrics()
