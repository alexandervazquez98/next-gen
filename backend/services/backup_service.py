# backend/services/backup_service.py
"""Backup service — handles PostgreSQL backups, scheduling, and history."""

from __future__ import annotations

import logging
import os
import posixpath
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import get_db
from postgres_db import SessionLocal


# --- Config defaults ---

PERSISTENT_BACKUP_ROOT = "/backups"
logger = logging.getLogger(__name__)


def _normalize_storage_path(storage_path: Optional[str]) -> str:
    """Keep backup storage inside the persisted container mount."""
    if not storage_path:
        return PERSISTENT_BACKUP_ROOT

    normalized = posixpath.normpath(str(storage_path).strip().strip("'\""))
    if normalized == PERSISTENT_BACKUP_ROOT or normalized.startswith(f"{PERSISTENT_BACKUP_ROOT}/"):
        return normalized

    logger.warning(
        "Ignoring non-persistent backup storage_path %r; using %s",
        storage_path,
        PERSISTENT_BACKUP_ROOT,
    )
    return PERSISTENT_BACKUP_ROOT

DEFAULT_CONFIG = {
    "schedule_type": "daily",
    "scheduled_time": "06:00",
    "enabled": True,
    "retention_days": 7,
    "storage_path": PERSISTENT_BACKUP_ROOT,
}


# --- Private DB helpers ---

def _get_config_from_db() -> Optional[Dict[str, Any]]:
    """Load backup_config from PostgreSQL, or None if not set."""
    from models.backup_config import BackupConfig

    db = SessionLocal()
    try:
        row = db.query(BackupConfig).first()
        if not row:
            return None
        return {
            "schedule_type": row.schedule_type,
            "scheduled_time": row.scheduled_time,
            "enabled": row.enabled,
            "retention_days": row.retention_days,
            "storage_path": row.storage_path,
            "updated_by": row.updated_by,
        }
    finally:
        db.close()


