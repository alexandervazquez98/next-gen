import os
from datetime import timedelta
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
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
from models.refresh_token import generate_opaque_token
from services.session_policy import (
    resolve_session_policy_for_user,
    session_policy_cookie_max_age_seconds,
    access_token_max_age_seconds,
)
from utils.security import verify_password, get_password_hash
from postgres_db import get_pg_db
from repositories import user_repo
from models.user import Token, User, PasswordChangeRequest
from models.refresh_token import RefreshTokenResponse
from middleware.rate_limit import (
    check_rate_limit,
    clear_attempts,
    increment_attempts,
    raise_rate_limit_locked,
    refresh_token_rate_limit_key,
)

# ── Cookie domain and security (parsed once at import) ─────────────────────────

def _get_cookie_domain_and_secure() -> tuple[str | None, bool]:
    """
    Parse FRONTEND_ORIGIN for hostname and scheme, or use COOKIE_SECURE override.
    Returns (domain, secure) tuple where:
    - domain: hostname from FRONTEND_ORIGIN, or COOKIE_DOMAIN override
    - secure: True only when FRONTEND_ORIGIN uses https scheme, or overridden by COOKIE_SECURE env var
    """
    # 1. Determine secure: check COOKIE_SECURE first, fallback to FRONTEND_ORIGIN scheme
    cookie_secure_env = os.environ.get("COOKIE_SECURE")
    if cookie_secure_env is not None:
        secure = cookie_secure_env.lower() in ("true", "1", "yes", "on")
    else:
        origin = os.environ.get("FRONTEND_ORIGIN", "")
        secure = urlparse(origin).scheme == "https" if origin else False

    # 2. Determine domain: check COOKIE_DOMAIN first, fallback to FRONTEND_ORIGIN hostname
    explicit = os.environ.get("COOKIE_DOMAIN")
    if explicit:
        domain = None if explicit == "none" else explicit
        return domain, secure

    origin = os.environ.get("FRONTEND_ORIGIN", "")
    if not origin:
        return None, secure

    parsed = urlparse(origin)
    return parsed.hostname, secure


_COOKIE_DOMAIN, _COOKIE_SECURE = _get_cookie_domain_and_secure()


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
    responses={404: {"description": "Not found"}},
)


def _set_access_cookie(response: Response, token: str, domain: str | None = None, max_age_seconds: int | None = None) -> None:
    """Set HttpOnly cookie for access token."""
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",  # Allows cross-origin within same domain (port difference)
        path="/api",
        max_age=max_age_seconds or ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        domain=domain,
    )


def _clear_access_cookie(response: Response, domain: str | None = None) -> None:
    """Clear the access token cookie."""
    response.delete_cookie(key="access_token", path="/api", domain=domain)


def _set_refresh_cookie(response: Response, token: str, domain: str | None = None, max_age_seconds: int | None = None) -> None:
    """Set HttpOnly cookie for refresh token."""
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",  # Allows cross-origin within same domain (port difference)
        path="/api",
        max_age=max_age_seconds or 7 * 24 * 60 * 60,  # 7 days
        domain=domain,
    )


