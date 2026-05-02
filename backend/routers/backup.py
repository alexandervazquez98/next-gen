# backend/routers/backup.py
"""Backup system API — admin-configurable schedule, manual backup, metrics."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import services.backup_service as backup_service
from models.user import User, UserRole, UserPermission
from services.auth_service import get_current_active_user, check_permission

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


@router.put("/config")
async def update_backup_config_endpoint(
    config: BackupConfigUpdate,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Update backup configuration. Admin only.
    Allows changing schedule type (daily/manual), scheduled time,
    enabled flag, retention period, and storage path.
    """
    if current_user.role != UserRole.ADMIN and current_user.role != "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Only admins can update backup configuration",
        )

    result = backup_service.update_backup_config(
        schedule_type=config.schedule_type,
        scheduled_time=config.scheduled_time,
        enabled=config.enabled,
        retention_days=config.retention_days,
        storage_path=config.storage_path,
        updated_by=current_user.username,
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