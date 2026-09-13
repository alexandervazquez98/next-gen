"""HTTP router for /api/cmdb/proposals/* — feat-cmdb-ai-handoff.

Five endpoints (T-2.1..T-2.5) gated on ``FEATURE_CMDB_PROPOSALS_ENABLED``
(default off → 404 when off) so unflagged deployments stay silent.

Permission matrix (REQ-CMAP-004/005):
- POST create: AI_PROPOSE_CI (or Admin) — 403 otherwise
- GET list/detail: CI_VIEW — 403 otherwise
- POST approve/revoke: CI_APPROVE_PROPOSAL — 403 otherwise

Error contract is forwarded from the service layer (HTTPException with
``detail.reason`` keys). Guardrail denials return 200 with
``harness_result.denied=true`` (REQ-CMAP-011).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response

from models.user import (
    AIPermission,
    User,
    UserPermission,
    UserRole,
)
from services.auth_service import check_permission as user_check_permission, get_current_active_user

logger = logging.getLogger(__name__)

FEATURE_FLAG_ENV = "FEATURE_CMDB_PROPOSALS_ENABLED"


def _feature_enabled() -> bool:
    raw = os.getenv(FEATURE_FLAG_ENV, "false").strip().lower()
    return raw in ("1", "true", "yes", "on", "enabled")


def _feature_flag_or_404() -> None:
    """Dependency that short-circuits every endpoint when the flag is off."""
    if not _feature_enabled():
        raise HTTPException(status_code=404, detail="feature_disabled")


def _user_has_ai_propose_ci(user: User) -> bool:
    if user.role == UserRole.ADMIN.value or user.role == "ADMIN":
        return True
    return AIPermission.AI_PROPOSE_CI.value in (user.permissions or [])


def _user_has_ci_approve_proposal(user: User) -> bool:
    if user.role == UserRole.ADMIN.value or user.role == "ADMIN":
        return True
    return UserPermission.CI_APPROVE_PROPOSAL.value in (user.permissions or [])


router = APIRouter(
    prefix="/cmdb/proposals",
    tags=["CMDB Proposals"],
    dependencies=[Depends(_feature_flag_or_404)],
)


@router.post("")
async def create_proposal(
    request: Request,
    response: Response,
    manifest: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_active_user),
):
    """POST /api/cmdb/proposals — submit a CI manifest (AI_PROPOSE_CI required).

    Returns 201 on success, 200 with ``harness_result.denied=true`` on guardrail denial.
    """
    if not _user_has_ai_propose_ci(current_user):
        raise HTTPException(
            status_code=403,
            detail="missing_permission: AI_PROPOSE_CI required to propose a CI",
        )

    # Lazy import so the router stays importable even when the service layer
    # hasn't fully loaded (test seams).
    from services import cmdb_proposal_service as svc

    result = svc.create_proposal(
        manifest=manifest,
        user=current_user,
        ai_agent_id=current_user.username,
        db=None,
        request=request,
    )

    # Guardrail denial comes back as {harness_result: {...}}; forward as 200.
    if isinstance(result, dict) and result.get("harness_result", {}).get("denied"):
        response.status_code = 200
        return result

    response.status_code = 201
    return {
        "proposal_id": result["id"],
        "status": result["status"],
        "version": result["version"],
        "created_at": result.get("created_at"),
        "resulted_ci_id": result.get("resulted_ci_id"),
    }


@router.get("")
async def list_proposals(
    status: str | None = Query(None),
    category: str | None = Query(None),
    proposed_by: str | None = Query(None),
    created_from: str | None = Query(None),
    created_to: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
):
    """GET /api/cmdb/proposals — paginated list with filters (CI_VIEW required)."""
    if not user_check_permission(UserPermission.CI_VIEW, current_user):
        raise HTTPException(
            status_code=403, detail="missing_permission: CI_VIEW required"
        )

    from services import cmdb_proposal_service as svc

    return svc.list_proposals(
        status=status,
        category=category,
        proposed_by=proposed_by,
        created_from=created_from,
        created_to=created_to,
        page=page,
        page_size=page_size,
    )


@router.get("/count")
async def count_proposals(
    status: str | None = Query(None),
    current_user: User = Depends(get_current_active_user),
):
    """GET /api/cmdb/proposals/count?status=DRAFT — total count for the badge (CI_VIEW)."""
    if not user_check_permission(UserPermission.CI_VIEW, current_user):
        raise HTTPException(
            status_code=403, detail="missing_permission: CI_VIEW required"
        )

    from services import cmdb_proposal_service as svc

    repo = svc._get_repo()
    # Pull up to page_size=1 rows just to read `total`; for a dedicated endpoint
    # the service would expose a count() method. Use a high page_size to count
    # up to 10k drafts without paging — the badge never needs an exact count
    # above that.
    rows = repo.list(status=status, page=1, page_size=10_000)
    return {"count": len(rows)}


@router.get("/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """GET /api/cmdb/proposals/{id} — full row + manifest (CI_VIEW required)."""
    if not user_check_permission(UserPermission.CI_VIEW, current_user):
        raise HTTPException(
            status_code=403, detail="missing_permission: CI_VIEW required"
        )

    from services import cmdb_proposal_service as svc

    row = svc.get_proposal(proposal_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"reason": "proposal_not_found"})
    return row


@router.post("/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    request: Request = None,
    current_user: User = Depends(get_current_active_user),
):
    """POST /api/cmdb/proposals/{id}/approve — human approval gate."""
    if not _user_has_ci_approve_proposal(current_user):
        raise HTTPException(
            status_code=403,
            detail="missing_permission: CI_APPROVE_PROPOSAL required",
        )

    expected_version = int(body.get("version") or 1)
    expected_category = body.get("expected_category")

    from services import cmdb_proposal_service as svc

    row = svc.approve_proposal(
        proposal_id=proposal_id,
        expected_version=expected_version,
        user=current_user,
        db=None,
        expected_category=expected_category,
        request=request,
    )
    return {
        "proposal_id": row["id"],
        "status": row["status"],
        "version": row["version"],
        "resulted_ci_id": row.get("resulted_ci_id"),
    }


@router.post("/{proposal_id}/revoke")
async def revoke_proposal(
    proposal_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    request: Request = None,
    current_user: User = Depends(get_current_active_user),
):
    """POST /api/cmdb/proposals/{id}/revoke — DRAFT/APPROVED -> REVOKED."""
    if not _user_has_ci_approve_proposal(current_user):
        raise HTTPException(
            status_code=403,
            detail="missing_permission: CI_APPROVE_PROPOSAL required",
        )

    expected_version = int(body.get("version") or 1)
    reason = body.get("reason")

    from services import cmdb_proposal_service as svc

    row = svc.revoke_proposal(
        proposal_id=proposal_id,
        expected_version=expected_version,
        user=current_user,
        reason=reason,
        db=None,
        request=request,
    )
    return {
        "proposal_id": row["id"],
        "status": row["status"],
        "version": row["version"],
    }