def _clear_refresh_cookie(response: Response, domain: str | None = None) -> None:
    """Clear the refresh token cookie."""
    response.delete_cookie(key="refresh_token", path="/api", domain=domain)


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
        # Increment failed attempts and return 429 as soon as this failure locks the identity.
        attempt_info = increment_attempts(form_data.username)
        if attempt_info.locked_until:
            raise_rate_limit_locked(attempt_info.locked_until)
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

    # Resolve policy from configured profile mapping
    policy = resolve_session_policy_for_user(user)

    # Create access and refresh tokens with policy-aware expiry
    access_token_expires = timedelta(minutes=policy.access_token_minutes)
    role_value = user.role.value if hasattr(user.role, 'value') else user.role
    session_id = generate_opaque_token()
    access_token = create_access_token(
        data={
            "sub": user.username,
            "role": role_value,
            "sid": session_id,
            "profile": policy.profile,
        },
        expires_delta=access_token_expires,
    )

    refresh_token = create_refresh_token(user.id, db, policy=policy, session_id=session_id)

    # Set HttpOnly cookies
    _set_access_cookie(
        response,
        access_token,
        domain=_COOKIE_DOMAIN,
        max_age_seconds=access_token_max_age_seconds(policy),
    )
    _set_refresh_cookie(
        response,
        refresh_token,
        domain=_COOKIE_DOMAIN,
        max_age_seconds=session_policy_cookie_max_age_seconds(policy),
    )

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
        # Fallback: check if passed in raw request body (e.g. from tests or non-browser clients)
        try:
            body = await request.body()
            if body:
                refresh_token = body.decode("utf-8").strip()
                # If body is JSON, extract refresh_token key if present
                if refresh_token.startswith("{"):
                    import json
                    try:
                        data = json.loads(refresh_token)
                        if isinstance(data, dict):
                            refresh_token = data.get("refresh_token", refresh_token)
                    except Exception:
                        pass
        except Exception:
            pass

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token cookie",
        )

    # Track failed attempts by hashed token identifier before token verification.
    rate_limit_key = refresh_token_rate_limit_key(refresh_token)
    check_rate_limit(rate_limit_key, identity_type="refresh_token")

    # Verify refresh token and optionally keep session lineage for refresh rotation continuity.
    verified = verify_refresh_token(refresh_token, db, include_session_metadata=True)
    if verified is None:
        attempt_info = increment_attempts(rate_limit_key, identity_type="refresh_token")
        if attempt_info.locked_until:
            raise_rate_limit_locked(attempt_info.locked_until)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if isinstance(verified, tuple):
        user_id, session_id = verified
    else:
        user_id = verified
        session_id = None

    # Keep stable session lineage across refreshes so authenticated requests
    # can correlate activity to a single logical session.
    session_id = session_id or generate_opaque_token()

    # Revoke old refresh token (single-use rotation)
    revoke_refresh_token(refresh_token, db)

    # Get user by ID
    db_user = user_repo.get_user_by_id(db, user_id)
    if db_user is None or not db_user.is_active:
        attempt_info = increment_attempts(rate_limit_key, identity_type="refresh_token")
        if attempt_info.locked_until:
            raise_rate_limit_locked(attempt_info.locked_until)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    # Successful refresh — clear failed attempts for this token
    clear_attempts(rate_limit_key, identity_type="refresh_token")

    # Create new access token
    # Keep existing behaviour for PR1: use standard policy for refresh flow.
    # Policy-aware recovery logic is deferred to PR2.
    policy = resolve_session_policy_for_user(db_user)

    access_token_expires = timedelta(minutes=policy.access_token_minutes)
    role_value = db_user.role.value if hasattr(db_user.role, 'value') else db_user.role
    access_token = create_access_token(
        data={
            "sub": db_user.username,
            "role": role_value,
            "sid": session_id,
            "profile": policy.profile,
        },
        expires_delta=access_token_expires,
    )

    # Create new refresh token
    new_refresh_token = create_refresh_token(db_user.id, db, policy=policy, session_id=session_id)

    # Set new access token cookie
    _set_access_cookie(
        response,
        access_token,
        domain=_COOKIE_DOMAIN,
        max_age_seconds=access_token_max_age_seconds(policy),
    )

    # Set refresh token in HTTP-only cookie (rotation)
    _set_refresh_cookie(
        response,
        new_refresh_token,
        domain=_COOKIE_DOMAIN,
        max_age_seconds=session_policy_cookie_max_age_seconds(policy),
    )

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
    _clear_access_cookie(response, domain=_COOKIE_DOMAIN)
    _clear_refresh_cookie(response, domain=_COOKIE_DOMAIN)
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