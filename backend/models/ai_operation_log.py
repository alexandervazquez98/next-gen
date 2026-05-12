from sqlalchemy import Column, Integer, String, DateTime, Boolean, JSON, Index
from sqlalchemy.sql import func
from postgres_db import Base


class AIOperationLog(Base):
    __tablename__ = "ai_operation_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    ai_persona = Column(String(50), nullable=False)  # "AI_DIAGNOSTIC", "AI_OPERATOR"
    ai_agent_id = Column(String(100), nullable=False)  # JWT subject
    operation = Column(String(50), nullable=False)  # "diagnose", "ack", "close", "ci_update"
    target_type = Column(String(20), nullable=False)  # "event", "ci", "metric"
    target_id = Column(String(100), nullable=False)
    target_name = Column(String(255), nullable=True)  # Human-readable name
    result = Column(String(20), nullable=False)  # "success", "blocked", "failed", "escalated"
    blocked_reason = Column(String(255), nullable=True)
    escalation_triggered = Column(Boolean, default=False)
    request_context = Column(JSON, nullable=True)  # IP, user agent, etc.
    prior_operation = Column(String(50), nullable=True)
    prior_target = Column(String(100), nullable=True)
    time_since_prior_seconds = Column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_ai_op_log_agent_timestamp", "ai_agent_id", "timestamp"),
        Index("ix_ai_op_log_target", "target_type", "target_id"),
        Index("ix_ai_op_log_operation_timestamp", "operation", "timestamp"),
    )