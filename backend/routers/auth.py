import os
from datetime import timedelta
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from services.auth_service import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    RefreshVerificationStatus,
    create_access_token,
    create_refresh_token,
    try_increment_refresh_recovery_count,
    rotate_refresh_token,
    revoke_refresh_token,
    revoke_all_user_refresh_tokens,
    verify_refresh_token,
    record_session_activity,
    get_current_active_user,
)
from models.refresh_token import generate_opaque_token, RefreshToken
from services.session_policy import (
    resolve_session_policy_for_user,
    session_policy_cookie_max_age_seconds,
    access_token_max_age_seconds,
    get_session_activity_write_throttle_seconds,
)
from services import audit_service
from utils.security import verify_password, get_password_hash
from postgres_db import get_pg_db
from repositories import user_repo
from models.user import Token, User, PasswordChangeRequest, CurrentUser
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


# Standardized audit outcomes and event names for auth lifecycle capture.
AUDIT_OUTCOME_SUCCESS = "SUCCESS"
AUDIT_OUTCOME_FAILURE = "FAILURE"
AUDIT_OUTCOME_DENIED = "DENIED"

AUTH_EVENT_LOGIN_SUCCESS = "LOGIN_SUCCESS"
AUTH_EVENT_LOGIN_FAILURE = "LOGIN_FAILURE"
AUTH_EVENT_LOGOUT = "LOGOUT"

