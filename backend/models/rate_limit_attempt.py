"""Persistent auth rate-limit state."""
from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, Index, Integer, String, Text, UniqueConstraint

from postgres_db import Base


class RateLimitAttempt(Base):
    """SQLAlchemy model for shared auth rate-limit counters."""

    __tablename__ = "rate_limit_attempts"

    id = Column(Integer, primary_key=True, index=True)
    identity_key = Column(Text, nullable=False)
    identity_type = Column(String(32), nullable=False, default="username")
    attempt_count = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)
    last_failed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("identity_type", "identity_key", name="uq_rate_limit_identity"),
        CheckConstraint("attempt_count >= 0", name="ck_rate_limit_attempt_count_nonnegative"),
        Index("ix_rate_limit_identity", "identity_type", "identity_key"),
        Index("ix_rate_limit_cleanup", "locked_until", "updated_at"),
    )
