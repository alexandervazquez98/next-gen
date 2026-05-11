# backend/models/prune_lock.py
"""Distributed lock for prune operations — prevents concurrent SSE streams."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from postgres_db import Base


class PruneLock(Base):
    """
    Distributed lock that ensures only ONE prune operation can run at a time
    across ALL operators. Uses PostgreSQL for ACID guarantees.
    """

    __tablename__ = "prune_lock"

    id = Column(Integer, primary_key=True, index=True)
    # Single lock key — we only need one global prune lock
    lock_key = Column(String, default="prune", nullable=False, unique=True)
    # Username of the operator who acquired the lock
    owner = Column(String, nullable=False)
    # When the lock was acquired
    acquired_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # When the lock expires (auto-release if operator disconnects)
    expires_at = Column(DateTime, nullable=False)