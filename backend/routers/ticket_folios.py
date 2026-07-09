"""Routers for ITSM ticket/folio lifecycle.

These endpoints are intentionally isolated from catalog/event automation.
They expose CRUD + transition operations for ticket folios without
creating or mutating event relationships as part of this slice.
"""

from __future__ import annotations

from typing import Annotated, Any

import services.ticket_folio_service as ticket_folio_service
from fastapi import APIRouter, Depends, HTTPException, Query
from models.itsm import TicketFolioCreate, TicketFolioUpdate
from models.user import User, UserPermission
from pydantic import BaseModel
from services.auth_service import check_permission, get_current_active_user


class TicketTransitionRequest(BaseModel):
    next_status: str
    closed_reason: str | None = None



CurrentUserDep = Annotated[User, Depends(get_current_active_user)]
LimitQuery = Annotated[int, Query(ge=1, le=500)]

router = APIRouter(prefix="/itsm/tickets", tags=["ITSM Tickets"])


@router.get("", response_model=list[dict[str, Any]])
async def list_ticket_folios(
    current_user: CurrentUserDep,
    status: str | None = None,
    service_catalog_id: str | None = None,
    archived: bool | None = None,
    limit: LimitQuery = 100,
):
    if not check_permission(UserPermission.ITSM_VIEW, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to view tickets")
    return ticket_folio_service.list_ticket_folios(
        status=status,
        service_catalog_id=service_catalog_id,
        archived=archived,
        limit=limit,
    )


@router.get("/{ticket_id}", response_model=dict[str, Any])
async def get_ticket_folio(
    ticket_id: str,
    current_user: CurrentUserDep,
):
    if not check_permission(UserPermission.ITSM_VIEW, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to view tickets")
    return ticket_folio_service.get_ticket_folio(ticket_id)


@router.post("", response_model=dict[str, Any])
async def create_ticket_folio(
    payload: TicketFolioCreate,
    current_user: CurrentUserDep,
):
    if not check_permission(UserPermission.ITSM_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to create tickets")
    return ticket_folio_service.create_ticket_folio(
        payload,
        actor=current_user.username,
    )


@router.put("/{ticket_id}", response_model=dict[str, Any])
async def update_ticket_folio(
    ticket_id: str,
    payload: TicketFolioUpdate,
    current_user: CurrentUserDep,
):
    if not check_permission(UserPermission.ITSM_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to update tickets")
    return ticket_folio_service.update_ticket_folio(
        ticket_id,
        payload,
        actor=current_user.username,
    )


@router.post("/{ticket_id}/transition", response_model=dict[str, Any])
async def transition_ticket_folio(
    ticket_id: str,
    payload: TicketTransitionRequest,
    current_user: CurrentUserDep,
):
    if not check_permission(UserPermission.ITSM_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to transition tickets")
    return ticket_folio_service.transition_ticket_folio(
        ticket_id,
        next_status=payload.next_status,
        closed_reason=payload.closed_reason,
        actor=current_user.username,
    )