def _save_config_to_db(
    schedule_type: str,
    scheduled_time: str,
    enabled: bool,
    retention_days: int,
    storage_path: str,
    updated_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update backup_config in PostgreSQL."""
    from models.backup_config import BackupConfig

    db = SessionLocal()
    try:
        config = db.query(BackupConfig).first()
        if not config:
            config = BackupConfig()
            db.add(config)

        config.schedule_type = schedule_type
        config.scheduled_time = scheduled_time
        config.enabled = enabled
        config.retention_days = retention_days
        config.storage_path = storage_path
        config.updated_by = updated_by

        db.commit()
        db.refresh(config)

        return {
            "schedule_type": config.schedule_type,
            "scheduled_time": config.scheduled_time,
            "enabled": config.enabled,
            "retention_days": config.retention_days,
            "storage_path": config.storage_path,
            "updated_by": config.updated_by,
        }
    finally:
        db.close()


def _get_history_from_db(limit: int = 50) -> List[Dict[str, Any]]:
    """Load recent backup history records from PostgreSQL."""
    from models.backup_config import BackupHistory

    db = SessionLocal()
    try:
        rows = (
            db.query(BackupHistory)
            .order_by(BackupHistory.started_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "filename": r.filename,
                "file_path": r.file_path,
                "size_bytes": r.size_bytes,
                "status": r.status,
                "error_message": r.error_message,
                "backup_type": r.backup_type,
                "triggered_by": r.triggered_by,
                "duration_seconds": r.duration_seconds,
                "started_at": r.started_at,
                "completed_at": r.completed_at,
            }
            for r in rows
        ]
    finally:
        db.close()


def _record_backup_history(
    filename: str,
    file_path: str,
    size_bytes: Optional[int],
    status: str,
    error_message: Optional[str],
    backup_type: str,
    triggered_by: Optional[str],
    duration_seconds: Optional[int],
    started_at: datetime,
    completed_at: Optional[datetime],
) -> None:
    """Persist a backup history record to PostgreSQL."""
    from models.backup_config import BackupHistory

    db = SessionLocal()
    try:
        record = BackupHistory(
            filename=filename,
            file_path=file_path,
            size_bytes=size_bytes,
            status=status,
            error_message=error_message,
            backup_type=backup_type,
            triggered_by=triggered_by,
            duration_seconds=duration_seconds,
            started_at=started_at,
            completed_at=completed_at,
        )
        db.add(record)
        db.commit()
    finally:
        db.close()


# --- Public API ---

def get_backup_config() -> Dict[str, Any]:
    """Return current backup configuration, falling back to defaults."""
    stored = _get_config_from_db()
    if stored is None:
        return DEFAULT_CONFIG.copy()
    stored["storage_path"] = _normalize_storage_path(stored.get("storage_path"))
    return stored


def update_backup_config(
    schedule_type: Optional[str] = None,
    scheduled_time: Optional[str] = None,
    enabled: Optional[bool] = None,
    retention_days: Optional[int] = None,
    storage_path: Optional[str] = None,
    updated_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Update backup configuration and return the new values."""
    current = get_backup_config()

    return _save_config_to_db(
        schedule_type=schedule_type if schedule_type is not None else current["schedule_type"],
        scheduled_time=scheduled_time if scheduled_time is not None else current["scheduled_time"],
        enabled=enabled if enabled is not None else current["enabled"],
        retention_days=retention_days if retention_days is not None else current["retention_days"],
        storage_path=_normalize_storage_path(storage_path if storage_path is not None else current["storage_path"]),
        updated_by=updated_by,
    )


def _run_pg_dump(output_path: str, db_name: str = "nexgen_auth") -> str:
    """Run pg_dump for the specified database and save to output_path."""
    os.makedirs(output_path, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{timestamp}.dump"
    filepath = os.path.join(output_path, filename)
    postgres_user = os.getenv("POSTGRES_USER", "nexgen_admin").strip("'\"")
    postgres_password = os.getenv("POSTGRES_PASSWORD", "nexgen_password").strip("'\"")
    postgres_host = os.getenv("POSTGRES_HOST", "postgres").strip("'\"")
    postgres_port = os.getenv("POSTGRES_PORT", "5432").strip("'\"")
    postgres_db = os.getenv("POSTGRES_DB", db_name).strip("'\"")
    pg_dump_env = os.environ.copy()
    pg_dump_env["PGPASSWORD"] = postgres_password

    result = subprocess.run(
        [
            "pg_dump",
            "-Fc",
            "-f", filepath,
            "-h", postgres_host,
            "-p", postgres_port,
            "-U", postgres_user,
            "-d", postgres_db,
        ],
        capture_output=True,
        env=pg_dump_env,
    )

    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {result.stderr.decode() if result.stderr else 'unknown error'}")

    return filepath


def _emit_backup_event(status: str, message: str) -> None:
    """Emit a BACKUP_SUCCESS or BACKUP_FAILURE Neo4j event for the admin dashboard."""
    driver = get_db()
    event_id = f"backup-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    severity = "INFO" if status == "SUCCESS" else "CRITICAL"

    with driver.session() as session:
        session.run(
            """
            CREATE (e:Event {
                id: $event_id,
                ci_id: 'SYSTEM',
                metric_id: 'BACKUP',
                status: 'OPEN',
                severity: $severity,
                message: $message,
                created_at: datetime(),
                last_seen: datetime()
            })
            """,
            event_id=event_id,
            severity=severity,
            message=message,
        )


def trigger_scheduled_backup() -> Dict[str, Any]:
    """
    Trigger a scheduled PostgreSQL backup (called by APScheduler at dawn).
    Returns the same result structure as trigger_manual_backup.
    """
    from services.backup_service import (
        get_backup_config,
        _run_pg_dump,
        _record_backup_history,
        _cleanup_old_backups,
        _emit_backup_event,
    )

    started_at = datetime.now(timezone.utc)
    config = get_backup_config()
    output_path = config["storage_path"]

    try:
        filepath = _run_pg_dump(output_path=output_path)
        filename = os.path.basename(filepath)
        size_bytes = os.path.getsize(filepath) if os.path.exists(filepath) else None
        duration = int((datetime.now(timezone.utc) - started_at).total_seconds())
        completed_at = datetime.now(timezone.utc)

        _record_backup_history(
            filename=filename,
            file_path=filepath,
            size_bytes=size_bytes,
            status="SUCCESS",
            error_message=None,
            backup_type="scheduled",
            triggered_by=None,
            duration_seconds=duration,
            started_at=started_at,
            completed_at=completed_at,
        )

        _emit_backup_event(
            status="SUCCESS",
            message=f"Scheduled backup completed: {filename} ({size_bytes} bytes)",
        )

        # Cleanup old backups after successful backup
        _cleanup_old_backups(output_path, config["retention_days"])

        return {
            "status": "SUCCESS",
            "filename": filename,
            "file_path": filepath,
            "size_bytes": size_bytes,
            "triggered_by": "scheduler",
            "backup_type": "scheduled",
            "duration_seconds": duration,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
        }

    except Exception as exc:
        duration = int((datetime.now(timezone.utc) - started_at).total_seconds())
        completed_at = datetime.now(timezone.utc)
        error_msg = str(exc)
        filename = f"FAILED_{started_at.strftime('%Y%m%d_%H%M%S')}.dump"

        _record_backup_history(
            filename=filename,
            file_path="",
            size_bytes=None,
            status="FAILURE",
            error_message=error_msg,
            backup_type="scheduled",
            triggered_by=None,
            duration_seconds=duration,
            started_at=started_at,
            completed_at=completed_at,
        )

        _emit_backup_event(
            status="FAILURE",
            message=f"Scheduled backup FAILED: {error_msg}",
        )

        return {
            "status": "FAILURE",
            "filename": filename,
            "error_message": error_msg,
            "triggered_by": "scheduler",
            "backup_type": "scheduled",
            "duration_seconds": duration,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
        }


def trigger_manual_backup(triggered_by: str) -> Dict[str, Any]:
    """Trigger a manual PostgreSQL backup and record the result."""

    started_at = datetime.now(timezone.utc)
    config = get_backup_config()
    output_path = config["storage_path"]

    try:
        filepath = _run_pg_dump(output_path=output_path)
        filename = os.path.basename(filepath)
        size_bytes = os.path.getsize(filepath) if os.path.exists(filepath) else None
        duration = int((datetime.now(timezone.utc) - started_at).total_seconds())
        completed_at = datetime.now(timezone.utc)

        _record_backup_history(
            filename=filename,
            file_path=filepath,
            size_bytes=size_bytes,
            status="SUCCESS",
            error_message=None,
            backup_type="manual",
            triggered_by=triggered_by,
            duration_seconds=duration,
            started_at=started_at,
            completed_at=completed_at,
        )

        _emit_backup_event(
            status="SUCCESS",
            message=f"Manual backup completed: {filename} ({size_bytes} bytes)",
        )

        # Cleanup old backups after successful backup
        _cleanup_old_backups(output_path, config["retention_days"])

        return {
            "status": "SUCCESS",
            "filename": filename,
            "file_path": filepath,
            "size_bytes": size_bytes,
            "triggered_by": triggered_by,
            "backup_type": "manual",
            "duration_seconds": duration,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
        }

    except Exception as exc:
        duration = int((datetime.now(timezone.utc) - started_at).total_seconds())
        completed_at = datetime.now(timezone.utc)
        error_msg = str(exc)
        filename = f"FAILED_{started_at.strftime('%Y%m%d_%H%M%S')}.dump"

        _record_backup_history(
            filename=filename,
            file_path="",
            size_bytes=None,
            status="FAILURE",
            error_message=error_msg,
            backup_type="manual",
            triggered_by=triggered_by,
            duration_seconds=duration,
            started_at=started_at,
            completed_at=completed_at,
        )

        _emit_backup_event(
            status="FAILURE",
            message=f"Manual backup FAILED: {error_msg}",
        )

        return {
            "status": "FAILURE",
            "filename": filename,
            "error_message": error_msg,
            "triggered_by": triggered_by,
            "backup_type": "manual",
            "duration_seconds": duration,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
        }


def get_backup_history(limit: int = 50) -> List[Dict[str, Any]]:
    """Return the most recent backup history records."""
    return _get_history_from_db(limit=limit)


def get_backup_metrics() -> Dict[str, Any]:
    """Aggregate backup statistics from history."""
    history = _get_history_from_db(limit=100)

    total = len(history)
    successful = sum(1 for r in history if r["status"] == "SUCCESS")
    failed = sum(1 for r in history if r["status"] == "FAILURE")

    last_backup = history[0] if history else None

    return {
        "total_backups": total,
        "successful_backups": successful,
        "failed_backups": failed,
        "last_backup": last_backup["filename"] if last_backup else None,
        "last_backup_status": last_backup["status"] if last_backup else None,
        "last_backup_at": last_backup["started_at"].isoformat() if last_backup and last_backup.get("started_at") else None,
    }


def _cleanup_old_backups(backup_dir: str, retention_days: int) -> int:
    """Remove backup files older than retention_days. Returns count of deleted files."""
    if not os.path.exists(backup_dir):
        return 0

    import time
    cutoff = time.time() - (retention_days * 86400)
    removed = 0

    for filename in os.listdir(backup_dir):
        if not filename.endswith(".dump"):
            continue
        filepath = os.path.join(backup_dir, filename)
        try:
            if os.path.getmtime(filepath) < cutoff:
                os.remove(filepath)
                removed += 1
        except OSError:
            continue

    return removed
