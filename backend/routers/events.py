from datetime import datetime
from typing import Any

import services.event_service as event_service
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from models.core import (
    AffectedCI,
    AvailabilityReportResponse,
    AvailabilitySnmpNoResponseResponse,
    EventDetailResponse,
    EventFeedSummary,
)
from models.user import AIPermission, User, UserPermission
from pydantic import BaseModel
from services.ai_guard_service import check_all_guards, record_operation, set_cooldown
from services.auth_service import (
    check_permission,
    get_current_active_user,
)
from services.escalation_notifier import notify_critical_event_escalation

router = APIRouter(
    prefix="/events",
    tags=["Events"],
    responses={404: {"description": "Not found"}},
)


class EventComment(BaseModel):
    message: str


class AckRequest(BaseModel):
    comment_message: str | None = None


class CloseRequest(BaseModel):
    forced: bool = False
    comment_message: str | None = None


def _is_ai_agent(current_user: User) -> bool:
    return bool(current_user.role and str(current_user.role).startswith("AI_"))


def _has_ai_permission(permission: AIPermission, current_user: User) -> bool:
    return permission.value in current_user.permissions


@router.get("", response_model=list[EventFeedSummary], response_model_exclude_none=True)
async def get_events(
    status: str | None = None,
    include_children: bool = Query(  # noqa: B008
        False,
        description=(
            "When false (default), only ROOT events are returned. Set to true "
            "to retain legacy PROPAGATED child rows (audit, AI chat context)."
        ),
    ),
):
    """
    Fetch system events filtered by status.

    Args:
        status: 'OPEN', 'ACK', 'CLOSED', 'RECOVERED', 'ACTIVE' (Open/Ack),
            or 'CONSOLE' (Open/Ack/Recovered).
        include_children: default False (root-only feed). See P2 REQ-003.

    P2 REQ-001 / SCN-010: `response_model_exclude_none=True` guarantees that
    absent `affected_ci_ids` / `affected_count` fields stay absent from the
    JSON payload. The service-side `_public_event_summary` drops null
    values, but FastAPI's default response-model serialization rebuilds
    the schema and would re-emit the schema defaults as `null`; the
    exclude_none flag preserves the omission contract end-to-end.
    """
    return event_service.get_events(status, include_children=include_children)


@router.get("/availability-report", response_model=AvailabilityReportResponse)
async def get_availability_report(
    start: datetime | None = Query(None, description="Inclusive report window start"),  # noqa: B008
    end: datetime | None = Query(None, description="Inclusive report window end"),  # noqa: B008
):
    """Fetch additive availability MTTR/MTBF metrics for the event dashboard."""
    return event_service.get_availability_report(start=start, end=end)


