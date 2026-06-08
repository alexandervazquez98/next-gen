"""Pydantic DTOs for audit event API responses."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEventResponse(BaseModel):
    id: int
    schema_version: int
    event_type: str
    outcome: str
    actor_username: str | None = None
    actor_role: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    target_label: str | None = None
    source: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    reason: str | None = None
    context: dict[str, Any] | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditEventListResponse(BaseModel):
    items: list[AuditEventResponse]
    total: int
    page: int
    page_size: int
