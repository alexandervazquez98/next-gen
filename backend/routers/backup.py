# backend/routers/backup.py
"""Backup system API — admin-configurable schedule, manual backup, metrics."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
import services.backup_service as backup_service
from models.user import User, UserRole
from postgres_db import get_pg_db
from services import audit_service
from services.auth_service import get_current_active_user


# Audit constants
AUDIT_TARGET_TYPE_SYSTEM_CONFIG = "system_config"
AUDIT_SOURCE_BACKUP = "backup"

AUDIT_OUTCOME_SUCCESS = "SUCCESS"
AUDIT_OUTCOME_VALIDATION_FAILURE = "VALIDATION_FAILURE"

AUDIT_EVENT_SYSTEM_CONFIG_UPDATE = "SYSTEM_CONFIG_UPDATE"

ALLOWED_BACKUP_SCHEDULE_TYPES = {"daily", "manual"}

router = APIRouter(
    prefix="/backup",
    tags=["Backup"],
    responses={404: {"description": "Not found"}},
)


# --- Pydantic schemas ---


class BackupConfigUpdate(BaseModel):
    schedule_type: Optional[str] = None  # "daily" or "manual"
    scheduled_time: Optional[str] = None  # HH:MM in 24h format
    enabled: Optional[bool] = None
    retention_days: Optional[int] = None
    storage_path: Optional[str] = None


# --- Endpoints ---


@router.get("/config")
async def get_backup_config_endpoint() -> dict:
    """
    Get current backup configuration.
    Returns schedule type, time, enabled flag, retention days, and storage path.
    """
    return backup_service.get_backup_config()


def _validate_backup_config_update(config: BackupConfigUpdate) -> tuple[str | None, str | None]:
    """Return (validation_error_key, error_message) for unsupported payload values."""

    if config.schedule_type is not None and config.schedule_type not in ALLOWED_BACKUP_SCHEDULE_TYPES:
        return "invalid_schedule_type", f"schedule_type must be one of {sorted(ALLOWED_BACKUP_SCHEDULE_TYPES)}"

    if config.retention_days is not None and config.retention_days < 0:
        return "invalid_retention_days", "retention_days must be non-negative"

    if config.retention_days is not None and config.retention_days > 3650:
        return "invalid_retention_days", "retention_days must be <= 3650"

    return None, None


@router.put("/config")
async def update_backup_config_endpoint(
    request: Request,
    config: BackupConfigUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db),
) -> dict:
    """
    Update backup configuration. Admin only.
    Allows changing schedule type (daily/manual), scheduled time,
    enabled flag, retention period, and storage path.
    """
    if current_user.role != UserRole.ADMIN and current_user.role != "ADMIN":
        audit_service.record_denied(
            db=db,
            request=request,
            actor=current_user,
            required_permission=UserRole.ADMIN.value,
            target_type=AUDIT_TARGET_TYPE_SYSTEM_CONFIG,
            target_id="backup_config",
            source=AUDIT_SOURCE_BACKUP,
            reason="missing_permission:ADMIN",
        )
        raise HTTPException(
            status_code=403,
            detail="Only admins can update backup configuration",
        )

    validation_error, validation_message = _validate_backup_config_update(config)
    if validation_error:
        changed_fields = [field for field, value in config.model_dump(exclude_unset=True).items() if value is not None]
        audit_service.record_critical_change(
            db=db,
            request=request,
            actor=current_user,
            event_type=AUDIT_EVENT_SYSTEM_CONFIG_UPDATE,
            outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
            target_type=AUDIT_TARGET_TYPE_SYSTEM_CONFIG,
            target_id="backup_config",
            target_label="Backup Configuration",
            reason=validation_error,
            source=AUDIT_SOURCE_BACKUP,
            context={
                "changed_fields": changed_fields,
                "required_permission": UserRole.ADMIN.value,
            },
        )
        raise HTTPException(
            status_code=400,
            detail=validation_message,
        )

    changed_fields = [field for field, value in config.model_dump(exclude_unset=True).items() if value is not None]
    result = backup_service.update_backup_config(
        schedule_type=config.schedule_type,
        scheduled_time=config.scheduled_time,
        enabled=config.enabled,
        retention_days=config.retention_days,
        storage_path=config.storage_path,
        updated_by=current_user.username,
    )

    audit_service.record_critical_change(
        db=db,
        request=request,
        actor=current_user,
        event_type=AUDIT_EVENT_SYSTEM_CONFIG_UPDATE,
        outcome=AUDIT_OUTCOME_SUCCESS,
        target_type=AUDIT_TARGET_TYPE_SYSTEM_CONFIG,
        target_id="backup_config",
        target_label="Backup Configuration",
        reason="backup_config_updated",
        source=AUDIT_SOURCE_BACKUP,
        context={
            "changed_fields": changed_fields,
            "required_permission": UserRole.ADMIN.value,
        },
    )

    # Reschedule the daily backup job with new config
    import main
    main.reschedule_backup()

    return result


@router.post("/backup")
async def trigger_backup_endpoint(
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Trigger a manual backup immediately. Admin only.
    Returns the backup result (success/failure) with file details.
    """
    if current_user.role != UserRole.ADMIN and current_user.role != "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Only admins can trigger manual backups",
        )

    return backup_service.trigger_manual_backup(triggered_by=current_user.username)


@router.get("/history")
async def get_backup_history_endpoint(
    limit: int = Query(default=50, ge=1, le=500),
) -> List[dict]:
    """
    Get backup history (most recent first).
    Defaults to 50 records, max 500.
    """
    return backup_service.get_backup_history(limit=limit)


@router.get("/metrics")
async def get_backup_metrics_endpoint() -> dict:
    """
    Get aggregated backup metrics for the admin dashboard.
    Returns total/successful/failed counts and last backup info.
    """
    return backup_service.get_backup_metrics()