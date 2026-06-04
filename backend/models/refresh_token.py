import secrets
import hashlib
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from pydantic import BaseModel

from postgres_db import Base


class RefreshToken(Base):
    """SQLAlchemy model for refresh tokens stored as SHA-256 hashes."""
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Policy-backed session metadata
    session_id = Column(String, index=True, nullable=False)
    policy_profile = Column(String, default="standard", nullable=False)
    last_activity_at = Column(DateTime, nullable=False)

    # Rotation / audit metadata
    rotated_at = Column(DateTime, nullable=True)
    replaced_by_token_id = Column(Integer, ForeignKey("refresh_tokens.id"), nullable=True)
    revoked_reason = Column(String, nullable=True)
    stale_recovery_count = Column(Integer, default=0, nullable=False)

    # Retention controls
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="refresh_tokens")


# ── Pydantic Schemas ─────────────────────────────────────────────────────────


class RefreshTokenCreate(BaseModel):
    """Schema for creating a refresh token (internal use)."""

    user_id: int


class RefreshTokenResponse(BaseModel):
    """Response schema for token refresh endpoint."""

    access_token: str
    token_type: str = "bearer"


class RefreshVerificationStatus(str, Enum):
    """Refresh verification terminal/recoverable status codes."""

    VALID = "valid"
    MISSING = "missing"
    EXPIRED = "expired"
    IDLE_EXPIRED = "idle_expired"
    REVOKED = "revoked"
    ROTATED_STALE_REJECTED = "rotated_stale_rejected"
    ROTATED_STALE_RECOVERABLE = "rotated_stale_recoverable"
    USER_INACTIVE = "user_inactive"


class RefreshVerificationResult(BaseModel):
    """Result of verify_refresh_token."""

    status: RefreshVerificationStatus
    user_id: int | None = None
    session_id: str | None = None
    policy_profile: str | None = None
    token_id: int | None = None
    should_count_rate_limit: bool = True


def hash_token(token: str) -> str:
    """SHA-256 hash of an opaque token."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_opaque_token() -> str:
    """Generate a 256-bit random opaque token."""
    return secrets.token_urlsafe(32)


REFRESH_TOKEN_EXPIRE_DAYS = 7