AUTH_REASON_INCORRECT_CREDENTIALS = "incorrect_credentials"
AUTH_REASON_INACTIVE_USER = "inactive_user"
AUTH_REASON_RATE_LIMITED = "rate_limited"
AUTH_REASON_LOGIN_SUCCESS = "login_success"
AUTH_REASON_LOGOUT_SUCCESS = "logout_success"


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
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_pg_db),
):
    try:
        # Check rate limit before processing
        check_rate_limit(form_data.username)
    except HTTPException:
        audit_service.record_auth_event(
            db=db,
            request=request,
            event_type=AUTH_EVENT_LOGIN_FAILURE,
            outcome=AUDIT_OUTCOME_DENIED,
            actor_username=form_data.username,
            reason=AUTH_REASON_RATE_LIMITED,
        )
        raise

    # Verify user in Postgres
    user = user_repo.get_user_by_username(db, form_data.username)

    if not user or not verify_password(form_data.password, user.hashed_password):
        # Increment failed attempts and return 429 as soon as this failure locks the identity.
        attempt_info = increment_attempts(form_data.username)
        if attempt_info.locked_until:
            audit_service.record_auth_event(
                db=db,
                request=request,
                event_type=AUTH_EVENT_LOGIN_FAILURE,
                outcome=AUDIT_OUTCOME_DENIED,
                actor_username=form_data.username,
                reason=AUTH_REASON_RATE_LIMITED,
            )
            raise_rate_limit_locked(attempt_info.locked_until)

        audit_service.record_auth_event(
            db=db,
            request=request,
            event_type=AUTH_EVENT_LOGIN_FAILURE,
            outcome=AUDIT_OUTCOME_FAILURE,
            actor_username=form_data.username,
            reason=AUTH_REASON_INCORRECT_CREDENTIALS,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        audit_service.record_auth_event(
            db=db,
            request=request,
            event_type=AUTH_EVENT_LOGIN_FAILURE,
            outcome=AUDIT_OUTCOME_DENIED,
            actor_username=form_data.username,
            reason=AUTH_REASON_INACTIVE_USER,
        )
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

    audit_service.record_auth_event(
        db=db,
        request=request,
        event_type=AUTH_EVENT_LOGIN_SUCCESS,
        outcome=AUDIT_OUTCOME_SUCCESS,
        actor_username=user.username,
        reason=AUTH_REASON_LOGIN_SUCCESS,
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
    verification = verify_refresh_token(refresh_token, db)

    if verification.status == RefreshVerificationStatus.MISSING:
        attempt_info = increment_attempts(rate_limit_key, identity_type="refresh_token")
        if attempt_info.locked_until:
            raise_rate_limit_locked(attempt_info.locked_until)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if verification.status == RefreshVerificationStatus.EXPIRED:
        increment_attempts(rate_limit_key, identity_type="refresh_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
        )

    if verification.status == RefreshVerificationStatus.REVOKED:
        increment_attempts(rate_limit_key, identity_type="refresh_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session revoked",
        )

    if verification.status == RefreshVerificationStatus.IDLE_EXPIRED:
        increment_attempts(rate_limit_key, identity_type="refresh_token")
        # PR1 #287: emit the lifecycle audit event for idle expiry. The DB
        # anchor may be `last_activity_at` or the COALESCE fallback to
        # `created_at` for transitional NULL rows (see _is_token_idle_expired).
        idle_anchor = "last_activity_at"
        if verification.token_id is not None:
            try:
                anchor_row = (
                    db.query(RefreshToken.last_activity_at, RefreshToken.created_at)
                    .filter(RefreshToken.id == verification.token_id)
                    .first()
                )
                if anchor_row is not None:
                    last_activity_at, created_at = anchor_row
                    idle_anchor = "last_activity_at" if last_activity_at is not None else "created_at"
            except Exception:
                # Audit must not block the 401 response.
                pass
        audit_service.record_auth_event(
            db=db,
            request=request,
            event_type="session.idle_expired",
            outcome=AUDIT_OUTCOME_DENIED,
            actor_username=verification.user_id and None,
            reason="idle_timeout",
            context={
                "session_id": verification.session_id,
                "user_id": verification.user_id,
                "policy_profile": verification.policy_profile,
                "activity_anchor": idle_anchor,
                # Mirror `session.activity_recorded` so dashboard cross-event
                # correlation stays coherent (warning from PR1 verify agent).
                "throttle_seconds": get_session_activity_write_throttle_seconds(),
            },
        )
        # Build a JSONResponse directly so the Set-Cookie headers reach the
        # client AND the route's `response_model=RefreshTokenResponse`
        # validation is bypassed (we are returning an error body, not a
        # token bundle). `raise HTTPException(...)` would discard the
        # cookie-clearing headers.
        idle_response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "session timed out"},
        )
        _clear_access_cookie(idle_response, domain=_COOKIE_DOMAIN)
        _clear_refresh_cookie(idle_response, domain=_COOKIE_DOMAIN)
        return idle_response

    if verification.status == RefreshVerificationStatus.USER_INACTIVE:
        increment_attempts(rate_limit_key, identity_type="refresh_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User inactive",
        )

    if verification.status == RefreshVerificationStatus.ROTATED_STALE_REJECTED:
        increment_attempts(rate_limit_key, identity_type="refresh_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="session expired",
        )

    user_id = verification.user_id
    if user_id is None:
        increment_attempts(rate_limit_key, identity_type="refresh_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    db_user = user_repo.get_user_by_id(db, user_id)
    if db_user is None or not db_user.is_active:
        increment_attempts(rate_limit_key, identity_type="refresh_token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    policy = resolve_session_policy_for_user(db_user)

    if verification.status == RefreshVerificationStatus.ROTATED_STALE_RECOVERABLE:
        if verification.token_id is None or not try_increment_refresh_recovery_count(
            db,
            verification.token_id,
            policy.stale_rotation_max_recoveries,
        ):
            increment_attempts(rate_limit_key, identity_type="refresh_token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="session expired",
            )

    # Successful refresh path, clear failed attempts.
    clear_attempts(rate_limit_key, identity_type="refresh_token")

    session_id = verification.session_id or generate_opaque_token()

    # Create new refresh token first so rotation can link replacement id.
    new_refresh_token, new_rt = create_refresh_token(
        db_user.id,
        db,
        policy=policy,
        session_id=session_id,
        return_token_row=True,
    )

    # Rotate old token for valid single-use semantics.
    if verification.status == RefreshVerificationStatus.VALID:
        rotate_refresh_token(db, old_refresh_token=refresh_token, new_refresh_token_id=new_rt.id)

    # Create new access token with stable session id and current policy.
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

    # PR1 #287: bump server-authoritative session activity for the
    # rotated refresh's session. The DB conditional UPDATE is throttled
    # cross-worker; this is a no-op on operational profile.
    record_session_activity(session_id, db_user.id, db, policy, request=request)

    return RefreshTokenResponse(access_token=access_token)


@router.post("/logout")
async def logout(
    request: Request,
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
    audit_service.record_auth_event(
        db=db,
        request=request,
        event_type=AUTH_EVENT_LOGOUT,
        outcome=AUDIT_OUTCOME_SUCCESS,
        actor_username=current_user.username,
        reason=AUTH_REASON_LOGOUT_SUCCESS,
    )
    return {"status": "success", "message": "Logged out"}


@router.get("/users/me", response_model=CurrentUser)
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