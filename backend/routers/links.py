from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any
from models.core import Link
from models.user import User
from services.auth_service import get_current_active_user
import services.link_service as link_service

router = APIRouter(
    prefix="/api",
    tags=["Topology"],
    responses={404: {"description": "Not found"}},
)

@router.get("/links", response_model=List[Dict[str, Any]])
async def get_links(current_user: User = Depends(get_current_active_user)):
    """
    Fetch all active relationship links between CIs and Metrics.
    """
    return link_service.get_links(current_user)

@router.post("/links")
async def create_link(link: Link, current_user: User = Depends(get_current_active_user)):
    """
    Create a new relationship (edge) between two nodes.
    """
    from services.auth_service import check_permission
    from models.user import UserPermission

    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Permission denied: CI_EDIT required")
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

@router.get("/graph/full")
async def get_full_graph(
    layer: str = None, 
    location: str = None, 
    owner: str = None,
    current_user: User = Depends(get_current_active_user)
):
    """
    Fetch the COMPLETE graph topology.
    Supports filtering by metadata (layer, location, owner).
    """
    return link_service.get_full_graph(current_user, layer=layer, location=location, owner=owner)
