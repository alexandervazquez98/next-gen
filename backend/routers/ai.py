from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Literal

from config import get_lm_studio_settings
from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Request, status
from models.user import AIPermission, User, UserPermission
from postgres_db import get_pg_db
from pydantic import BaseModel, ConfigDict, Field, field_validator
from services import ai_chat_service, cmdb_proposal_service
from services.ai_chat_service import (
    LMStudioError,
    LMStudioRequestRejected,
    LMStudioTimeoutError,
    build_guard_denial_harness_result,
    complete_chat,
    latest_event_list_ci_refs,
    load_chat_history,
    maybe_run_harness,
    save_chat_exchange,
)
from services.ai_guard_service import check_all_guards, record_operation
from services.auth_service import check_permission, get_current_active_user

CurrentUserDep = Depends(get_current_active_user)
PgDbDep = Depends(get_pg_db)
Neo4jDriverDep = Depends(get_db)

logger = logging.getLogger(__name__)


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


class ProposeCIIntent(BaseModel):
    """feat-489: chat-side HITL entry point. Agent (or explicit client
    intent) submits a CMDB proposal manifest; backend validates via
    ``ManifestPayload.model_validate`` and persists as DRAFT.

    The manifest shape is intentionally a free-form dict here so the LLM
    can produce it; the strict Pydantic shape is enforced at the service
    boundary in ``cmdb_proposal_service.create_proposal``.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["propose_ci"]
    manifest: dict[str, Any]
    rationale: str = Field(default="", max_length=1024)
    source_refs: list[str] = Field(default_factory=list, max_length=16)


AIChatIntent = (
    AvailabilityIntent | AvailabilityBatchIntent | EventListIntent | ProposeCIIntent
)


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


def _can_run_propose_ci_harness(user: User) -> bool:
    # feat-489: AI_PROPOSE_CI is the chat-side gate for HITL CI proposals.
    # ADMIN bypasses the per-permission check via auth_service.check_permission.
    return user.role == "ADMIN" or (
        AIPermission.AI_PROPOSE_CI.value in user.permissions
    )


def _can_run_intent_harness(intent: AIChatIntent, user: User) -> bool:
    if intent.type in {"availability_check", "availability_check_batch"}:
        return _can_run_availability_harness(user)
    if intent.type in {"event_list", "active_events"}:
        return _can_run_event_list_harness(user)
    if intent.type == "propose_ci":
        return _can_run_propose_ci_harness(user)
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
        r"\b(list\w*|listar|lista|mostrar|muestra|ver|ves|detalle|detalla|"
        r"activos?|abiertos?|actuales?|"
        r"tengo(s)?|tenemos|"
        r"cu[aá]les?)",
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
        r"\b("
        r"verific\w*|verifiqu\w*|chequ\w*|chec\w*|"
        r"revis\w*|revisi\w*|revisa\w*|"
        r"monitor\w*|monitore\w*|"
        r"comprueb\w*|comprob\w*|consult\w*|"
        r"estatus|estado|siguen|sigue|funcionando|responden|"
        r"reachable|working|availability|disponibilidad"
        r")\b",
        normalized,
    )
    confirms_prior_action = re.search(
        r"^\s*(ok|okay|si|sí|dale|hazlo|usalo|úsalo|ejecutalo|ejecútalo|do it|use it)\b",
        normalized,
    )
    if not asks_availability and not confirms_prior_action:
        return None
    ci_refs = latest_event_list_ci_refs(db, username, query=query)
    if not ci_refs:
        return None
    return AvailabilityBatchIntent(type="availability_check_batch", ci_refs=ci_refs)


def _normalize_availability_ci_ref(ci_ref: str) -> str:
    return str(ci_ref).strip()


def _safe_get_ci_field(ci: Any, field: str) -> Any:
    if isinstance(ci, dict):
        return ci.get(field)
    getter = getattr(ci, "get", None)
    if callable(getter):
        try:
            return getter(field)
        except TypeError:
            return None
    return getattr(ci, field, None)


def _canonical_ci_target_id(ci: Any) -> str | None:
    ci_id = _safe_get_ci_field(ci, "id")
    if ci_id is None:
        return None
    canonical = str(ci_id)
    if not canonical.strip():
        return None
    return f"ci:{canonical}"


def _build_availability_not_found_result(ci_ref: str) -> dict[str, Any]:
    return {"type": "availability_check", "ci_ref": ci_ref, "status": "ci_not_found"}


def _resolve_ci_for_harness(neo4j_driver, ci_ref: str) -> dict[str, Any] | None:
    return ai_chat_service.resolve_ci_for_harness(neo4j_driver, ci_ref)


def _event_query_target_id(intent: EventListIntent) -> str:
    status = str(getattr(intent, "status", "ACTIVE") or "ACTIVE").upper()
    severity = str(getattr(intent, "severity", "any") or "any").lower()
    return f"event_query:{status}:{severity}"


def _build_guard_request_context(intent: AIChatIntent) -> dict[str, Any]:
    context = {
        "source": "ai_chat",
        "intent_type": intent.type,
    }
    if isinstance(intent, AvailabilityIntent):
        context["ci_ref"] = intent.ci_ref
        context["ci_refs_count"] = 1
    elif isinstance(intent, AvailabilityBatchIntent):
        context["ci_refs_count"] = len(intent.ci_refs)
    elif isinstance(intent, ProposeCIIntent):
        # feat-489: include manifest summary in guard context so the audit
        # row carries the proposed ci_id and category without storing the
        # full manifest (which the audit walker already redacts).
        ci_block = intent.manifest.get("ci") if isinstance(intent.manifest, dict) else None
        if isinstance(ci_block, dict):
            context["proposed_ci_id"] = ci_block.get("id")
            context["proposed_category"] = ci_block.get("type") or ci_block.get("category")
        context["source_refs_count"] = len(intent.source_refs)
    else:
        context["status"] = intent.status
        context["severity"] = intent.severity
        context["limit"] = intent.limit
    return context


def _evaluate_chat_guard(
    *,
    user: User,
    target_type: str,
    target_ids: list[str],
    reason_context: dict[str, Any],
    intent_type: str,
) -> dict[str, Any] | None:
    try:
        guard_result = check_all_guards(user.username, "diagnose", target_ids)
    except Exception:
        return build_guard_denial_harness_result(
            intent_type=intent_type,
            target_type=target_type,
            target_ids=target_ids,
            reason="AI guardrail system could not verify this request was safe.",
            reason_code="guard_unavailable",
            request_context=reason_context,
        )

    if guard_result.escalation_required:
        return build_guard_denial_harness_result(
            intent_type=intent_type,
            target_type=target_type,
            target_ids=target_ids,
            reason=guard_result.reason,
            escalation_required=True,
            escalation_id=guard_result.escalation_id,
            request_context=reason_context,
        )

    if not guard_result.allowed:
        return build_guard_denial_harness_result(
            intent_type=intent_type,
            target_type=target_type,
            target_ids=target_ids,
            reason=guard_result.reason,
            cooldown_remaining_seconds=guard_result.cooldown_remaining_seconds,
            request_context=reason_context,
        )
    return None


def _record_chat_operation(
    *,
    user: User,
    intent: AIChatIntent,
    target_type: str,
    target_id: str,
    target_name: str,
    result: str,
    blocked_reason: str | None = None,
) -> None:
    request_context = _build_guard_request_context(intent)
    request_context["event_category"] = "chat_harness"
    try:
        record_operation(
            ai_persona=str(user.role),
            ai_agent_id=user.username,
            operation="diagnose",
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            result=result,
            blocked_reason=blocked_reason,
            request_context=request_context,
        )
    except Exception:
        return


@router.post("/chat", response_model=AIChatResponse)
async def chat_with_ai(
    body: AIChatRequest,
    request: Request,
    current_user: User = CurrentUserDep,
    db=PgDbDep,
    neo4j_driver=Neo4jDriverDep,
) -> AIChatResponse:
    if not get_lm_studio_settings().enabled:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LM Studio is unavailable",
        )

    intent = body.intent or infer_chat_intent(body.query)
    if intent is None:
        intent = await asyncio.to_thread(
            infer_followup_intent,
            body.query,
            db,
            current_user.username,
        )
    if intent is not None and not _can_run_intent_harness(intent, current_user):
        if intent.type in {"availability_check", "availability_check_batch"}:
            detail = "Not authorized to run diagnostics"
        elif intent.type in {"event_list", "active_events"}:
            detail = "Not authorized to view events"
        elif intent.type == "propose_ci":
            detail = "missing_permission: AI_PROPOSE_CI required to propose a CI"
        else:  # pragma: no cover — defensive, all branches covered above
            detail = "Not authorized to run this harness"
        raise HTTPException(status_code=403, detail=detail)

    harness_result: dict[str, Any] | None = None

    try:
        if intent is None:
            pass
        elif intent.type == "availability_check":
            ci_ref = _normalize_availability_ci_ref(intent.ci_ref)
            ci = _resolve_ci_for_harness(neo4j_driver, ci_ref)
            if ci is None:
                harness_result = _build_availability_not_found_result(ci_ref)
            else:
                target_id = _canonical_ci_target_id(ci)
                if target_id is None:
                    harness_result = _build_availability_not_found_result(ci_ref)
                else:
                    target_name = str(_safe_get_ci_field(ci, "name") or ci_ref)
                    guard_context = _build_guard_request_context(intent)
                    denial = _evaluate_chat_guard(
                        user=current_user,
                        target_type="ci",
                        target_ids=[target_id],
                        reason_context=guard_context,
                        intent_type="availability_check",
                    )
                    if denial is not None:
                        _record_chat_operation(
                            user=current_user,
                            intent=intent,
                            target_type="ci",
                            target_id=target_id,
                            target_name=target_name,
                            result=(
                                "blocked"
                                if denial.get("reason_code") != "escalation_required"
                                else "escalated"
                            ),
                            blocked_reason=denial.get("reason_code"),
                        )
                        harness_result = denial
                    else:
                        run_intent = type(
                            "ResolvedAvailabilityIntent",
                            (),
                            {"type": "availability_check", "ci_ref": ci_ref, "_resolved_ci": ci},
                        )()
                        harness_result = await asyncio.to_thread(
                            maybe_run_harness,
                            run_intent,
                            neo4j_driver,
                            current_user,
                        )
                        _record_chat_operation(
                            user=current_user,
                            intent=intent,
                            target_type="ci",
                            target_id=target_id,
                            target_name=target_name,
                            result="success",
                        )
        elif intent.type in {"event_list", "active_events"}:
            target_id = _event_query_target_id(intent)
            target_name = f"event query {target_id}"
            guard_context = _build_guard_request_context(intent)
            denial = _evaluate_chat_guard(
                user=current_user,
                target_type="event_query",
                target_ids=[target_id],
                reason_context=guard_context,
                intent_type="event_list",
            )
            if denial is not None:
                _record_chat_operation(
                    user=current_user,
                    intent=intent,
                    target_type="event_query",
                    target_id=target_id,
                    target_name=target_name,
                    result=(
                        "blocked"
                        if denial.get("reason_code") != "escalation_required"
                        else "escalated"
                    ),
                    blocked_reason=denial.get("reason_code"),
                )
                harness_result = denial
            else:
                harness_result = await asyncio.to_thread(
                    maybe_run_harness,
                    intent,
                    neo4j_driver,
                    current_user,
                )
        elif intent.type == "availability_check_batch":
            target_names: dict[str, str] = {}
            resolved_targets: list[str] = []
            resolved_by_ref: dict[str, Any | None] = {}
            normalized_refs: list[str] = []
            non_executable_ci_refs: list[str] = []
            for ci_ref in intent.ci_refs:
                ref = _normalize_availability_ci_ref(ci_ref)
                normalized_refs.append(ref)
                ci = _resolve_ci_for_harness(neo4j_driver, ref)
                if ci is None:
                    resolved_by_ref[ref] = None
                    continue

                canonical_id = _canonical_ci_target_id(ci)
                if canonical_id is None:
                    non_executable_ci_refs.append(ref)
                    continue

                resolved_by_ref[ref] = ci
                resolved_targets.append(canonical_id)
                target_names[canonical_id] = str(_safe_get_ci_field(ci, "name") or ref)

            guard_context = _build_guard_request_context(intent)
            if non_executable_ci_refs:
                denial = build_guard_denial_harness_result(
                    intent_type="availability_check_batch",
                    target_type="ci",
                    target_ids=resolved_targets,
                    reason="Could not verify one or more availability targets for guard-safe execution.",
                    reason_code="guard_unavailable",
                    request_context=guard_context,
                )
                block_target_id = resolved_targets[0] if resolved_targets else ""
                block_target_name = target_names.get(
                    block_target_id, "unresolved availability target"
                )
                _record_chat_operation(
                    user=current_user,
                    intent=intent,
                    target_type="ci",
                    target_id=block_target_id,
                    target_name=block_target_name,
                    result="blocked",
                    blocked_reason=denial.get("reason_code"),
                )
                harness_result = denial
            else:
                if not resolved_targets:
                    run_intent = type(
                        "ResolvedAvailabilityBatchIntent",
                        (),
                        {
                            "type": "availability_check_batch",
                            "ci_refs": normalized_refs,
                            "_resolved_ci_targets": resolved_by_ref,
                        },
                    )()
                    harness_result = await asyncio.to_thread(
                        maybe_run_harness, run_intent, neo4j_driver, current_user
                    )
                else:
                    denial = _evaluate_chat_guard(
                        user=current_user,
                        target_type="ci",
                        target_ids=resolved_targets,
                        reason_context=guard_context,
                        intent_type="availability_check_batch",
                    )
                    if denial is None:
                        for canonical_id in resolved_targets:
                            denial = _evaluate_chat_guard(
                                user=current_user,
                                target_type="ci",
                                target_ids=[canonical_id],
                                reason_context=guard_context,
                                intent_type="availability_check_batch",
                            )
                            if denial is not None:
                                break

                    if denial is not None:
                        denial_target_id = denial.get("target_ids", [])
                        record_target_id = (
                            denial_target_id[0]
                            if denial_target_id
                            else (resolved_targets[0] if resolved_targets else "")
                        )
                        _record_chat_operation(
                            user=current_user,
                            intent=intent,
                            target_type="ci",
                            target_id=record_target_id,
                            target_name=target_names.get(record_target_id, record_target_id),
                            result=(
                                "blocked"
                                if denial.get("reason_code") != "escalation_required"
                                else "escalated"
                            ),
                            blocked_reason=denial.get("reason_code"),
                        )
                        denial["target_ids"] = resolved_targets
                        harness_result = denial
                    else:
                        run_intent = type(
                            "ResolvedAvailabilityBatchIntent",
                            (),
                            {
                                "type": "availability_check_batch",
                                "ci_refs": normalized_refs,
                                "_resolved_ci_targets": resolved_by_ref,
                            },
                        )()
                        harness_result = await asyncio.to_thread(
                            maybe_run_harness, run_intent, neo4j_driver, current_user
                        )
                        for canonical_id in resolved_targets:
                            _record_chat_operation(
                                user=current_user,
                                intent=intent,
                                target_type="ci",
                                target_id=canonical_id,
                                target_name=target_names.get(canonical_id, canonical_id),
                                result="success",
                            )
        elif intent.type == "propose_ci":
            # feat-489: chat-side HITL proposal submission. The service does
            # the heavy lifting (manifest validation, guard gate, repo write,
            # audit, op-log). We translate its return shape into the
            # provider-neutral harness_result so the LLM completion can use
            # it as chat context.
            try:
                result = await asyncio.to_thread(
                    cmdb_proposal_service.create_proposal,
                    manifest=intent.manifest,
                    user=current_user,
                    ai_agent_id=current_user.username,
                    db=db,
                    request=request,
                )
            except HTTPException as exc:
                # Surface service-layer errors (422 invalid_manifest,
                # 409 ci_id_collision, 404, 403 missing_permission) as a
                # conversationally-stable harness_result instead of a 4xx,
                # so the chat agent can quote the reason verbatim to the
                # operator (cf. tools/cmdb_proposals.md error cheat-sheet).
                detail = exc.detail
                reason = (
                    detail.get("reason") if isinstance(detail, dict) else str(detail)
                )
                harness_result = {
                    "type": "propose_ci",
                    "status": "error",
                    "reason": reason or f"http_{exc.status_code}",
                    "errors": detail if isinstance(detail, dict) else {"detail": str(detail)},
                    "http_status": exc.status_code,
                }
            else:
                # create_proposal returns either {"harness_result": {denied: ...}}
                # (guardrail denial) or the created proposal row.
                if isinstance(result, dict) and "harness_result" in result:
                    harness_result = {
                        "type": "propose_ci",
                        **result["harness_result"],
                    }
                else:
                    harness_result = {
                        "type": "propose_ci",
                        "status": "DRAFT",
                        "proposal_id": result.get("id"),
                        "version": result.get("version", 1),
                        "ci_id": result.get("resulted_ci_id") or (
                            intent.manifest.get("ci", {}).get("id")
                            if isinstance(intent.manifest, dict)
                            else None
                        ),
                    }
        else:
            harness_result = await asyncio.to_thread(
                maybe_run_harness, intent, neo4j_driver, current_user
            )

        if harness_result is None:
            harness_result = await asyncio.to_thread(
                maybe_run_harness, intent, neo4j_driver, current_user
            )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operational harness is unavailable; no diagnostic or event result was executed.",
        ) from exc

    history = await asyncio.to_thread(load_chat_history, db, current_user.username)
    try:
        completion = await asyncio.to_thread(
            complete_chat,
            body.query,
            body.context,
            harness_result,
            history,
        )
    except LMStudioTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="LM Studio request timed out",
        ) from exc
    except LMStudioRequestRejected as exc:
        reason = exc.body_preview or exc.reason or "unknown"
        if exc.status >= 500:
            detail = f"LM Studio upstream error: {exc.status} {reason}"
        else:
            detail = f"LM Studio rejected the request: {reason}"
        logger.warning(
            "LM Studio rejected chat request: status=%s detail=%s",
            exc.status,
            detail,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        ) from exc
    except LMStudioError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LM Studio is unavailable",
        ) from exc

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
