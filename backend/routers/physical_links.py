"""HTTP router for /api/cmdb/physical-links — feat-444-physical-link-styling (slice 2).

Slice 2/4 of the fiber-optic / physical-link visualization chain (#444). Four
endpoints mirror the cmdb_proposals router pattern; the underlying model +
migration shipped in slice 1 (#323).

Auth model (mirrors ``backend/routers/links.py`` tunnel-link precedent):
- Reads (``GET`` list / by-id): **public**. ``current_user: User | None = None``
  is the parameter; the service layer skips CI_VIEW enforcement when the
  caller is anonymous. This lets the Geo View (and other anonymous graph
  consumers) poll PhysicalLink data without 401-ing.
- Writes (``POST`` create / ``PATCH`` status): **authenticated**. The auth
  dep raises 401 automatically when no Bearer is supplied; CI_EDIT is
  required by the service layer (Admin bypasses).

Permission gate is enforced inside the service layer so router-level code
stays a thin HTTP wrapper.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from models.user import User
from schemas.physical_link import (
    PhysicalLinkCreateRequest,
    PhysicalLinkResponse,
    PhysicalLinkUpdateStatusRequest,
)
from services.auth_service import get_current_active_user

logger = logging.getLogger(__name__)

FEATURE_FLAG_ENV = "FEATURE_CMDB_PHYSICAL_LINKS_ENABLED"


def _feature_enabled() -> bool:
    """Mirror of ``routers.cmdb_proposals._feature_enabled``."""
    raw = os.getenv(FEATURE_FLAG_ENV, "false").strip().lower()
    return raw in ("1", "true", "yes", "on", "enabled")


def _feature_flag_or_404() -> None:
    """Short-circuit every endpoint when the flag is off (404, not 403)."""
    if not _feature_enabled():
        raise HTTPException(status_code=404, detail="feature_disabled")


router = APIRouter(
    prefix="/cmdb/physical-links",
    tags=["CMDB Physical Links"],
    dependencies=[Depends(_feature_flag_or_404)],
    responses={404: {"description": "Not found"}},
)


@router.post(
    "",
    response_model=PhysicalLinkResponse,
    status_code=201,
)
async def create_physical_link(
    payload: PhysicalLinkCreateRequest,
    response: Response,
    current_user: User = Depends(get_current_active_user),  # noqa: B008
) -> PhysicalLinkResponse:
    """POST /api/cmdb/physical-links — create a new PhysicalLink (CI_EDIT required).

    Auth dep raises 401 when no Bearer is supplied; the service layer
    enforces CI_EDIT (HTTP 403) and validates the Literal types + endpoint
    references (HTTP 400). Returns 201 + the wire-shape row on success.
    """
    from services import physical_link_service as svc

    row = svc.create_physical_link(
        payload=payload.model_dump(mode="json"),
        current_user=current_user,
    )
    return PhysicalLinkResponse(**row)


@router.get(
    "",
    response_model=list[PhysicalLinkResponse],
)
async def list_physical_links(
    ci_id: str | None = Query(default=None),
    type: str | None = Query(default=None, alias="type"),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: (
        User | None
    ) = None,  # noqa: B008 — public read; service enforces CI_VIEW when set.
) -> list[PhysicalLinkResponse]:
    """GET /api/cmdb/physical-links — list with optional filters.

    Public read (no auth required). When ``current_user`` is provided
    (e.g. an authenticated operator), CI_VIEW is enforced by the service
    layer. Admin always passes through.
    """
    from services import physical_link_service as svc

    rows = svc.list_physical_links(
        ci_id=ci_id,
        link_type=type,
        status=status,
        limit=limit,
        offset=offset,
        current_user=current_user,
    )
    return [PhysicalLinkResponse(**row) for row in rows]


@router.get(
    "/{link_id}",
    response_model=PhysicalLinkResponse,
)
async def get_physical_link(
    link_id: str,
    current_user: (
        User | None
    ) = None,  # noqa: B008 — public read; service enforces CI_VIEW when set.
) -> PhysicalLinkResponse:
    """GET /api/cmdb/physical-links/{id} — fetch one row by id (public read)."""
    from fastapi import HTTPException
    from services import physical_link_service as svc

    row = svc.get_physical_link(link_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"reason": "physical_link_not_found", "id": link_id},
        )
    # Optional CI_VIEW gate for authenticated callers (admin bypasses inside the service).
    if current_user is not None:
        from models.user import UserPermission, UserRole
        from services.auth_service import check_permission as _check_permission

        if (
            not _check_permission(UserPermission.CI_VIEW, current_user)
            and current_user.role != UserRole.ADMIN.value
        ):
            raise HTTPException(
                status_code=403,
                detail="missing_permission: CI_VIEW required to read PhysicalLink",
            )
    return PhysicalLinkResponse(**row)


@router.patch(
    "/{link_id}/status",
    response_model=PhysicalLinkResponse,
)
async def update_physical_link_status(
    link_id: str,
    payload: PhysicalLinkUpdateStatusRequest = Body(...),  # noqa: B008
    current_user: User = Depends(get_current_active_user),  # noqa: B008
) -> PhysicalLinkResponse:
    """PATCH /api/cmdb/physical-links/{id}/status — update the status literal (CI_EDIT required)."""
    from services import physical_link_service as svc

    row = svc.update_physical_link_status(
        link_id=link_id,
        status=payload.status,
        current_user=current_user,
    )
    return PhysicalLinkResponse(**row)
