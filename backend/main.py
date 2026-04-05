from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import logging
import asyncio
import os
import shutil
import platform
from database import get_db, verify_connection
from services.snmp_service import snmp_collector_loop, get_collector_status
from seed_admin import seed_admin
from seed_roles import seed_roles

# Router Imports
from routers import auth, users, roles, nodes, metrics, catalog, links, events

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="NEX-GEN API",
    version="1.4.0",
    description="API for CMDB, Monitoring, and AIOps Platform",
)

# Include Routers
app.include_router(auth.router)  # /api/auth (defined in router)
app.include_router(users.router)  # /api/users
app.include_router(roles.router)  # /api/roles
app.include_router(nodes.router)  # /api/nodes
app.include_router(metrics.router)  # /api/metrics
app.include_router(catalog.router)  # /api/categories, /api/hardware, /api/owners
app.include_router(links.router)  # /api/links
app.include_router(events.router)  # /api/events


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler to capture unhandled exceptions and return standard JSON error responses.
    """
    logger.error(f"Global error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__},
    )


@app.on_event("startup")
async def startup_event():
    """
    Application startup event handler.
    1. Verifies database connectivity.
    2. Initializes default schema/metrics.
    3. Starts background tasks (e.g., SNMP Collector).
    4. Seeds default admin user.
    """
    logger.info("Starting up... Verifying DB connection")
    verify_connection()

    # Initialize TimescaleDB Hypertables
    # Initialize TimescaleDB Hypertables
    try:
        from postgres_db import SessionLocal, engine, Base
        from repositories.metric_repo import create_hypertable
        from models.timescale_models import MetricValue  # Import to register model

        # Create Tables
        Base.metadata.create_all(bind=engine)

        # Inline migration: add 'tier' column if it doesn't exist (safe for existing DBs)
        try:
            with engine.connect() as conn:
                conn.execute(
                    __import__("sqlalchemy").text(
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS tier VARCHAR DEFAULT 'T1'"
                    )
                )
                conn.commit()
        except Exception as migration_err:
            logger.warning(f"Migration warning (tier column): {migration_err}")

        db = SessionLocal()
        create_hypertable(db)
        db.close()
    except Exception as e:
        logger.error(f"Failed to initialize TimescaleDB: {e}")

    # Ensure Defaults
    pass

    # Seed Admin
    try:
        await seed_admin()
    except Exception as e:
        logger.error(f"Failed to seed admin: {e}")

    # Seed Roles
    try:
        await seed_roles()
    except Exception as e:
        logger.error(f"Failed to seed roles: {e}")

    # Start Background SNMP Collector
    asyncio.create_task(snmp_collector_loop())


@app.get("/")
def read_root():
    """Health check endpoint."""
    return {"status": "System Operational", "module": "Backend API v1.4 (Refactored)"}


@app.get("/api/system/status")
def get_system_status():
    """
    Get internal system health metrics (CPU, RAM, Disk, Services).
    """
    # 1. System Resources (OS Independent if possible, or Linux specific)
    cpu_percent = 0.0
    ram_percent = 0.0
    disk_percent = 0.0

    try:
        # Load Average (Unix)
        if hasattr(os, "getloadavg"):
            load = os.getloadavg()
            # Approximation: Load / Cores * 100 (Simplified)
            cpu_percent = min((load[0] / os.cpu_count()) * 100, 100)
    except:
        pass

    try:
        # Disk Usage
        total, used, free = shutil.disk_usage("/")
        disk_percent = (used / total) * 100
    except:
        pass

    # RAM (Linux /proc/meminfo parsing)
    if platform.system() == "Linux":
        try:
            with open("/proc/meminfo", "r") as f:
                lines = f.readlines()
                mem_total = int(lines[0].split()[1])
                mem_free = int(lines[1].split()[1])  # MemFree
                mem_available = int(lines[2].split()[1])  # MemAvailable usually
                ram_percent = ((mem_total - mem_available) / mem_total) * 100
        except:
            pass

    # 2. Service Status
    neo4j_status = "UNKNOWN"
    try:
        verify_connection()
        neo4j_status = "CONNECTED"
    except:
        neo4j_status = "DISCONNECTED"

    collector = get_collector_status()

    return {
        "cpu": round(cpu_percent, 1),
        "ram": round(ram_percent, 1),
        "disk": round(disk_percent, 1),
        "neo4j": neo4j_status,
        "collector": collector,
    }
