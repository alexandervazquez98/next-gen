import asyncio
import logging
import os
import platform
import re
import shutil
import threading
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from config import get_time_sync_settings
from database import get_db, verify_connection
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from neo4j import Query as Neo4jQuery

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global start time to track system reboots/restarts
STARTUP_TIME = datetime.now().isoformat()
_DISK_SECTOR_SIZE_BYTES = 512
_DISK_IO_PREVIOUS_SAMPLE = None
_DISK_IO_SAMPLE_LOCK = threading.Lock()
_SYSTEM_STATUS_HISTORY_LOCK = threading.Lock()


_SYSTEM_STATUS_SNAPSHOTS_ENABLED = True
_SYSTEM_STATUS_HISTORY_RETENTION_DAYS = 7
_SYSTEM_STATUS_HISTORY_MIN_INTERVAL_SECONDS = 900
_SYSTEM_STATUS_HISTORY_STALE_THRESHOLD_SECONDS = 1800


def _parse_system_status_bool(value: str) -> bool | None:
    if value.strip().lower() in ("1", "true", "yes", "on", "enabled", "enable"):
        return True
    if value.strip().lower() in ("0", "false", "no", "off", "disabled", "disable"):
        return False
    return None


def _parse_system_status_int(env_var: str, default_value: int, minimum: int | None = None) -> int:
    raw_value = os.getenv(env_var)
    if raw_value is None:
        return default_value

    try:
        parsed_value = int(raw_value.strip())
        if minimum is not None and parsed_value < minimum:
            raise ValueError(f"{env_var} cannot be lower than {minimum}: {parsed_value}")
        return parsed_value
    except Exception as exc:
        logger.warning(
            "Invalid value for %s=%r, using default %s: %s",
            env_var,
            raw_value,
            default_value,
            exc,
        )
        return default_value


def _reload_system_status_env_settings() -> None:
    """Load system-status snapshot behavior from environment with safe defaults."""
    global _SYSTEM_STATUS_SNAPSHOTS_ENABLED
    global _SYSTEM_STATUS_HISTORY_RETENTION_DAYS
    global _SYSTEM_STATUS_HISTORY_MIN_INTERVAL_SECONDS
    global _SYSTEM_STATUS_HISTORY_STALE_THRESHOLD_SECONDS

    enabled = os.getenv("SYSTEM_STATUS_SNAPSHOTS_ENABLED", "true")
    parsed_enabled = _parse_system_status_bool(enabled)
    if parsed_enabled is None:
        logger.warning(
            "Invalid value for SYSTEM_STATUS_SNAPSHOTS_ENABLED=%r, using default true",
            enabled,
        )
        parsed_enabled = True
    _SYSTEM_STATUS_SNAPSHOTS_ENABLED = parsed_enabled

    _SYSTEM_STATUS_HISTORY_RETENTION_DAYS = _parse_system_status_int(
        "SYSTEM_STATUS_HISTORY_RETENTION_DAYS",
        default_value=7,
        minimum=1,
    )
    _SYSTEM_STATUS_HISTORY_MIN_INTERVAL_SECONDS = _parse_system_status_int(
        "SYSTEM_STATUS_SNAPSHOT_INTERVAL_SECONDS",
        default_value=900,
        minimum=60,
    )
    _SYSTEM_STATUS_HISTORY_STALE_THRESHOLD_SECONDS = _parse_system_status_int(
        "SYSTEM_STATUS_HISTORY_STALE_THRESHOLD_SECONDS",
        default_value=1800,
        minimum=60,
    )


from middleware.rate_limit import RateLimitMiddleware  # noqa: E402
from seed_admin import seed_admin  # noqa: E402
from seed_roles import seed_roles  # noqa: E402
from services.snmp_service import get_collector_status, snmp_collector_loop  # noqa: E402

# Global scheduler instance
backup_scheduler = AsyncIOScheduler()


