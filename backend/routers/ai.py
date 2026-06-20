from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from config import get_lm_studio_settings
from database import get_db
from postgres_db import get_pg_db
from models.user import AIPermission, User, UserPermission
from services.auth_service import check_permission, get_current_active_user
from services.ai_chat_service import (
    LMStudioError,
    LMStudioTimeoutError,
    complete_chat,
    maybe_run_harness,
    save_chat_exchange,
)


router = APIRouter(prefix="/ai", tags=["AI Chat"])


class AvailabilityIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["availability_check"]
    ci_ref: str = Field(min_length=1, max_length=120)


class AIChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2_000)
    context: str | None = Field(default=None, max_length=4_000)
    intent: AvailabilityIntent | None = None


class AIChatResponse(BaseModel):
    answer: str
    model: str | None = None
    message_id: int | None = None
    harness_result: dict[str, Any] | None = None


def _can_run_availability_harness(user: User) -> bool:
    can_run_diagnostics = check_permission(UserPermission.RUN_DIAGNOSTICS, user) or (
        AIPermission.AI_RUN_DIAGNOSTIC.value in user.permissions
    )
    can_view_all_cmdb = AIPermission.AI_VIEW_ALL.value in user.permissions
    return can_run_diagnostics and can_view_all_cmdb


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

    if body.intent is not None and not _can_run_availability_harness(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to run diagnostics")

    harness_result = await asyncio.to_thread(maybe_run_harness, body.intent, neo4j_driver)
    try:
        completion = await asyncio.to_thread(
            complete_chat, body.query, body.context, harness_result,
        )
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

    row = await asyncio.to_thread(
        save_chat_exchange,
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
