import os
import secrets
import hashlib
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from models.user import TokenData, User, UserRole, UserPermission, UserInDB, AIPermission
from pydantic import BaseModel
from typing import Optional
from postgres_db import get_pg_db
from repositories import user_repo
from models.refresh_token import (
    RefreshToken,
    RefreshVerificationResult,
    RefreshVerificationStatus,
    hash_token,
    generate_opaque_token,
)
from services.session_policy import (
    SessionPolicy,
    get_standard_session_policy,
    get_session_policy_by_profile,
)

# ── Secret Configuration ─────────────────────────────────────────────────────

# JWT_SECRET_KEY is MANDATORY — fail fast if not set
_jwt_secret = os.environ.get("JWT_SECRET_KEY")
if _jwt_secret is None:
    raise EnvironmentError("JWT_SECRET_KEY must be set")

SECRET_KEY = _jwt_secret
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15  # Short TTL for security

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create a signed JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# ── Refresh Token Functions ───────────────────────────────────────────────────


def create_refresh_token(
    user_id: int,
    db: Session,
    policy: SessionPolicy | None = None,
    *,
    session_id: str | None = None,
    return_token_row: bool = False,
) -> str | tuple[str, RefreshToken]:
    """
    Create an opaque refresh token, store its SHA-256 hash in DB.

    By default, returns the raw opaque token.
    Set `return_token_row=True` to return a tuple of `(raw_token, refresh_token_row)`.
    """
    now = datetime.utcnow()
    policy = policy or get_standard_session_policy()
    raw_token = generate_opaque_token()
    token_hash = hash_token(raw_token)

    expires_at = now + timedelta(days=policy.refresh_token_days)
    rt = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        created_at=now,
        last_activity_at=now,
        session_id=session_id or generate_opaque_token(),
        policy_profile=policy.profile,
        stale_recovery_count=0,
    )
    db.add(rt)
    db.flush()
    db.commit()

    if return_token_row:
        return raw_token, rt

    return raw_token



def _now_utc() -> datetime:
    return datetime.utcnow()


def _is_token_idle_expired(rt: RefreshToken, now: datetime, policy: SessionPolicy) -> bool:
    if policy.idle_timeout_minutes is None:
        return False

    if rt.last_activity_at is None:
        return False

    return now - rt.last_activity_at > timedelta(minutes=policy.idle_timeout_minutes)


def _format_refresh_verification_result(
    result: RefreshVerificationResult,
    include_session_metadata: bool,
) -> RefreshVerificationResult | int | tuple[int, str | None] | None:
    """Preserve PR1 legacy return shape until router status handling lands."""
    if not include_session_metadata:
        return result

    if result.status != RefreshVerificationStatus.VALID or result.user_id is None:
        return None

    return result.user_id, result.session_id


