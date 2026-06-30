from fastapi import APIRouter, Body, Depends, HTTPException
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, ValidationError
from models.core import Link
from models.user import User
from services.auth_service import get_current_active_user
import services.link_service as link_service

router = APIRouter(
    prefix="",
    tags=["Topology"],
    responses={404: {"description": "Not found"}},
)


class MassLinkPayload(BaseModel):
    source_filter: Dict[str, Any]
    target_filter: Dict[str, Any]
    relationship: str


class CiIdsPayload(BaseModel):
    ci_ids: List[str]


class MassDeletePayload(BaseModel):
    source_filter: Dict[str, Any]
    target_filter: Dict[str, Any]
    relationship: str


class MassUpdatePayload(BaseModel):
    source_filter: Dict[str, Any]
    target_filter: Dict[str, Any]
    old_relationship: str
    new_relationship: str


@router.get("/links", response_model=List[Dict[str, Any]])
async def get_links(current_user: User = Depends(get_current_active_user)):
    """
    Fetch all active relationship links.
    Enforces data scoping based on user allowed locations.
    """
    return link_service.get_links(current_user)


@router.post("/links")
async def create_link(
    link_payload: Dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_active_user),
):
    """
    Create a new relationship (edge) between two nodes.
    """
    from services.auth_service import check_permission
    from models.user import UserPermission

    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Permission denied: CI_EDIT required")

    try:
        link = Link.model_validate(link_payload)
    except ValidationError as exc:
        if any(error.get("loc") == ("medium",) for error in exc.errors()):
            raise HTTPException(status_code=400, detail="invalid medium") from exc
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    return link_service.create_link(link)


@router.delete("/links")
async def delete_link(link: Link, current_user: User = Depends(get_current_active_user)):
    """
    Delete a relationship between two nodes.
    """
    from services.auth_service import check_permission
    from models.user import UserPermission

    if not check_permission(UserPermission.CI_DELETE, current_user):
        raise HTTPException(status_code=403, detail="Permission denied: CI_DELETE required")
    return link_service.delete_link(link)


@router.post("/cis/relationships")
async def get_cis_relationships(
    payload: CiIdsPayload, current_user: User = Depends(get_current_active_user)
):
    """
    Batch-fetch relationship summary for a list of CI ids.
    Returns {ci_id: {asSource: [...], asTarget: [...]}}.
    """
    return link_service.get_cis_relationships(payload.ci_ids, current_user)


@router.post("/links/mass/simulate")
async def simulate_mass_links(
    payload: MassLinkPayload, current_user: User = Depends(get_current_active_user)
):
    """
    Simulates a bulk link creation and returns impact.
    Requires CI_EDIT permission.
    """
    from services.auth_service import check_permission
    from models.user import UserPermission

    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Permission denied: CI_EDIT required")

    return link_service.simulate_bulk_links(
        current_user, payload.source_filter, payload.target_filter
    )


@router.post("/links/mass")
async def execute_mass_links(
    payload: MassLinkPayload, current_user: User = Depends(get_current_active_user)
):
    """
    Executes a bulk link creation.
    Requires CI_EDIT permission.
    """
    from services.auth_service import check_permission
    from models.user import UserPermission

    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Permission denied: CI_EDIT required")

    return link_service.execute_bulk_links(
        current_user, payload.source_filter, payload.target_filter, payload.relationship
    )


@router.delete("/links/mass")
async def delete_mass_links(
    payload: MassDeletePayload, current_user: User = Depends(get_current_active_user)
):
    """
    Executes a bulk link deletion.
    Requires CI_DELETE permission.
    """
    from services.auth_service import check_permission
    from models.user import UserPermission

    if not check_permission(UserPermission.CI_DELETE, current_user):
        raise HTTPException(status_code=403, detail="Permission denied: CI_DELETE required")

    return link_service.execute_bulk_delete(
        current_user, payload.source_filter, payload.target_filter, payload.relationship
    )


@router.put("/links/mass")
async def update_mass_links(
    payload: MassUpdatePayload, current_user: User = Depends(get_current_active_user)
):
    """
    Executes a bulk link update (change relationship type).
    Requires CI_EDIT permission.
    """
    from services.auth_service import check_permission
    from models.user import UserPermission

    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Permission denied: CI_EDIT required")

    return link_service.execute_bulk_update(
        current_user,
        payload.source_filter,
        payload.target_filter,
        payload.old_relationship,
        payload.new_relationship,
    )


@router.get("/graph/full")
async def get_full_graph(
    layer: Optional[str] = None,
    location: Optional[str] = None,
    owner: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
):
    """
    Fetch the COMPLETE graph topology.
    Supports filtering by metadata and data scoping.
    """
    return link_service.get_full_graph(current_user, layer=layer, location=location, owner=owner)
