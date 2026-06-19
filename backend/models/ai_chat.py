from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text

from postgres_db import Base


class AIChatMessage(Base):
    """Persist one bounded AI chat exchange and optional harness metadata."""

    __tablename__ = "ai_chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, index=True, nullable=False)
    user_message = Column(Text, nullable=False)
    assistant_response = Column(Text, nullable=False)
    context = Column(Text, nullable=True)
    harness_result = Column(JSON, nullable=True)
    model = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
