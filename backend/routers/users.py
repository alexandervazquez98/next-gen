from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from services.auth_service import get_current_active_user, check_permission
from utils.security import get_password_hash
from models.user import User, UserCreate, UserUpdate, UserRole, UserPermission, UserResetRequest
from postgres_db import get_pg_db
from repositories import user_repo
from models.sql_models import User as PgUser

router = APIRouter(
    prefix="/api/users",
    tags=["Users"],
    responses={404: {"description": "Not found"}},
)

# Helper to convert PG Model to Pydantic Model
def map_pg_user_to_pydantic(pg_user: PgUser) -> User:
    return User(
        username=pg_user.username,
        role=pg_user.role,
        permissions=pg_user.permissions,
        allowed_locations=pg_user.allowed_locations,
        allowed_ci_types=pg_user.allowed_ci_types,
        phone=pg_user.phone,
        email=pg_user.email,
        disabled=not pg_user.is_active,
        force_password_change=pg_user.force_password_change
    )

@router.get("/", response_model=List[User])
async def list_users(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db)
):
    if not check_permission(UserPermission.USER_MANAGE, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to view users")
    
    users = user_repo.get_users(db)
    return [map_pg_user_to_pydantic(u) for u in users]

@router.post("/", response_model=User)
async def create_user(
    user: UserCreate, 
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db)
):
    if not check_permission(UserPermission.USER_MANAGE, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to create users")
    
    existing = user_repo.get_user_by_username(db, user.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    new_user = user_repo.create_user(db, user)
    return map_pg_user_to_pydantic(new_user)

@router.put("/{username}", response_model=User)
async def update_user(
    username: str, 
    update_data: UserUpdate, 
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db)
):
    if not check_permission(UserPermission.USER_MANAGE, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to update users")

    updated_user = user_repo.update_user(db, username, update_data)
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    return map_pg_user_to_pydantic(updated_user)

@router.delete("/{username}")
async def delete_user(
    username: str, 
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db)
):
    if not check_permission(UserPermission.USER_MANAGE, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to delete users")
    
    success = user_repo.delete_user(db, username)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
        
    return {"status": "success", "message": f"User {username} deleted"}

@router.post("/{username}/reset")
async def reset_password(
    username: str, 
    reset_data: UserResetRequest = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db)
):
    if not check_permission(UserPermission.USER_MANAGE, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to reset passwords")
    
    if not reset_data or not reset_data.new_password:
         raise HTTPException(status_code=400, detail="New password required")

    # Reuse update logic
    update_payload = UserUpdate(password=reset_data.new_password)
    # Also set force_password_change = True (Need to add this to Repo update logic or handle manually here)
    # For simplicity, we restart manual update:
    
    db_user = user_repo.get_user_by_username(db, username)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    db_user.hashed_password = get_password_hash(reset_data.new_password)
    db_user.force_password_change = True
    db.commit()
        
    return {"status": "success", "message": f"Password reset for {username}."}
