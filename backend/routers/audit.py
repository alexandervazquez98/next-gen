"""Audit log query API."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from models.audit import AuditEventListResponse
from models.audit_event import AuditEvent
from models.user import User, UserPermission
from postgres_db import get_pg_db
from services.auth_service import check_permission, get_current_active_user
from sqlalchemy.orm import Session

router = APIRouter(
    prefix="/audit",
    tags=["Audit"],
    responses={404: {"description": "Not found"}},
)

AuditOutcome = Literal["SUCCESS", "DENIED", "VALIDATION_FAILURE", "FAILURE"]
AuditSort = Literal["created_at_desc", "created_at_asc"]


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


@router.get("/events", response_model=AuditEventListResponse)
async def list_audit_events(
    start_time: datetime | None = Query(  # noqa: B008
        None, description="Inclusive event window start"
    ),
    end_time: datetime | None = Query(None, description="Inclusive event window end"),  # noqa: B008
    actor: str | None = Query(None, description="Exact actor username"),  # noqa: B008
    event_type: str | None = Query(None, description="Exact audit event type"),  # noqa: B008
    outcome: AuditOutcome | None = Query(None, description="Audit event outcome"),  # noqa: B008
    target_type: str | None = Query(None, description="Exact audit target type"),  # noqa: B008
    target_id: str | None = Query(None, description="Exact audit target id"),  # noqa: B008
    page: int = Query(1, ge=1),  # noqa: B008
    page_size: int = Query(50, ge=1, le=100),  # noqa: B008
    sort: AuditSort = Query("created_at_desc"),  # noqa: B008
    current_user: User = Depends(get_current_active_user),  # noqa: B008
    db: Session = Depends(get_pg_db),  # noqa: B008
):
    """Return permission-gated audit events with server-side filters."""

    if not check_permission(UserPermission.AUDIT_VIEW, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to view audit logs")

    normalized_start = _normalize_datetime(start_time)
    normalized_end = _normalize_datetime(end_time)
    if normalized_start and normalized_end and normalized_start > normalized_end:
        raise HTTPException(
            status_code=422, detail="start_time must be before or equal to end_time"
        )

    query = db.query(AuditEvent)
    if normalized_start:
        query = query.filter(AuditEvent.created_at >= normalized_start)
    if normalized_end:
        query = query.filter(AuditEvent.created_at <= normalized_end)
    if actor:
        query = query.filter(AuditEvent.actor_username == actor)
    if event_type:
        query = query.filter(AuditEvent.event_type == event_type)
    if outcome:
        query = query.filter(AuditEvent.outcome == outcome)
    if target_type:
        query = query.filter(AuditEvent.target_type == target_type)
    if target_id:
        query = query.filter(AuditEvent.target_id == target_id)

    total = query.count()
    if sort == "created_at_asc":
        query = query.order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
    else:
        query = query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())

    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return AuditEventListResponse(items=items, total=total, page=page, page_size=page_size)
