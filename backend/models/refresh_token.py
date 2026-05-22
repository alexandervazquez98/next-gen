import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional

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
    refresh_token: str  # the opaque token (not hash)
    token_type: str = "bearer"


class RefreshTokenVerifyResult(BaseModel):
    """Result of verify_refresh_token."""
    user_id: int


def hash_token(token: str) -> str:
    """SHA-256 hash of an opaque token."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_opaque_token() -> str:
    """Generate a 256-bit random opaque token."""
    return secrets.token_urlsafe(32)


REFRESH_TOKEN_EXPIRE_DAYS = 7