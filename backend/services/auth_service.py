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
from typing import Optional, Dict, Any
from postgres_db import get_pg_db
from repositories import user_repo
from utils.security import verify_password, get_password_hash
from models.refresh_token import RefreshToken, hash_token, generate_opaque_token, REFRESH_TOKEN_EXPIRE_DAYS

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

def create_refresh_token(user_id: int, db: Session) -> str:
    """
    Create an opaque refresh token, store its SHA-256 hash in DB.
    Returns the raw opaque token (to be sent to client).
    """
    opaque = generate_opaque_token()
    token_hash = hash_token(opaque)
    expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    rt = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(rt)
    db.commit()
    return opaque


def verify_refresh_token(token: str, db: Session) -> Optional[int]:
    """
    Verify a refresh token.
    Returns user_id if valid and not revoked/expired.
    Returns None if invalid, revoked, or expired.
    """
    token_hash = hash_token(token)
    rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if rt is None:
        return None

    if rt.revoked_at is not None:
        return None

    if rt.expires_at < datetime.utcnow():
        return None

    return rt.user_id


def revoke_refresh_token(token: str, db: Session) -> bool:
    """
    Revoke a refresh token by setting revoked_at.
    Returns True if token was revoked, False if not found.
    """
    token_hash = hash_token(token)
    rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if rt is None:
        return False

    rt.revoked_at = datetime.utcnow()
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
