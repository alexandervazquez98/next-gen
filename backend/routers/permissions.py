from fastapi import APIRouter, Depends
from models.user import User, UserPermission, AIPermission
from services.auth_service import get_current_active_user

router = APIRouter(
    prefix="/permissions",
    tags=["Permissions"],
    responses={401: {"description": "Not authenticated"}},
)


@router.get("/")
async def get_permissions(current_user: User = Depends(get_current_active_user)):
    """Return all human and AI permission enum values."""
    return {
        "human": [p.value for p in UserPermission],
        "ai": [p.value for p in AIPermission],
    }