def verify_refresh_token(
    token: str,
    db: Session,
    *,
    include_session_metadata: bool = False,
) -> RefreshVerificationResult | int | tuple[int, str | None] | None:
    """
    Verify a refresh token and return a structured status result.

    `include_session_metadata=True` preserves the PR1 legacy return shape for
    stacked compatibility until router status handling is applied in the next PR.
    """
    token_hash = hash_token(token)
    rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if rt is None:
        return _format_refresh_verification_result(
            RefreshVerificationResult(status=RefreshVerificationStatus.MISSING),
            include_session_metadata,
        )

    policy = get_session_policy_by_profile(rt.policy_profile)

    if rt.expires_at is not None and rt.expires_at < _now_utc():
        return _format_refresh_verification_result(
            RefreshVerificationResult(
                status=RefreshVerificationStatus.EXPIRED,
                user_id=rt.user_id,
                session_id=rt.session_id,
                policy_profile=rt.policy_profile,
                token_id=rt.id,
            ),
            include_session_metadata,
        )

    if _is_token_idle_expired(rt, _now_utc(), policy):
        return _format_refresh_verification_result(
            RefreshVerificationResult(
                status=RefreshVerificationStatus.IDLE_EXPIRED,
                user_id=rt.user_id,
                session_id=rt.session_id,
                policy_profile=rt.policy_profile,
                token_id=rt.id,
            ),
            include_session_metadata,
        )

    if rt.revoked_at is not None:
        # Distinguish stale rotation overlap from terminal revocation.
        if rt.revoked_reason == "rotated":
            grace_seconds = policy.stale_rotation_grace_seconds
            if rt.rotated_at is None or (_now_utc() - rt.rotated_at).total_seconds() > grace_seconds:
                return _format_refresh_verification_result(
                    RefreshVerificationResult(
                        status=RefreshVerificationStatus.ROTATED_STALE_REJECTED,
                        user_id=rt.user_id,
                        session_id=rt.session_id,
                        policy_profile=rt.policy_profile,
                        token_id=rt.id,
                    ),
                    include_session_metadata,
                )

            max_recoveries = policy.stale_rotation_max_recoveries
            if rt.stale_recovery_count >= max_recoveries:
                return _format_refresh_verification_result(
                    RefreshVerificationResult(
                        status=RefreshVerificationStatus.ROTATED_STALE_REJECTED,
                        user_id=rt.user_id,
                        session_id=rt.session_id,
                        policy_profile=rt.policy_profile,
                        token_id=rt.id,
                    ),
                    include_session_metadata,
                )

            return _format_refresh_verification_result(
                RefreshVerificationResult(
                    status=RefreshVerificationStatus.ROTATED_STALE_RECOVERABLE,
                    user_id=rt.user_id,
                    session_id=rt.session_id,
                    policy_profile=rt.policy_profile,
                    token_id=rt.id,
                    should_count_rate_limit=False,
                ),
                include_session_metadata,
            )

        return _format_refresh_verification_result(
            RefreshVerificationResult(
                status=RefreshVerificationStatus.REVOKED,
                user_id=rt.user_id,
                session_id=rt.session_id,
                policy_profile=rt.policy_profile,
                token_id=rt.id,
            ),
            include_session_metadata,
        )

    return _format_refresh_verification_result(
        RefreshVerificationResult(
            status=RefreshVerificationStatus.VALID,
            user_id=rt.user_id,
            session_id=rt.session_id,
            policy_profile=rt.policy_profile,
            token_id=rt.id,
            should_count_rate_limit=False,
        ),
        include_session_metadata,
    )


def increment_refresh_recovery_count(db: Session, token_id: int) -> None:
    """Backward-compatible stale recovery increment helper."""
    try_increment_refresh_recovery_count(db, token_id, max_recoveries=10**9)


def try_increment_refresh_recovery_count(
    db: Session,
    token_id: int,
    max_recoveries: int,
) -> bool:
    """Atomically reserve one stale-recovery attempt for a refresh token row."""
    updated = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.id == token_id,
            RefreshToken.stale_recovery_count < max_recoveries,
        )
        .update(
            {RefreshToken.stale_recovery_count: RefreshToken.stale_recovery_count + 1},
            synchronize_session=False,
        )
    )
    db.commit()
    return updated == 1


def rotate_refresh_token(
    db: Session,
    old_refresh_token: str | None,
    new_refresh_token_id: int,
) -> None:
    """Mark an old refresh token as rotated and link replacement id."""
    if old_refresh_token is None:
        return

    token_hash = hash_token(old_refresh_token)
    old_rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if old_rt is None:
        return

    now = _now_utc()
    old_rt.revoked_at = now
    old_rt.revoked_reason = "rotated"
    old_rt.rotated_at = now
    old_rt.replaced_by_token_id = new_refresh_token_id
    old_rt.stale_recovery_count = old_rt.stale_recovery_count or 0
    db.commit()


def revoke_refresh_token(token: str, db: Session, reason: str = "revoked") -> bool:
    """
    Revoke a refresh token by setting revoked_at.
    Returns True if token was revoked, False if not found.
    """
    token_hash = hash_token(token)
    rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if rt is None:
        return False

    rt.revoked_at = datetime.utcnow()
    rt.revoked_reason = reason
    db.commit()
    return True


