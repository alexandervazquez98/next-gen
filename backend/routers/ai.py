from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from config import get_lm_studio_settings
from database import get_db
from postgres_db import get_pg_db
from models.user import AIPermission, User, UserPermission
from services.auth_service import check_permission, get_current_active_user
from services.ai_chat_service import (
    LMStudioError,
    LMStudioTimeoutError,
    complete_chat,
    latest_event_list_ci_refs,
    load_chat_history,
    maybe_run_harness,
    save_chat_exchange,
)


router = APIRouter(prefix="/ai", tags=["AI Chat"])


class AvailabilityIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["availability_check"]
    ci_ref: str = Field(min_length=1, max_length=120)


class EventListIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["event_list", "active_events"]
    status: Literal["OPEN", "ACK", "CLOSED", "RECOVERED", "ACTIVE", "CONSOLE"] = "ACTIVE"
    severity: Literal["CRITICAL", "WARNING", "INFO"] | None = None
    limit: int = Field(default=10, ge=1, le=25)


class AvailabilityBatchIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["availability_check_batch"]
    ci_refs: list[str] = Field(min_length=1, max_length=5)

    @field_validator("ci_refs")
    @classmethod
    def validate_ci_refs(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("At least one CI reference is required")
        if any(len(item) > 120 for item in cleaned):
            raise ValueError("CI references must be 120 characters or fewer")
        return cleaned


AIChatIntent = AvailabilityIntent | AvailabilityBatchIntent | EventListIntent


class AIChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2_000)
    context: str | None = Field(default=None, max_length=4_000)
    intent: AIChatIntent | None = None


class AIChatResponse(BaseModel):
    answer: str
    model: str | None = None
    message_id: int | None = None
    harness_result: dict[str, Any] | None = None


def _has_ai_view_all(user: User) -> bool:
    return user.role == "ADMIN" or (AIPermission.AI_VIEW_ALL.value in user.permissions)


def _can_run_availability_harness(user: User) -> bool:
    can_run_diagnostics = check_permission(UserPermission.RUN_DIAGNOSTICS, user) or (
        AIPermission.AI_RUN_DIAGNOSTIC.value in user.permissions
    )
    return can_run_diagnostics and _has_ai_view_all(user)


def _can_run_event_list_harness(user: User) -> bool:
    return check_permission(UserPermission.EVENT_VIEW, user) or (
        AIPermission.AI_VIEW_ALL.value in user.permissions
    )


def _can_run_intent_harness(intent: AIChatIntent, user: User) -> bool:
    if intent.type in {"availability_check", "availability_check_batch"}:
        return _can_run_availability_harness(user)
    if intent.type in {"event_list", "active_events"}:
        return _can_run_event_list_harness(user)
    return False


def infer_chat_intent(query: str) -> AIChatIntent | None:
    """Infer simple provider-neutral intents for clients without tool planning."""
    normalized = query.lower()
    asks_for_events = re.search(r"\b(events?|eventos?|alertas?|incidentes?)\b", normalized)
    asks_for_recovery = re.search(r"\b(recuperad[oa]s?|recovered|recovery)\b", normalized)
    asks_for_unrecovered = asks_for_recovery and re.search(
        r"\b(no|not|sin|unrecovered|unresolved)\b",
        normalized,
    )
    asks_to_list = re.search(
        r"\b(list|listar|lista|mostrar|muestra|ver|ves|detalle|detalla|activos?|abiertos?|actuales?)\b",
        normalized,
    )

    if not asks_for_events or not (asks_to_list or asks_for_recovery):
        return None

    severity = None
    if re.search(r"\b(criticos?|críticos?|critical|criticals?)\b", normalized):
        severity = "CRITICAL"
    elif re.search(r"\b(warnings?|advertencias?)\b", normalized):
        severity = "WARNING"
    elif re.search(r"\b(info|informativos?)\b", normalized):
        severity = "INFO"

    if asks_for_unrecovered:
        return EventListIntent(type="event_list", status="ACTIVE", severity=severity, limit=10)
    if asks_for_recovery:
        return EventListIntent(type="event_list", status="RECOVERED", severity=severity, limit=10)
    if re.search(r"\b(abiertos?|open)\b", normalized):
        status = "OPEN"
    else:
        status = "CONSOLE" if re.search(r"\b(console|consola)\b", normalized) else "ACTIVE"
    return EventListIntent(type="event_list", status=status, severity=severity, limit=10)


def infer_followup_intent(query: str, db, username: str) -> AIChatIntent | None:
    """Infer follow-up diagnostics from recent harness context."""
    normalized = query.lower()
    asks_availability = re.search(
        r"\b(verifica|verificar|checa|chequeo|revisa|revisar|estatus|estado|siguen|disponibilidad|funcionando|responden|reachable|working|availability)\b",
        normalized,
    )
    if not asks_availability:
        return None
    ci_refs = latest_event_list_ci_refs(db, username, query=query)
    if not ci_refs:
        return None
    return AvailabilityBatchIntent(type="availability_check_batch", ci_refs=ci_refs)


@router.post("/chat", response_model=AIChatResponse)
async def chat_with_ai(
    body: AIChatRequest,
    current_user: User = Depends(get_current_active_user),
    db=Depends(get_pg_db),
    neo4j_driver=Depends(get_db),
) -> AIChatResponse:
    if not get_lm_studio_settings().enabled:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LM Studio is unavailable",
        )

    intent = body.intent or infer_chat_intent(body.query) or infer_followup_intent(
        body.query,
        db,
        current_user.username,
    )
    if intent is not None and not _can_run_intent_harness(intent, current_user):
        detail = (
            "Not authorized to run diagnostics"
            if intent.type in {"availability_check", "availability_check_batch"}
            else "Not authorized to view events"
        )
        raise HTTPException(status_code=403, detail=detail)

    harness_result = maybe_run_harness(intent, neo4j_driver)
    history = load_chat_history(db, current_user.username)
    try:
        completion = complete_chat(body.query, body.context, harness_result, history)
    except LMStudioTimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="LM Studio request timed out",
        )
    except LMStudioError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LM Studio is unavailable",
        )

    row = save_chat_exchange(
        db,
        username=current_user.username,
        user_message=body.query,
        assistant_response=completion["content"],
        context=body.context,
        harness_result=harness_result,
        model=completion.get("model"),
    )
    return AIChatResponse(
        answer=completion["content"],
        model=completion.get("model"),
        message_id=getattr(row, "id", None),
        harness_result=harness_result,
    )
