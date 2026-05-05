import sys
import os

# Add backend directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from neo4j import GraphDatabase
from sqlalchemy.orm import Session
from postgres_db import SessionLocal, engine, Base
from models.sql_models import User as PgUser
from dotenv import load_dotenv

load_dotenv()

# Neo4j Connection
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_AUTH = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password"))

def migrate_users():
    print("🚀 Starting User Migration from Neo4j to PostgreSQL...")
    
    # 1. Init Postgres Tables
    Base.metadata.create_all(bind=engine)
    pg_db: Session = SessionLocal()
    
    # 2. Connect to Neo4j
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    
    try:
        # 3. Fetch all users from Neo4j
        query = "MATCH (u:User) RETURN u"
        results, _, _ = driver.execute_query(query)
        
        count = 0
        for record in results:
            node = record["u"]
            data = dict(node)
            
            username = data.get("username")
            if not username:
                continue
                
            # Check if exists in PG
            existing = pg_db.query(PgUser).filter(PgUser.username == username).first()
            if existing:
                print(f"⚠️ User {username} already exists in Postgres. Skipping.")
                continue
            
            # Map Fields
            new_user = PgUser(
                username=username,
                hashed_password=data.get("password", ""), # Caution: Ensure this is the hashed one
                role=data.get("role", "VIEWER"),
                permissions=data.get("permissions", []),
                allowed_locations=data.get("allowed_locations", []),
                allowed_ci_types=data.get("allowed_ci_types", []),
                phone=data.get("phone"),
                email=data.get("email"),
                is_active=not data.get("disabled", False),
                force_password_change=data.get("force_password_change", False)
            )
            
            pg_db.add(new_user)
            count += 1
            
        pg_db.commit()
        print(f"✅ Successfully migrated {count} users.")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        pg_db.rollback()
    finally:
        driver.close()
        pg_db.close()

if __name__ == "__main__":
    migrate_users()