# Initialize system-status snapshot settings from environment now and again during startup.
_reload_system_status_env_settings()


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

    # Replace only the backup job so unrelated scheduler jobs (audit cleanup) survive reschedules.
    if backup_scheduler.get_job("daily_backup"):
        backup_scheduler.remove_job("daily_backup")

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
from routers import (  # noqa: E402
    ai,
    audit,
    auth,
    backup,
    catalog,
    cis,
    cli,
    dictionaries,
    events,
    links,
    metrics,
    nodes,
    permissions,
    roles,
    rtus,
    tunnels,
    users,
)

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
            conn.execute(
                sql("ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS session_id VARCHAR")
            )
            conn.execute(
                sql(
                    "ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS policy_profile VARCHAR DEFAULT 'standard'"
                )
            )
            conn.execute(
                sql(
                    "ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMP"
                )
            )
            conn.execute(
                sql("ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS rotated_at TIMESTAMP")
            )
            conn.execute(
                sql(
                    "ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS replaced_by_token_id INTEGER REFERENCES refresh_tokens(id)"
                )
            )
            conn.execute(
                sql("ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS revoked_reason VARCHAR")
            )
            conn.execute(
                sql(
                    "ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS stale_recovery_count INTEGER DEFAULT 0"
                )
            )
            # Backfill existing rows so runtime non-null assumptions are still safe.
            conn.execute(
                sql(
                    "UPDATE refresh_tokens SET session_id = COALESCE(session_id, CONCAT('legacy-', id::text)) WHERE session_id IS NULL"
                )
            )
            conn.execute(
                sql(
                    "UPDATE refresh_tokens SET policy_profile = COALESCE(policy_profile, 'standard') WHERE policy_profile IS NULL"
                )
            )
            conn.execute(
                sql(
                    "UPDATE refresh_tokens SET last_activity_at = COALESCE(last_activity_at, created_at, NOW()) WHERE last_activity_at IS NULL"
                )
            )
            conn.execute(
                sql(
                    "UPDATE refresh_tokens SET stale_recovery_count = COALESCE(stale_recovery_count, 0) WHERE stale_recovery_count IS NULL"
                )
            )
            conn.execute(
                sql(
                    "CREATE INDEX IF NOT EXISTS ix_refresh_tokens_session_id ON refresh_tokens (session_id)"
                )
            )
            conn.execute(
                sql(
                    "CREATE INDEX IF NOT EXISTS ix_refresh_tokens_policy_profile ON refresh_tokens (policy_profile)"
                )
            )
            conn.commit()
    except Exception as migration_err:
        logger.warning(
            f"Migration warning (refresh_tokens session-policy columns): {migration_err}"
        )


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
app.include_router(audit.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(roles.router, prefix="/api")
app.include_router(nodes.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(catalog.router, prefix="/api")
app.include_router(links.router, prefix="/api")
app.include_router(tunnels.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(backup.router, prefix="/api")
app.include_router(dictionaries.router, prefix="/api")
app.include_router(cis.router, prefix="/api")
app.include_router(cli.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(permissions.router, prefix="/api")
app.include_router(rtus.router, prefix="/api/v1")


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
        from postgres_db import Base, SessionLocal, engine
        # PR1: import MQTT bridge idempotency model so Base metadata can create table.
        from models.mqtt_metric_sample_receipt import MqttMetricSampleReceipt  # noqa: F401
        from repositories.metric_repo import create_hypertable

        # Create Tables (includes backup_config, backup_history, rate_limit_attempts, system status history, and audit events)
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
    _reload_system_status_env_settings()

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

    # Seed AI Prompts (frozen user-override folder; non-fatal, bundled fallback applies)
    try:
        from services.ai_chat_service import ensure_ai_prompts_seeded

        ensure_ai_prompts_seeded()
    except Exception as e:
        logger.error(f"Failed to seed AI prompts: {e}")

    # Start Background SNMP Collector
    disable_collector = os.getenv("DISABLE_BACKEND_COLLECTOR", "false").lower() in (
        "true",
        "1",
        "yes",
        "on",
    )
    if not disable_collector:
        asyncio.create_task(snmp_collector_loop())
        logger.info("Background SNMP Collector started in backend process")
    else:
        logger.info(
            "Background SNMP Collector in backend process is disabled (DISABLE_BACKEND_COLLECTOR=true)"
        )

    # Start Backup Scheduler
    schedule_daily_backup()
    try:
        from services.audit_service import run_audit_retention_cleanup

        backup_scheduler.add_job(
            run_audit_retention_cleanup,
            trigger=CronTrigger(hour=3, minute=30),
            id="audit_retention_cleanup",
            name="Audit Event Retention Cleanup",
            replace_existing=True,
        )
        logger.info("Scheduled audit retention cleanup at 03:30")
    except Exception as e:
        logger.error(f"Failed to schedule audit retention cleanup: {e}")

    # Start System Status Snapshot Scheduler (background ownership for persisted history)
    if _SYSTEM_STATUS_SNAPSHOTS_ENABLED:
        try:
            _register_system_status_snapshot_job()
        except Exception as e:
            logger.error("Failed to schedule system status snapshot job: %s", e)

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


def _is_diskstats_device(device_name: str) -> bool:
    """Return true for base disk devices while excluding common partitions."""
    if device_name.startswith(("loop", "ram", "fd", "sr")):
        return False
    if re.fullmatch(r"sd[a-z]+|vd[a-z]+|xvd[a-z]+|hd[a-z]+", device_name):
        return True
    if re.fullmatch(r"nvme\d+n\d+", device_name):
        return True
    if re.fullmatch(r"mmcblk\d+", device_name):  # noqa: SIM103
        return True
    return False


def _collect_disk_io_sample(path: str = "/proc/diskstats", sampled_at: datetime | None = None):
    """Collect a lightweight aggregate disk I/O sample from Linux /proc/diskstats."""
    read_bytes = 0
    write_bytes = 0
    busy_ms = 0

    try:
        with open(path, encoding="utf-8") as diskstats:
            lines = diskstats.readlines()
    except OSError:
        return None

    for line in lines:
        parts = line.split()
        if len(parts) < 14:
            continue
        device_name = parts[2]
        if not _is_diskstats_device(device_name):
            continue
        try:
            read_bytes += int(parts[5]) * _DISK_SECTOR_SIZE_BYTES
            write_bytes += int(parts[9]) * _DISK_SECTOR_SIZE_BYTES
            busy_ms += int(parts[12])
        except ValueError:
            continue

    if read_bytes == 0 and write_bytes == 0 and busy_ms == 0:
        return None

    return {
        "read_bytes": read_bytes,
        "write_bytes": write_bytes,
        "busy_ms": busy_ms,
        "sampled_at": sampled_at or datetime.now(),
    }


def _empty_disk_io_status(supported: bool = False):
    return {
        "supported": supported,
        "read_bytes_total": None,
        "write_bytes_total": None,
        "read_bytes_per_sec": None,
        "write_bytes_per_sec": None,
        "busy_percentage": None,
        "sampled_at": None,
    }


def _build_disk_io_status(current, previous=None):
    """Build the API disk I/O payload, including rates when a previous sample exists."""
    if current is None:
        return _empty_disk_io_status(supported=False)

    sampled_at = current["sampled_at"]
    status = {
        "supported": True,
        "read_bytes_total": current["read_bytes"],
        "write_bytes_total": current["write_bytes"],
        "read_bytes_per_sec": None,
        "write_bytes_per_sec": None,
        "busy_percentage": None,
        "sampled_at": sampled_at.isoformat(),
    }

    if previous is None:
        return status

    elapsed_seconds = (sampled_at - previous["sampled_at"]).total_seconds()
    if elapsed_seconds <= 0:
        return status

    read_delta = current["read_bytes"] - previous["read_bytes"]
    write_delta = current["write_bytes"] - previous["write_bytes"]
    busy_delta = current["busy_ms"] - previous["busy_ms"]
    if read_delta < 0 or write_delta < 0 or busy_delta < 0:
        return status

    status["read_bytes_per_sec"] = round(read_delta / elapsed_seconds, 2)
    status["write_bytes_per_sec"] = round(write_delta / elapsed_seconds, 2)
    status["busy_percentage"] = round(min((busy_delta / (elapsed_seconds * 1000)) * 100, 100), 1)
    return status


def _get_disk_io_status():
    """Return disk I/O health with graceful unsupported/null behavior."""
    global _DISK_IO_PREVIOUS_SAMPLE
    if platform.system() != "Linux":
        _DISK_IO_PREVIOUS_SAMPLE = None
        return _empty_disk_io_status(supported=False)

    with _DISK_IO_SAMPLE_LOCK:
        current = _collect_disk_io_sample()
        if current is None:
            _DISK_IO_PREVIOUS_SAMPLE = None
            return _empty_disk_io_status(supported=False)
        status = _build_disk_io_status(current, _DISK_IO_PREVIOUS_SAMPLE)
        _DISK_IO_PREVIOUS_SAMPLE = current
        return status


def _safe_float(value):
    return None if value is None else float(value)


def _safe_int(value):
    return None if value is None else int(value)


def _utc_now(tz=UTC) -> datetime:
    return datetime.now(tz)


def _should_record_system_status_snapshot(latest_snapshot, now: datetime) -> bool:
    """Return true when the latest persisted snapshot is outside the throttle window."""
    if latest_snapshot is None or latest_snapshot.recorded_at is None:
        return True
    return (
        now - latest_snapshot.recorded_at
    ).total_seconds() >= _SYSTEM_STATUS_HISTORY_MIN_INTERVAL_SECONDS


def _is_system_status_history_stale(
    latest_recorded_at: datetime | None,
    generated_at: datetime,
    stale_threshold_seconds: int | None = None,
) -> bool:
    """Return whether persisted history is stale."""
    threshold = stale_threshold_seconds or _SYSTEM_STATUS_HISTORY_STALE_THRESHOLD_SECONDS
    if latest_recorded_at is None:
        return True
    return (generated_at - latest_recorded_at).total_seconds() > threshold


def _build_system_status_snapshot(status: dict, recorded_at: datetime):
    """Convert the live `/api/system/status` payload into a compact persisted row."""
    from models.system_status_history import SystemStatusSnapshot

    collector = status.get("collector") or {}
    collector_stats = collector.get("stats") or {}
    disk_io = status.get("disk_io") or {}
    return SystemStatusSnapshot(
        recorded_at=recorded_at,
        cpu=_safe_float(status.get("cpu")),
        ram=_safe_float(status.get("ram")),
        disk=_safe_float(status.get("disk")),
        disk_io_supported=bool(disk_io.get("supported")),
        disk_read_bytes_per_sec=_safe_float(disk_io.get("read_bytes_per_sec")),
        disk_write_bytes_per_sec=_safe_float(disk_io.get("write_bytes_per_sec")),
        disk_busy_percentage=_safe_float(disk_io.get("busy_percentage")),
        neo4j_status=status.get("neo4j"),
        postgres_status=status.get("postgres"),
        collector_status=collector.get("status"),
        collector_cis_monitored=_safe_int(collector_stats.get("cis_monitored")),
        collector_metrics_collected=_safe_int(collector_stats.get("metrics_collected")),
        collector_metrics_failed=_safe_int(collector_stats.get("metrics_failed")),
        collector_jobs_per_min=_safe_float(collector_stats.get("jobs_per_min")),
        collector_cycle_duration=_safe_float(collector_stats.get("cycle_duration")),
    )


def _utc_isoformat(value: datetime) -> str:
    """Serialize stored UTC datetimes with an explicit timezone marker for clients."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _empty_time_sync_status(settings, error: str, measured_at: datetime) -> dict:
    return {
        "status": "UNKNOWN",
        "sources": {"reference": "backend", "compared": "neo4j"},
        "skew_ms": None,
        "thresholds_ms": {
            "warning": float(settings.warning_ms),
            "critical": float(settings.critical_ms),
        },
        "backend_time": _utc_isoformat(measured_at),
        "neo4j_time": None,
        "measured_at": _utc_isoformat(measured_at),
        "query_latency_ms": None,
        "error": error,
    }


def _normalize_neo4j_time(value) -> datetime:
    if hasattr(value, "to_native"):
        value = value.to_native()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    raise ValueError("invalid_neo4j_time")


def _classify_time_sync_skew(skew_ms: float, settings) -> str:
    if skew_ms >= settings.critical_ms:
        return "CRITICAL"
    if skew_ms >= settings.warning_ms:
        return "WARNING"
    return "OK"


def _time_sync_query_error(exc: Exception) -> str:
    timeout_sources = [type(exc).__name__, str(exc)]
    for attr in ("code", "status_code", "status", "gql_status", "gql_status_code"):
        value = getattr(exc, attr, None)
        if value is not None:
            timeout_sources.append(str(value))

    normalized_sources = [re.sub(r"[^a-z0-9]", "", source.lower()) for source in timeout_sources]
    if any(
        "timeout" in source or "timedout" in source or "deadline" in source
        for source in normalized_sources
    ):
        return "neo4j_time_query_timeout"
    return "neo4j_time_query_failed"


def _build_time_sync_status(driver=None, settings=None, now_func=None) -> dict:
    """Build backend-vs-Neo4j clock-skew telemetry without affecting health status."""
    settings = settings or get_time_sync_settings()
    now_func = now_func or _utc_now
    measured_at = now_func(UTC)

    try:
        driver = driver or get_db()
        before = measured_at
        query = Neo4jQuery(
            "RETURN datetime() AS neo4j_time",
            timeout=getattr(settings, "query_timeout_s", 1.0),
        )
        with driver.session() as session:
            record = session.run(query).single()
        after = now_func(UTC)
    except Exception as exc:
        logger.warning("Failed to query Neo4j time for time-sync status: %s", exc)
        return _empty_time_sync_status(settings, _time_sync_query_error(exc), measured_at)

    try:
        raw_neo4j_time = record["neo4j_time"] if record else None
        neo4j_time = _normalize_neo4j_time(raw_neo4j_time)
    except Exception as exc:
        logger.warning("Failed to normalize Neo4j time for time-sync status: %s", exc)
        return _empty_time_sync_status(settings, "invalid_neo4j_time", measured_at)

    latency = after - before
    midpoint = before + (latency / 2)
    skew_ms = abs((neo4j_time - midpoint).total_seconds() * 1000)
    skew_ms = round(skew_ms, 3)

    return {
        "status": _classify_time_sync_skew(skew_ms, settings),
        "sources": {"reference": "backend", "compared": "neo4j"},
        "skew_ms": skew_ms,
        "thresholds_ms": {
            "warning": float(settings.warning_ms),
            "critical": float(settings.critical_ms),
        },
        "backend_time": _utc_isoformat(midpoint),
        "neo4j_time": _utc_isoformat(neo4j_time),
        "measured_at": _utc_isoformat(midpoint),
        "query_latency_ms": round(latency.total_seconds() * 1000, 3),
        "error": None,
    }


def _serialize_system_status_snapshot(snapshot):
    """Serialize a persisted status snapshot into the history API row contract."""
    return {
        "recorded_at": _utc_isoformat(snapshot.recorded_at),
        "cpu": snapshot.cpu,
        "ram": snapshot.ram,
        "disk": snapshot.disk,
        "disk_io": {
            "supported": snapshot.disk_io_supported,
            "read_bytes_per_sec": snapshot.disk_read_bytes_per_sec,
            "write_bytes_per_sec": snapshot.disk_write_bytes_per_sec,
            "busy_percentage": snapshot.disk_busy_percentage,
        },
        "neo4j": snapshot.neo4j_status,
        "postgres": snapshot.postgres_status,
        "collector": {
            "status": snapshot.collector_status,
            "stats": {
                "cis_monitored": snapshot.collector_cis_monitored,
                "metrics_collected": snapshot.collector_metrics_collected,
                "metrics_failed": snapshot.collector_metrics_failed,
                "jobs_per_min": snapshot.collector_jobs_per_min,
                "cycle_duration": snapshot.collector_cycle_duration,
            },
        },
    }


def _build_system_status_payload() -> dict:
    """Build live system telemetry payload for dashboard cards."""
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
    except Exception:
        pass

    try:
        # Disk Usage
        total, used, free = shutil.disk_usage("/")
        disk_percent = (used / total) * 100
    except Exception:
        pass

    # RAM (Linux /proc/meminfo parsing)
    if platform.system() == "Linux":
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()
                mem_total = int(lines[0].split()[1])
                mem_available = int(lines[2].split()[1])  # MemAvailable usually
                ram_percent = ((mem_total - mem_available) / mem_total) * 100
        except Exception:
            pass

    # 2. Service Status
    neo4j_status = "UNKNOWN"
    try:
        verify_connection(max_retries=1, retry_delay=0)
        neo4j_status = "CONNECTED"
    except Exception:
        neo4j_status = "DISCONNECTED"

    postgres_status = "UNKNOWN"
    try:
        from postgres_db import engine
        from sqlalchemy import text

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        postgres_status = "CONNECTED"
    except Exception:
        postgres_status = "DISCONNECTED"

    collector = get_collector_status()
    from services.event_lock import get_event_lock_observability_snapshot

    try:
        event_lock_snapshot = get_event_lock_observability_snapshot()
    except Exception as exc:
        logger.warning("Failed to build event lock observability snapshot: %s", exc)
        event_lock_snapshot = {"alert_state": "UNKNOWN", "snapshot_error": True}

    if neo4j_status == "CONNECTED":
        time_sync = _build_time_sync_status()
    else:
        time_sync = _empty_time_sync_status(
            get_time_sync_settings(),
            "neo4j_disconnected",
            _utc_now(UTC),
        )

    return {
        "cpu": round(cpu_percent, 1),
        "ram": round(ram_percent, 1),
        "disk": round(disk_percent, 1),
        "disk_io": _get_disk_io_status(),
        "neo4j": neo4j_status,
        "postgres": postgres_status,
        "collector": collector,
        "event_lock": event_lock_snapshot,
        "time_sync": time_sync,
        "startup_time": STARTUP_TIME,
    }


def _record_system_status_snapshot_job() -> bool:
    try:
        payload = _build_system_status_payload()
        return _record_system_status_snapshot(payload)
    except Exception as exc:
        logger.warning("Failed to run system status snapshot job: %s", exc)
        return False


def _register_system_status_snapshot_job() -> bool:
    if not _SYSTEM_STATUS_SNAPSHOTS_ENABLED:
        logger.info("System status snapshot scheduler is disabled")
        return False

    backup_scheduler.add_job(
        _record_system_status_snapshot_job,
        trigger=IntervalTrigger(seconds=_SYSTEM_STATUS_HISTORY_MIN_INTERVAL_SECONDS),
        id="system_status_snapshot",
        name="System Status Snapshot",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "Scheduled system status snapshot job every %ss",
        _SYSTEM_STATUS_HISTORY_MIN_INTERVAL_SECONDS,
    )
    return True


def _record_system_status_snapshot(status: dict, now: datetime | None = None) -> bool:
    """Persist a throttled operational snapshot and prune data older than configured retention."""
    from models.system_status_history import SystemStatusSnapshot
    from postgres_db import SessionLocal

    recorded_at = now or datetime.now(UTC).replace(tzinfo=None)
    if recorded_at.tzinfo is not None:
        recorded_at = recorded_at.astimezone(UTC).replace(tzinfo=None)
    with _SYSTEM_STATUS_HISTORY_LOCK:
        db = SessionLocal()
        try:
            latest = (
                db.query(SystemStatusSnapshot)
                .order_by(SystemStatusSnapshot.recorded_at.desc())
                .first()
            )
            if not _should_record_system_status_snapshot(latest, recorded_at):
                return False

            db.add(_build_system_status_snapshot(status, recorded_at))
            cutoff = recorded_at - timedelta(days=_SYSTEM_STATUS_HISTORY_RETENTION_DAYS)
            db.query(SystemStatusSnapshot).filter(SystemStatusSnapshot.recorded_at < cutoff).delete(
                synchronize_session=False
            )
            db.commit()
            return True
        except Exception as exc:
            db.rollback()
            logger.warning("Failed to record system status snapshot: %s", exc)
            return False
        finally:
            db.close()


def _fetch_system_status_history(hours: int, limit: int, now: datetime | None = None):
    """Read compact system status history rows newest-first."""
    from models.system_status_history import SystemStatusSnapshot
    from postgres_db import SessionLocal

    generated_at = now or datetime.now(UTC).replace(tzinfo=None)
    if generated_at.tzinfo is not None:
        generated_at = generated_at.astimezone(UTC).replace(tzinfo=None)
    cutoff = generated_at - timedelta(hours=hours)
    db = SessionLocal()
    try:
        snapshots = (
            db.query(SystemStatusSnapshot)
            .filter(SystemStatusSnapshot.recorded_at >= cutoff)
            .order_by(SystemStatusSnapshot.recorded_at.desc())
            .limit(limit)
            .all()
        )
        latest_recorded_at = snapshots[0].recorded_at if snapshots else None
        is_stale = _is_system_status_history_stale(
            latest_recorded_at=latest_recorded_at,
            generated_at=generated_at,
        )

        return {
            "generated_at": _utc_isoformat(generated_at),
            "hours": hours,
            "limit": limit,
            "retention_days": _SYSTEM_STATUS_HISTORY_RETENTION_DAYS,
            "snapshot_interval_seconds": _SYSTEM_STATUS_HISTORY_MIN_INTERVAL_SECONDS,
            "stale_threshold_seconds": _SYSTEM_STATUS_HISTORY_STALE_THRESHOLD_SECONDS,
            "latest_recorded_at": (
                _utc_isoformat(latest_recorded_at) if latest_recorded_at else None
            ),
            "is_stale": is_stale,
            "rows": [_serialize_system_status_snapshot(row) for row in snapshots],
        }
    finally:
        db.close()


@app.get("/api/system/status")
def get_system_status():
    """
    Get internal system health metrics (CPU, RAM, Disk, Services).
    """
    return _build_system_status_payload()


@app.get("/api/system/status/history")
def get_system_status_history(
    hours: int = Query(168, ge=1, le=168, description="History window in hours"),
    limit: int = Query(100, ge=1, le=500, description="Maximum snapshots to return"),
):
    """Fetch persisted operational system status snapshots, newest first."""
    try:
        return _fetch_system_status_history(hours=hours, limit=limit)
    except Exception as exc:
        logger.error("Failed to fetch system status history: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="System status history unavailable") from exc
