from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv()

URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
AUTH = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password"))

driver = GraphDatabase.driver(URI, auth=AUTH)

def get_db():
    if not driver:
        # Re-connect if needed logic here or handled by driver
        pass
    return driver

def close_db():
    if driver:
        driver.close()

import time

def close_db():
    if driver:
        driver.close()

def verify_connection():
    max_retries = 30
    retry_delay = 2
    
    for i in range(max_retries):
        try:
            driver.verify_connectivity()
            print("Neo4j Connection Verified")
            return
        except Exception as e:
            print(f"Neo4j Connection Failed (Attempt {i+1}/{max_retries}): {e}")
            time.sleep(retry_delay)
    
    print("Neo4j Connection Failed after max retries")
    raise Exception("Could not connect to Neo4j Database")
