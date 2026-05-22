from datetime import timedelta
from fastapi import APIRouter, Body, Cookie, Depends, HTTPException, status, Response, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from services.auth_service import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    revoke_refresh_token,
    revoke_all_user_refresh_tokens,
    get_current_active_user,
)
from utils.security import verify_password, get_password_hash
from postgres_db import get_pg_db
from repositories import user_repo
from models.user import Token, User, PasswordChangeRequest
from models.refresh_token import RefreshTokenResponse
from middleware.rate_limit import check_rate_limit, clear_attempts

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
    responses={404: {"description": "Not found"}},
)


def _set_access_cookie(response: Response, token: str) -> None:
    """Set HttpOnly, Secure, SameSite=Strict cookie on the response."""
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/api",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def _clear_access_cookie(response: Response) -> None:
    """Clear the access token cookie."""
    response.delete_cookie(key="access_token", path="/api")


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Set HttpOnly, Secure, SameSite=Strict cookie for refresh token."""
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/api",
        max_age=7 * 24 * 60 * 60,  # 7 days
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Clear the refresh token cookie."""
    response.delete_cookie(key="refresh_token", path="/api")


@router.post("/token", response_model=Token)
async def login_for_access_token(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_pg_db),
):
    # Check rate limit before processing
    check_rate_limit(form_data.username)

    # Verify user in Postgres
    user = user_repo.get_user_by_username(db, form_data.username)

    if not user or not verify_password(form_data.password, user.hashed_password):
        # Increment failed attempts
        from middleware.rate_limit import increment_attempts
        increment_attempts(form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user"
        )

    # Successful login — clear rate limit attempts
    clear_attempts(form_data.username)

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    role_value = user.role.value if hasattr(user.role, 'value') else user.role
    access_token = create_access_token(
        data={"sub": user.username, "role": role_value},
        expires_delta=access_token_expires,
    )

    # Set HttpOnly cookie
    _set_access_cookie(response, access_token)

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_tokens(
    request: Request,
    response: Response,
    db: Session = Depends(get_pg_db),
):
    """
    Accept refresh token from HttpOnly cookie, verify it, rotate tokens.
    Revokes the old refresh token and issues a new access token cookie
    plus a new refresh token cookie (single-use rotation).
    """
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token cookie",
        )

    # Verify refresh token
    user_id = verify_refresh_token(refresh_token, db)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Revoke old refresh token (single-use rotation)
    revoke_refresh_token(refresh_token, db)

    # Get user by ID
    db_user = user_repo.get_user_by_id(db, user_id)
    if db_user is None or not db_user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    # Create new access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    role_value = db_user.role.value if hasattr(db_user.role, 'value') else db_user.role
    access_token = create_access_token(
        data={"sub": db_user.username, "role": role_value},
        expires_delta=access_token_expires,
    )

    # Create new refresh token
    new_refresh_token = create_refresh_token(db_user.id, db)

    # Set new access token cookie
    _set_access_cookie(response, access_token)

    # Set refresh token in HTTP-only cookie (rotation)
    _set_refresh_cookie(response, new_refresh_token)

    return RefreshTokenResponse(access_token=access_token)


@router.post("/logout")
async def logout(
    response: Response,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db),
):
    """
    Revoke all refresh tokens for the current user and clear the access cookie.
    """
    # Get the DB user to retrieve the integer id
    db_user = user_repo.get_user_by_username(db, current_user.username)
    if db_user is not None:
        revoke_all_user_refresh_tokens(db_user.id, db)
    _clear_access_cookie(response)
    _clear_refresh_cookie(response)
    return {"status": "success", "message": "Logged out"}


@router.get("/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user


@router.post("/change-password")
async def change_password(
    password_data: PasswordChangeRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db),
):
    # Rate limit check to prevent brute force on password change
    check_rate_limit(current_user.username)

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