"""AI Guard Models — GuardResult and related types."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class GuardResult(BaseModel):
    """Result of a guard check.

    Attributes:
        allowed: Whether the operation is permitted.
        reason: Human-readable explanation (present when not allowed or flag raised).
        cooldown_remaining_seconds: Seconds until cooldown expires (if in cooldown).
        escalation_required: Whether human approval is needed before proceeding.
        escalation_id: ID of the escalation ticket (if escalation_required=True).
    """

    allowed: bool
    reason: Optional[str] = None
    cooldown_remaining_seconds: Optional[int] = None
    escalation_required: bool = False
    escalation_id: Optional[str] = None