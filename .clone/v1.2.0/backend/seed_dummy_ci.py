from neo4j import GraphDatabase
import os

URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
AUTH = ("neo4j", "nexgen_password")

def seed_data():
    driver = GraphDatabase.driver(URI, auth=AUTH)
    with driver.session() as session:
        print("Seeding dummy CIS...")
        session.run("""
            MERGE (n:CI {id: 'router-test-01'})
            SET n.type = 'INFRASTRUCTURE',
                n.name = 'Test Router',
                n.ip = '127.0.0.1',
                n.status = 'OK',
                n.brand = 'Cisco',
                n.model = 'ISR4000'
        """)
        print("Seeded 'router-test-01'")
    driver.close()

if __name__ == "__main__":
    seed_data()
