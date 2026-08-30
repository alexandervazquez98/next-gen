"""Routers for ITSM ticket/folio lifecycle.

These endpoints are intentionally isolated from catalog/event automation.
They expose CRUD + transition operations for ticket folios without
creating or mutating event relationships as part of this slice.
"""

from __future__ import annotations

from typing import Annotated, Any

import services.ticket_folio_service as ticket_folio_service
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from models.itsm import TicketFolioCreate, TicketFolioResponse, TicketFolioUpdate
from models.user import User, UserPermission
from pydantic import BaseModel
from postgres_db import SessionLocal
from repositories.itsm_service_catalog_repo import ServiceCatalogRepository
from repositories.ticket_folio_repo import TicketFolioRepository
from repositories.user_repo import UserRepository
from services.auth_service import check_permission, get_current_active_user
from services.itsm_imports import ticket_import


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


@router.get("/{ticket_id}", response_model=TicketFolioResponse)
async def get_ticket_folio(
    ticket_id: int,
    current_user: CurrentUserDep,
):
    if not check_permission(UserPermission.ITSM_VIEW, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to view tickets")
    return ticket_folio_service.get_ticket_folio(ticket_id)


@router.post("", response_model=TicketFolioResponse)
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


@router.put("/{ticket_id}", response_model=TicketFolioResponse)
async def update_ticket_folio(
    ticket_id: int,
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


@router.post("/{ticket_id}/transition", response_model=TicketFolioResponse)
async def transition_ticket_folio(
    ticket_id: int,
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


# ---------------------------------------------------------------------------
# PR 4 — WU 7 atomic XLSX ticket import with reference sheets.
# ---------------------------------------------------------------------------


@router.get("/template")
async def get_ticket_template(
    current_user: CurrentUserDep,
) -> Response:
    if not check_permission(UserPermission.ITSM_VIEW, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to view tickets")
    workbook_bytes = ticket_import.build_ticket_template_workbook(
        catalog_repository=ServiceCatalogRepository(),
        user_repository=UserRepository(),
    )
    return Response(
        content=workbook_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ticket_import_template.xlsx"},
    )


@router.post("/import")
async def import_ticket_workbook(
    file: UploadFile = File(...),
    current_user: CurrentUserDep = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    if not check_permission(UserPermission.ITSM_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to import tickets")
    payload = await file.read()
    pg_session = SessionLocal()
    try:
        return ticket_import.import_ticket_workbook(
            payload,
            actor=current_user.username,
            ticket_repository=TicketFolioRepository(),
            catalog_repository=ServiceCatalogRepository(),
            user_repository=UserRepository(),
            pg_session=pg_session,
        )
    except Exception as exc:  # noqa: BLE001 — surface structured errors to the client
        pg_session.close()
        from services.itsm_imports.errors import ImportValidationError

        if isinstance(exc, ImportValidationError):
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail=exc.to_payload())
        raise
    finally:
        try:
            pg_session.close()
        except Exception:  # noqa: BLE001
            pass
