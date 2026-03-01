from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from services.auth_service import (
    ACCESS_TOKEN_EXPIRE_MINUTES, 
    create_access_token, 
    get_current_active_user
)
from utils.security import verify_password, get_password_hash
from postgres_db import get_pg_db
from repositories import user_repo
from models.user import Token, User, PasswordChangeRequest

router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"],
    responses={404: {"description": "Not found"}},
)

@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_pg_db)
):
    # Verify user in Postgres
    user = user_repo.get_user_by_username(db, form_data.username)
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

    # Step 3: Create Token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user

@router.post("/change-password")
async def change_password(
    password_data: PasswordChangeRequest, 
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db)
):
    # In Pydantic User model (current_user), password field might be hash or empty depending on projection.
    # We should fetch DB user to verify old password hash correctly if not present in token user object.
    
    db_user = user_repo.get_user_by_username(db, current_user.username)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(password_data.old_password, db_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect old password")
        
    db_user.hashed_password = get_password_hash(password_data.new_password)
    db_user.force_password_change = False
    db.commit()
    
    return {"status": "success", "message": "Password updated successfully"}
