"""SQLAlchemy model for dedicated user audit events."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, JSON, String

from postgres_db import Base


class AuditEvent(Base):
    """Stores versioned audit events for auth, access, and critical changes."""

    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, index=True)
    schema_version = Column(Integer, default=1, nullable=False)
    event_type = Column(String(64), nullable=False, index=True)
    outcome = Column(String(32), nullable=False, index=True)

    actor_username = Column(String(128), nullable=True, index=True)
    actor_role = Column(String(64), nullable=True)

    target_type = Column(String(64), nullable=True, index=True)
    target_id = Column(String(256), nullable=True, index=True)
    target_label = Column(String(256), nullable=True)

    source = Column(String(64), nullable=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(256), nullable=True)
    reason = Column(String(128), nullable=True)
    context = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("ix_audit_events_created_event_type", "created_at", "event_type"),
        Index("ix_audit_events_created_outcome", "created_at", "outcome"),
        Index("ix_audit_events_created_actor", "created_at", "actor_username"),
        Index("ix_audit_events_target_lookup", "target_type", "target_id", "created_at"),
    )
