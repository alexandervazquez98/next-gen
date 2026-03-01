from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

# Postgres Connection
POSTGRES_USER = os.getenv("POSTGRES_USER", "nexgen_admin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "nexgen_password")
POSTGRES_DB = os.getenv("POSTGRES_DB", "nexgen_auth")
# Host is 'postgres' when running inside container, 'localhost' if running locally
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres") 
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

SQLALCHEMY_DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# Determine if we are running locally or in docker for connection string adjustment if needed (simplified here)
# If running outside docker (development), might need localhost
if os.getenv("RUNNING_LOCALLY", "false").lower() == "true":
     SQLALCHEMY_DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@localhost:{POSTGRES_PORT}/{POSTGRES_DB}"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_pg_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
