from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import asyncio
import os
import shutil
import platform
from datetime import datetime
from database import get_db, verify_connection

# Global start time to track system reboots/restarts
STARTUP_TIME = datetime.now().isoformat()
from services.snmp_service import snmp_collector_loop, get_collector_status
from seed_admin import seed_admin
from seed_roles import seed_roles
from middleware.rate_limit import RateLimitMiddleware

# APScheduler for backup scheduling
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Global scheduler instance
backup_scheduler = AsyncIOScheduler()


def schedule_daily_backup() -> None:
    """
    Schedule the daily automated backup job based on PostgreSQL config.
    Reads schedule_time from backup_config, defaults to 06:00 (dawn).
    """
    from services.backup_service import get_backup_config, trigger_scheduled_backup

    config = get_backup_config()

    # Parse schedule time (HH:MM format)
    schedule_parts = config.get("scheduled_time", "06:00").split(":")
    hour = int(schedule_parts[0])
    minute = int(schedule_parts[1])

    # Clear existing jobs and add new one
    backup_scheduler.remove_all_jobs()

    if config.get("enabled", True):
        backup_scheduler.add_job(
            trigger_scheduled_backup,
            trigger=CronTrigger(hour=hour, minute=minute),
            id="daily_backup",
            name="Daily PostgreSQL Backup",
            replace_existing=True,
        )
        logger.info(f"Scheduled daily backup at {hour:02d}:{minute:02d}")
    else:
        logger.info("Daily backup is disabled in config")


# Router Imports
from routers import auth, users, roles, nodes, metrics, catalog, links, events, backup, dictionaries, cis, cli

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="NEX-GEN API",
    version="1.4.0",
    description="API for CMDB, Monitoring, and AIOps Platform",
    redirect_slashes=False,
)

# CORS middleware — must come before route registration
_frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "X-Requested-With"],
)

# Register rate limiting middleware
app.add_middleware(RateLimitMiddleware)


def _ensure_refresh_token_schema_migration(engine) -> None:
    """Add backwards-compatible columns for session-policy-backed refresh tokens."""
    try:
        with engine.connect() as conn:
            sql = __import__("sqlalchemy").text
            conn.execute(sql("ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS session_id VARCHAR"))
            conn.execute(sql("ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS policy_profile VARCHAR DEFAULT 'standard'"))
            conn.execute(sql("ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMP"))
            conn.execute(sql("ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS rotated_at TIMESTAMP"))
            conn.execute(sql("ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS replaced_by_token_id INTEGER REFERENCES refresh_tokens(id)"))
            conn.execute(sql("ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS revoked_reason VARCHAR"))
            conn.execute(sql("ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS stale_recovery_count INTEGER DEFAULT 0"))
            # Backfill existing rows so runtime non-null assumptions are still safe.
            conn.execute(sql("UPDATE refresh_tokens SET session_id = COALESCE(session_id, CONCAT('legacy-', id::text)) WHERE session_id IS NULL"))
            conn.execute(sql("UPDATE refresh_tokens SET policy_profile = COALESCE(policy_profile, 'standard') WHERE policy_profile IS NULL"))
            conn.execute(sql("UPDATE refresh_tokens SET last_activity_at = COALESCE(last_activity_at, created_at, NOW()) WHERE last_activity_at IS NULL"))
            conn.execute(sql("UPDATE refresh_tokens SET stale_recovery_count = COALESCE(stale_recovery_count, 0) WHERE stale_recovery_count IS NULL"))
            conn.execute(sql("CREATE INDEX IF NOT EXISTS ix_refresh_tokens_session_id ON refresh_tokens (session_id)"))
            conn.execute(sql("CREATE INDEX IF NOT EXISTS ix_refresh_tokens_policy_profile ON refresh_tokens (policy_profile)"))
            conn.commit()
    except Exception as migration_err:
        logger.warning(f"Migration warning (refresh_tokens session-policy columns): {migration_err}")
"""
ROUTING ARCHITECTURE CONVENTIONS:
1. Centralized Prefix: All routers are included with the '/api' prefix here in main.py.
2. No Trailing Slashes: Routes are defined WITHOUT trailing slashes to maintain consistency.
3. Pragmatic REST for Bulk Ops: 
   - Single resource mutations use standard verbs (GET, POST, PUT, DELETE).
   - Bulk/Mass operations use POST for compatibility with corporate proxies and firewalls 
     that often intercept or misinterpret PUT/DELETE on batch endpoints.
4. Static vs Dynamic Priority: Static routes (like /bulk-update) MUST be registered 
   before dynamic routes (like /{id}) in their respective routers to prevent collisions.
"""

# Include Routers with global /api prefix
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(roles.router, prefix="/api")
app.include_router(nodes.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(catalog.router, prefix="/api")
app.include_router(links.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(backup.router, prefix="/api")
app.include_router(dictionaries.router, prefix="/api")
app.include_router(cis.router, prefix="/api")
app.include_router(cli.router, prefix="/api")


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
    3. Starts background tasks (e.g., SNMP Collector, Backup Scheduler).
    4. Seeds default admin user.
    """
    logger.info("Starting up... Verifying DB connection")
    verify_connection()

    # Initialize TimescaleDB Hypertables
    try:
        from postgres_db import SessionLocal, engine, Base
        from repositories.metric_repo import create_hypertable
        from models.timescale_models import MetricValue  # Import to register model
        from models.rate_limit_attempt import RateLimitAttempt  # Import to register model

        # Create Tables (includes backup_config, backup_history, and rate_limit_attempts)
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

        _ensure_refresh_token_schema_migration(engine)

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
    disable_collector = os.getenv("DISABLE_BACKEND_COLLECTOR", "false").lower() in ("true", "1", "yes", "on")
    if not disable_collector:
        asyncio.create_task(snmp_collector_loop())
        logger.info("Background SNMP Collector started in backend process")
    else:
        logger.info("Background SNMP Collector in backend process is disabled (DISABLE_BACKEND_COLLECTOR=true)")

    # Start Backup Scheduler
    schedule_daily_backup()
    backup_scheduler.start()
    logger.info("Backup scheduler started")


def reschedule_backup() -> None:
    """
    Reschedule the daily backup job. Called after backup config updates.
    """
    schedule_daily_backup()


@app.on_event("shutdown")
async def shutdown_event():
    """Stop the backup scheduler on shutdown."""
    backup_scheduler.shutdown()


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
        verify_connection(max_retries=1, retry_delay=0)
        neo4j_status = "CONNECTED"
    except:
        neo4j_status = "DISCONNECTED"

    postgres_status = "UNKNOWN"
    try:
        from postgres_db import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        postgres_status = "CONNECTED"
    except:
        postgres_status = "DISCONNECTED"

    collector = get_collector_status()

    return {
        "cpu": round(cpu_percent, 1),
        "ram": round(ram_percent, 1),
        "disk": round(disk_percent, 1),
        "neo4j": neo4j_status,
        "postgres": postgres_status,
        "collector": collector,
        "startup_time": STARTUP_TIME
    }