def revoke_all_user_refresh_tokens(user_id: int, db: Session) -> int:
    """
    Revoke all refresh tokens for a user.
    Returns count of revoked tokens.
    """
    rts = db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked_at.is_(None)
    ).all()

    now = datetime.utcnow()
    count = 0
    for rt in rts:
        rt.revoked_at = now
        rt.revoked_reason = "logout"
        count += 1

    db.commit()
    return count


# ── User Auth ────────────────────────────────────────────────────────────────


async def get_current_user(
    request: Request, db: Session = Depends(get_pg_db)
):
    # Try Authorization header first (standard Bearer token)
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        # Fallback: read access_token from HttpOnly cookie
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception

    # Fetch from Postgres
    user = user_repo.get_user_by_username(db, username=token_data.username)
    if user is None:
        raise credentials_exception

    # Map to Pydantic User
    return UserInDB(
        username=user.username,
        hashed_password=user.hashed_password,
        password=user.hashed_password,  # Compat compatibility
        role=user.role,
        permissions=user.permissions,
        allowed_locations=user.allowed_locations,
        allowed_ci_types=user.allowed_ci_types,
        phone=user.phone,
        email=user.email,
        disabled=not user.is_active,
        force_password_change=user.force_password_change,
        tier=user.tier or "T1",
    )


async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def check_permission(permission: UserPermission, user: User):
    # Admins have all permissions
    if user.role == UserRole.ADMIN.value or user.role == "ADMIN":
        return True
    if permission.value in user.permissions:
        return True
    return False


# ── AI Agent Detection ─────────────────────────────────────────────────────────

AI_PERSONAS = {"AI_DIAGNOSTIC", "AI_OPERATOR", "AI_ADMIN"}
ALLOWED_AI_PERMISSIONS = {permission.value for permission in AIPermission}


class AIAgentInfo(BaseModel):
    """Info extracted from AI agent JWT."""

    ai_agent_id: str
    persona: str
    permissions: list[str] = []


async def get_current_ai_agent(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_pg_db)
) -> AIAgentInfo:
    """FastAPI dependency that extracts AI agent info from JWT.

    The function enforces a strict allow-list for `permissions`:
    - missing claim => empty list
    - claim must be a list when provided
    - each item must be a non-empty string in `AIPermission`

    Fail-closed behavior:
    - unknown/invalid/human permissions and malformed claims return HTTP 403
    - token decode/subject failures return HTTP 401
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate AI agent credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        token_type = payload.get("type")
        if token_type != "ai_agent":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not an AI agent token",
            )
        ai_agent_id = payload.get("sub")
        if ai_agent_id is None:
            raise credentials_exception
        persona = payload.get("role")
        if persona not in AI_PERSONAS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Invalid AI persona: {persona}",
            )
        permissions = _normalize_ai_agent_permissions(payload)
        return AIAgentInfo(
            ai_agent_id=ai_agent_id,
            persona=persona,
            permissions=permissions,
        )
    except JWTError:
        raise credentials_exception


def _normalize_ai_agent_permissions(payload: dict) -> list[str]:
    """Normalize and validate AI-agent `permissions` claim values.

    Returns:
        list[str]: A validated permission list.

    Raises:
        HTTPException(403): For non-list payloads, non-string items, or values
            not present in the `AIPermission` enum.
    """
    if "permissions" not in payload:
        return []

    raw_permissions = payload.get("permissions")
    if not isinstance(raw_permissions, list):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI permissions claim must be a list when provided",
        )

    for permission in raw_permissions:
        if not isinstance(permission, str) or not permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="AI permissions claim must contain non-empty string values",
            )
        if permission not in ALLOWED_AI_PERMISSIONS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Invalid AI permission: {permission}",
            )

    return raw_permissions