@router.get(
    "/availability-report/snmp-no-response",
    response_model=AvailabilitySnmpNoResponseResponse,
)
async def get_availability_snmp_no_response(
    limit: int = Query(25, ge=1, le=100, description="Maximum affected CIs to return"),
    offset: int = Query(0, ge=0, description="Affected CI pagination offset"),
    current_user: User = Depends(get_current_active_user),  # noqa: B008
):
    """Fetch affected CIs with active SNMP no-response collection failures."""
    if not check_permission(UserPermission.EVENT_VIEW, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to view events")
    return event_service.get_availability_snmp_no_response_drilldown(
        limit=limit,
        offset=offset,
    )


@router.get("/{event_id}/affected", response_model=list[AffectedCI])
async def get_event_affected(
    event_id: str, current_user: User = Depends(get_current_active_user)  # noqa: B008
):
    """Drill-down endpoint returning the CI list affected by a ROOT event.

    P2 REQ-004: declared BEFORE `/{event_id}` so the path resolver wins
    the precedence race. Unknown or non-ROOT ids answer 404 with the
    canonical detail string from `_raise_event_not_found`. The guard
    mirrors `GET /events/{event_id}`.
    """
    if not check_permission(UserPermission.EVENT_VIEW, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to view events")
    return event_service.get_affected_siblings(event_id)


@router.get("/{event_id}", response_model=EventDetailResponse)
async def get_event_detail(
    event_id: str, current_user: User = Depends(get_current_active_user)  # noqa: B008
):
    """Fetch modal-specific event detail without bloating the summary feed."""
    if not check_permission(UserPermission.EVENT_VIEW, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to view events")
    return event_service.get_event_detail(event_id)


@router.get("/related/{ci_id}", response_model=list[dict[str, Any]])
async def get_related_events(
    ci_id: str, current_user: User = Depends(get_current_active_user)  # noqa: B008
):
    """
    Fetch all ACTIVE (OPEN, ACK) events for a specific CI.
    """
    if not check_permission(UserPermission.EVENT_VIEW, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to view events")
    return event_service.get_related_events(ci_id)


@router.post("/{event_id}/ack")
async def ack_event(
    event_id: str,
    ack_req: AckRequest | None = None,
    current_user: User = Depends(get_current_active_user),  # noqa: B008
):
    """
    Acknowledge an Event.
    """
    ack_req = ack_req or AckRequest()
    is_ai_agent = _is_ai_agent(current_user)
    if is_ai_agent:
        if not _has_ai_permission(AIPermission.AI_EVENT_ACK, current_user):
            raise HTTPException(
                status_code=403,
                detail="Not authorized to acknowledge events",
            )
    elif not check_permission(UserPermission.EVENT_ACK, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to acknowledge events")

    # AI agent guard check
    ai_info = None
    if is_ai_agent:
        # The check_all_guards function needs ai_agent_id - use username as id
        guard_result = check_all_guards(current_user.username, "ack", [event_id])
        if not guard_result.allowed:
            raise HTTPException(status_code=403, detail=guard_result.reason)
        ai_info = current_user.username  # used for record_operation

    result = event_service.ack_event(
        event_id,
        current_user.username,
        comment_message=ack_req.comment_message,
    )

    # Record AI operation after success
    if ai_info is not None:
        record_operation(
            ai_persona=str(current_user.role),
            ai_agent_id=current_user.username,
            operation="ack",
            target_type="event",
            target_id=event_id,
            target_name=f"Event {event_id}",
            result="success",
        )

    return result


@router.post("/{event_id}/close")
async def close_event(
    event_id: str,
    close_req: CloseRequest | None = None,
    current_user: User = Depends(get_current_active_user),  # noqa: B008
):
    """
    Close an Event manually.
    If forced=True, the caller must also hold EVENT_FORCED_CLOSE permission.
    AI agents cannot force-close events.
    """
    close_req = close_req or CloseRequest()
    is_ai_agent = _is_ai_agent(current_user)
    if is_ai_agent:
        if not _has_ai_permission(AIPermission.AI_EVENT_CLOSE, current_user):
            raise HTTPException(status_code=403, detail="Not authorized to close events")
    elif not check_permission(UserPermission.EVENT_CLOSE, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to close events")
    if close_req.forced and is_ai_agent:
        raise HTTPException(
            status_code=403,
            detail="AI agents cannot force-close events",
        )
    if close_req.forced and not check_permission(UserPermission.EVENT_FORCED_CLOSE, current_user):
        raise HTTPException(
            status_code=403,
            detail="Not authorized to force-close events (EVENT_FORCED_CLOSE required)",
        )

    # AI agent guard check
    ai_info = None
    if is_ai_agent:
        guard_result = check_all_guards(current_user.username, "close", [event_id])
        if not guard_result.allowed:
            raise HTTPException(status_code=403, detail=guard_result.reason)
        ai_info = current_user.username

    # Check if event is CRITICAL — requires escalation for ALL users (not just AI)
    event_detail = event_service.get_event_detail(event_id)
    severity = event_detail.get("event", {}).get("severity", "")

    if severity == "CRITICAL":
        # Notify human and log escalation
        event_msg = event_detail.get("event", {}).get("message", "")
        ci_id = event_detail.get("event", {}).get("ci", {}).get("id", "")
        ci_name = event_detail.get("event", {}).get("ci", {}).get("label", "")
        await notify_critical_event_escalation(
            ai_persona=str(current_user.role),
            ai_agent_id=current_user.username,
            event_id=event_id,
            event_message=event_msg,
            ci_id=ci_id or event_id,
            ci_name=ci_name or "Unknown CI",
        )
        record_operation(
            ai_persona=str(current_user.role),
            ai_agent_id=current_user.username,
            operation="close",
            target_type="event",
            target_id=event_id,
            target_name=f"Event {event_id}",
            result="escalated",
            blocked_reason="CRITICAL event requires human approval to close",
        )
        # C1 fix: still close the event (flagged as pending human review per spec)
        # C1 fix: set cooldown for CRITICAL events too
        set_cooldown(current_user.username, "close", event_id)

    result = event_service.close_event(
        event_id,
        current_user.username,
        forced=close_req.forced,
        comment_message=close_req.comment_message,
    )

    # Record AI operation after success
    if ai_info is not None:
        record_operation(
            ai_persona=str(current_user.role),
            ai_agent_id=current_user.username,
            operation="close",
            target_type="event",
            target_id=event_id,
            target_name=f"Event {event_id}",
            result="success",
        )

    return result


@router.post("/{event_id}/comment")
async def add_event_comment(
    event_id: str,
    comment: EventComment,
    current_user: User = Depends(get_current_active_user),  # noqa: B008
):
    """
    Append a user comment to the Event history.
    """
    is_ai_agent = _is_ai_agent(current_user)
    if is_ai_agent:
        authorized = _has_ai_permission(AIPermission.AI_EVENT_COMMENT, current_user)
    else:
        authorized = check_permission(UserPermission.EVENT_ACK, current_user)

    if not authorized:
        raise HTTPException(status_code=403, detail="Not authorized to comment on events")
    return event_service.add_event_comment(event_id, current_user.username, comment.message)


@router.post("/prune")
async def prune_recovered_events(
    current_user: User = Depends(get_current_active_user),  # noqa: B008
):
    """
    Bulk Close all 'RECOVERED' events (sync version).
    """
    if not check_permission(UserPermission.EVENT_CLOSE, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to prune events")
    return event_service.prune_recovered_events(current_user.username)


async def _sse_event_generator(
    user: str,
    batch_size: int | None = None,
    last_event_id: str | None = None,
):
    """
    Async generator that yields SSE-formatted progress events.
    Each chunk is sent as a server-sent event with the progress dict as data.

    WARNING #4 fix: Uses try/finally to ensure cleanup runs on disconnect,
    preventing abandoned generator resource leaks.

    Distributed lock: endpoint already acquired lock before SSE starts.
    Generator releases lock when stream ends (client disconnect or completion).
    """
    import json

    try:
        async for progress in event_service.event_batch_pruner(
            user=user,
            batch_size=batch_size,
            last_cursor=last_event_id,  # WARNING #5 fix: Last-Event-ID used as cursor
        ):
            # Format as SSE: "data: {json}\n\n"
            yield f"data: {json.dumps(progress)}\n\n"
    finally:
        # WARNING #4 fix: explicit cleanup when client disconnects
        # Release distributed lock when SSE stream ends
        from services.event_service import release_prune_lock

        release_prune_lock(owner=user)


@router.get("/bulk/stream-progress")
async def stream_prune_progress(
    request: Request,
    current_user: User = Depends(get_current_active_user),  # noqa: B008
):
    """
    SSE endpoint that streams batch pruning progress in real-time.

    Clients can reconnect using the Last-Event-ID header to resume from
    the last received event ID (useful for long-running operations).
    Last-Event-ID is parsed as the created_at timestamp cursor.

    Requires EVENT_CLOSE permission.

    Distributed lock ensures only ONE prune operation can run at a time
    across ALL operators. Returns HTTP 409 if another prune is in progress.
    """
    if not check_permission(UserPermission.EVENT_CLOSE, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to prune events")

    # Check distributed lock BEFORE starting SSE stream
    from services.event_service import acquire_prune_lock

    if not acquire_prune_lock(owner=current_user.username, ttl_seconds=300):
        raise HTTPException(
            status_code=409,
            detail="Another prune operation is in progress",
        )

    # WARNING #6 fix: validate batch_size is a positive integer, cap at max 10000
    batch_size_str = request.query_params.get("batch_size")
    batch_size: int | None = None
    if batch_size_str:
        try:
            batch_size = int(batch_size_str)
            if batch_size <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="batch_size must be a positive integer",
                )
            if batch_size > 10000:
                raise HTTPException(
                    status_code=400,
                    detail="batch_size must not exceed 10000",
                )
        except ValueError:
            raise HTTPException(  # noqa: B904
                status_code=400,
                detail="batch_size must be a valid integer",
            )

    # WARNING #5 fix: read Last-Event-ID header to support reconnection
    last_event_id = request.headers.get("Last-Event-ID")

    return StreamingResponse(
        _sse_event_generator(
            user=current_user.username,
            batch_size=batch_size,
            last_event_id=last_event_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.post("/{event_id}/diagnose")
async def run_event_diagnostic_endpoint(
    event_id: str, current_user: User = Depends(get_current_active_user)  # noqa: B008
):
    """
    Run an on-demand diagnostic (Ping/SNMP) for the CI related to this event.
    """
    is_ai_agent = _is_ai_agent(current_user)
    if is_ai_agent:
        if not _has_ai_permission(AIPermission.AI_RUN_DIAGNOSTIC, current_user):
            raise HTTPException(status_code=403, detail="Not authorized to run diagnostics")
    elif not check_permission(UserPermission.RUN_DIAGNOSTICS, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to run diagnostics")

    # AI agent guard check
    ai_info = None
    if is_ai_agent:
        guard_result = check_all_guards(current_user.username, "diagnose", [event_id])
        if not guard_result.allowed:
            raise HTTPException(status_code=403, detail=guard_result.reason)
        ai_info = current_user.username

    result = event_service.run_event_diagnostic(event_id, current_user.username)

    # Record AI operation after success
    if ai_info is not None:
        # Get event info for target_name
        event_detail = event_service.get_event_detail(event_id)
        ci_name = event_detail.get("event", {}).get("ci", {}).get("label", f"CI {event_id}")
        record_operation(
            ai_persona=str(current_user.role),
            ai_agent_id=current_user.username,
            operation="diagnose",
            target_type="ci",
            target_id=event_id,
            target_name=ci_name,
            result="success",
        )

    return result
