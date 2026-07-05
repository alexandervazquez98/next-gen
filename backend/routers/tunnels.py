from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from models.user import User
from repositories import topology_repo
from services.auth_service import get_current_active_user
from services.tunnel_health import TunnelHealthResponse, decode_link_id

router = APIRouter(
    prefix="/tunnels",
    tags=["Tunnels"],
    responses={404: {"description": "Not found"}},
)


@router.get("/{link_id}/health", response_model=TunnelHealthResponse)
async def get_tunnel_health(
    link_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    try:
        identity = decode_link_id(link_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid tunnel link id") from exc

    is_admin = current_user.role == "ADMIN"
    allowed_locations = current_user.allowed_locations
    health = topology_repo.get_tunnel_health_link(
        identity,
        allowed_locations=allowed_locations,
        is_admin=is_admin,
    )
    if health is None:
        raise HTTPException(status_code=404, detail="Tunnel link not found")
    return health
