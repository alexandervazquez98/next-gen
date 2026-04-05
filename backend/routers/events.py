from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import services.event_service as event_service
from services.auth_service import get_current_active_user, check_permission
from models.user import User, UserPermission

router = APIRouter(
    prefix="/api/events",
    tags=["Events"],
    responses={404: {"description": "Not found"}},
)


class EventComment(BaseModel):
    message: str


@router.get("", response_model=List[Dict[str, Any]])
async def get_events(status: Optional[str] = None):
    """
    Fetch system events filtered by status.
    Args:
        status (str, optional): 'OPEN', 'ACK', 'CLOSED', 'RECOVERED', or 'ACTIVE' (Open/Ack/Recovered).
    """
    return event_service.get_events(status)


@router.get("/related/{ci_id}", response_model=List[Dict[str, Any]])
async def get_related_events(ci_id: str):
    """
    Fetch all ACTIVE (OPEN, ACK) events for a specific CI.
    """
    return event_service.get_related_events(ci_id)


@router.post("/{event_id}/ack")
async def ack_event(
    event_id: str, current_user: User = Depends(get_current_active_user)
):
    """
    Acknowledge an Event.
    """
    if not check_permission(UserPermission.EVENT_ACK, current_user):
        raise HTTPException(
            status_code=403, detail="Not authorized to acknowledge events"
        )
    return event_service.ack_event(event_id, current_user.username)


@router.post("/{event_id}/close")
async def close_event(
    event_id: str, current_user: User = Depends(get_current_active_user)
):
    """
    Close an Event manually.
    """
    if not check_permission(UserPermission.EVENT_CLOSE, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to close events")
    return event_service.close_event(event_id, current_user.username)


@router.post("/{event_id}/comment")
async def add_event_comment(
    event_id: str,
    comment: EventComment,
    current_user: User = Depends(get_current_active_user),
):
    """
    Append a user comment to the Event history.
    """
    return event_service.add_event_comment(
        event_id, current_user.username, comment.message
    )


@router.post("/prune")
async def prune_recovered_events(current_user: User = Depends(get_current_active_user)):
    """
    Bulk Close all 'RECOVERED' events.
    """
    if not check_permission(UserPermission.EVENT_CLOSE, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to prune events")
    return event_service.prune_recovered_events(current_user.username)


@router.post("/{event_id}/diagnose")
async def run_event_diagnostic_endpoint(
    event_id: str, current_user: User = Depends(get_current_active_user)
):
    """
    Run an on-demand diagnostic (Ping/SNMP) for the CI related to this event.
    """
    if not check_permission(UserPermission.RUN_DIAGNOSTICS, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to run diagnostics")
    return event_service.run_event_diagnostic(event_id, current_user.username)
