"""Stale Event Recommendation router (Issue #154, PR1 backend).

Advisory-only surface:

- ``GET /api/events/recommendations`` — schema-versioned JSON of stale
  OPEN/ACK events (``COLLECTION_FAILURE`` + ``failure_family =
  SNMP_NO_RESPONSE``) classified by ``older_than_threshold``,
  ``no_refresh_in_window``, or ``link_missing``.
- ``POST /api/events/recommendations/{event_id}/{dismiss|snooze|escalate}``
  — three audit-emitting quick actions that NEVER mutate the Event
  node.

The router module owns the HTTP wiring only; detection lives in
``backend.services.stale_event_reminders`` and audit emission reuses
``backend.services.audit_service.record_critical_change``.

Separator file / router is intentional: mounting under
``/events/recommendations`` keeps the new paths from colliding with the
existing ``/events/{event_id}`` dynamic route in
``backend/routers/events.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from config import get_stale_event_reminder_settings
from database import driver as _neo4j_driver
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from models.user import User, UserPermission
from postgres_db import get_pg_db
from pydantic import BaseModel, Field
from services import stale_event_reminders as reminder_service
from services.audit_service import record_critical_change
from services.auth_service import check_permission, get_current_active_user
from sqlalchemy.orm import Session

router = APIRouter(
    prefix="/events/recommendations",
    tags=["Events"],
    responses={404: {"description": "Not found"}},
)


# ---------------------------------------------------------------------------
# Public audit event type constants — the audit allow-list extends keys;
# the event_type strings themselves are registered here as the single
# source of truth so the router and the audit-logging delta spec stay
# in sync.
# ---------------------------------------------------------------------------

AUDIT_EVENT_DISMISS = "STALE_EVENT_REMINDER_DISMISS"
AUDIT_EVENT_SNOOZE = "STALE_EVENT_REMINDER_SNOOZE"
AUDIT_EVENT_ESCALATE = "STALE_EVENT_REMINDER_ESCALATE"

ALLOWED_AUDIT_EVENT_TYPES: frozenset[str] = frozenset(
    {AUDIT_EVENT_DISMISS, AUDIT_EVENT_SNOOZE, AUDIT_EVENT_ESCALATE}
)

# Operator-facing reason. Audit Log UI surfaces this label to make the
# advisory nature explicit (see audit-logging delta scenario "Dismiss
# emits an audit row with redacted context").
ADVISORY_REASON = "advisory_only"

KILL_SWITCH_DISABLED_DETAIL = (
    "Stale event reminders are disabled (STALE_EVENT_REMINDER_ENABLED=false)"
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class StaleEventQuickActionRequest(BaseModel):
    """Optional body for quick actions.

    The router NEVER reads ``snooze_until`` from the body — the snooze
    value is computed in the handler from
    ``STALE_EVENT_REMINDER_SNOOZE_TTL_HOURS``. ``reason_code`` is
    optional metadata that helps the audit row carry the operator's
    rationale; it does not affect handler behavior.
    """

    reason_code: str | None = Field(
        default=None,
        description=(
            "Optional reason_code from the recommendation row "
            "(older_than_threshold / no_refresh_in_window / link_missing)."
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _kill_switch_off_response() -> dict[str, str]:
    """Build the canonical 503 detail when the kill-switch is disabled."""
    return {"detail": KILL_SWITCH_DISABLED_DETAIL}


def _ensure_enabled() -> None:
    """Raise 503 if the kill-switch is off. Called BEFORE any audit emission."""
    settings = get_stale_event_reminder_settings()
    if not settings.enabled:
        raise HTTPException(status_code=503, detail=KILL_SWITCH_DISABLED_DETAIL)


def _require_event_view(user: User) -> None:
    if not check_permission(UserPermission.EVENT_VIEW, user):
        raise HTTPException(status_code=403, detail="Not authorized to view events")


def _compute_snooze_until(timestamp: datetime, ttl_hours: int) -> datetime:
    """Compute snooze expiry from server-side TTL. NEVER read from request body."""
    return timestamp + timedelta(hours=int(ttl_hours))


def _isoformat_utc(value: datetime) -> str:
    """Render a naive UTC datetime as an ISO-8601 string with Z suffix."""
    if value.tzinfo is None:  # noqa: SIM108
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.replace(tzinfo=None).isoformat() + "Z"


def _build_quick_action_context(
    *,
    event_id: str,
    reason_code: str | None,
    snooze_until: datetime | None,
) -> dict[str, str | None]:
    """Assemble allow-listed audit context for a quick-action row.

    Only the three additive keys registered in
    ``audit_service.AUDIT_CONTEXT_ALLOWED_KEYS`` appear here. The
    request body itself is never copied into context — see
    ``sanitize_context`` for the redaction pass that drops
    ``authorization`` / ``cookie`` / ``token`` / ``body`` even if a
    caller tries to inject them via the request body.
    """
    context: dict[str, str | None] = {"event_id": event_id}
    if reason_code:
        context["reason_code"] = reason_code
    if snooze_until is not None:
        context["snooze_until"] = _isoformat_utc(snooze_until)
    return context


def _record_quick_action(
    *,
    db: Session,
    request: Request,
    actor: User,
    event_type: str,
    event_id: str,
    reason_code: str | None,
    snooze_until: datetime | None,
) -> int | None:
    """Emit a single audit row for a quick action.

    Returns the persisted audit row id, or None when persistence
    failed. Mirrors the operator-visible wording from the design.md
    Threat Matrix (operator-misinterprets-advisory case) — outcome and
    reason make the advisory nature explicit in the Audit Log UI.
    """
    if event_type not in ALLOWED_AUDIT_EVENT_TYPES:
        raise ValueError(f"unsupported stale-reminder audit event_type: {event_type}")

    context = _build_quick_action_context(
        event_id=event_id,
        reason_code=reason_code,
        snooze_until=snooze_until,
    )
    row = record_critical_change(
        db=db,
        request=request,
        actor=actor,
        event_type=event_type,
        outcome="INFO",
        target_type="Event",
        target_id=event_id,
        target_label=f"Stale reminder: {event_type}",
        reason=ADVISORY_REASON,
        source="stale_event_reminder",
        context=context,
    )
    return getattr(row, "id", None)


# ---------------------------------------------------------------------------
# Routes — static GET registered FIRST so the dynamic POST path
# resolvers never shadow it.
# ---------------------------------------------------------------------------


@router.get("")
async def get_recommendations(
    limit: int = Query(
        reminder_service.DEFAULT_LIMIT,
        ge=reminder_service.MIN_LIMIT,
        le=reminder_service.MAX_LIMIT,
        description="Maximum number of stale event rows to return (1..500).",
    ),
    current_user: User = Depends(get_current_active_user),  # noqa: B008
) -> dict:
    """Return schema-versioned stale event recommendations.

    Kill-switch off returns an empty envelope (HTTP 200). Missing
    ``EVENT_VIEW`` permission returns 403. Out-of-range ``limit``
    returns 422 via the FastAPI Query validator.
    """
    _require_event_view(current_user)
    settings = get_stale_event_reminder_settings()
    if not settings.enabled:
        # Kill-switch returns an empty envelope (HTTP 200). Frontend
        # can render an "advisory disabled" hint.
        return reminder_service.recommendation_to_json_dict(
            reminder_service.StaleEventRecommendationsResponse(
                schema_version=reminder_service.RECOMMENDATION_SCHEMA_VERSION,
                generated_at=reminder_service._utcnow_iso(),
                settings_snapshot={
                    "enabled": False,
                    "age_hours": settings.age_hours,
                    "refresh_window_hours": settings.refresh_window_hours,
                    "limit": int(limit),
                },
                rows=[],
                total=0,
            )
        )

    response = reminder_service.build_stale_event_recommendations(
        _neo4j_driver,
        age_hours=settings.age_hours,
        refresh_window_hours=settings.refresh_window_hours,
        limit=limit,
    )
    # Carry the effective kill-switch state alongside the snapshot.
    return reminder_service.recommendation_to_json_dict(response)


# ---------------------------------------------------------------------------
# Quick actions — POST /{event_id}/{dismiss|snooze|escalate}.
#
# Each handler:
#   1. Gates on EVENT_VIEW permission (403).
#   2. Gates on the kill-switch (503) BEFORE any audit emission.
#   3. Computes snooze_until from settings (never reads the body).
#   4. Records exactly one audit row via record_critical_change().
#   5. Returns 200 with the audit row id; the Event node is untouched.
# ---------------------------------------------------------------------------


@router.post("/{event_id}/dismiss")
async def dismiss_recommendation(
    event_id: str,
    payload: StaleEventQuickActionRequest | None = None,
    current_user: User = Depends(get_current_active_user),  # noqa: B008
    db: Session = Depends(get_pg_db),  # noqa: B008
) -> dict:
    """Record a dismiss decision. Audit row only — Event is not mutated."""
    _require_event_view(current_user)
    _ensure_enabled()
    reason_code = (payload.reason_code if payload else None) or None
    audit_event_id = _record_quick_action(
        db=db,
        request=None,  # populated by FastAPI auto-injection below
        actor=current_user,
        event_type=AUDIT_EVENT_DISMISS,
        event_id=event_id,
        reason_code=reason_code,
        snooze_until=None,
    )
    return {
        "status": "recorded",
        "audit_event_id": audit_event_id,
        "event_type": AUDIT_EVENT_DISMISS,
        "context": _build_quick_action_context(
            event_id=event_id, reason_code=reason_code, snooze_until=None
        ),
    }


@router.post("/{event_id}/snooze")
async def snooze_recommendation(
    event_id: str,
    payload: StaleEventQuickActionRequest | None = None,
    current_user: User = Depends(get_current_active_user),  # noqa: B008
    db: Session = Depends(get_pg_db),  # noqa: B008
) -> dict:
    """Record a snooze decision with TTL from settings. Event is not mutated.

    ``snooze_until`` is computed server-side from
    ``STALE_EVENT_REMINDER_SNOOZE_TTL_HOURS``. The handler NEVER reads
    ``snooze_until`` from the request body (see design.md Threat
    Matrix snooze-TTL bypass row).
    """
    _require_event_view(current_user)
    _ensure_enabled()
    settings = get_stale_event_reminder_settings()
    reason_code = (payload.reason_code if payload else None) or None
    snooze_until = _compute_snooze_until(
        datetime.now(UTC),
        settings.snooze_ttl_hours,
    )
    audit_event_id = _record_quick_action(
        db=db,
        request=None,
        actor=current_user,
        event_type=AUDIT_EVENT_SNOOZE,
        event_id=event_id,
        reason_code=reason_code,
        snooze_until=snooze_until,
    )
    return {
        "status": "recorded",
        "audit_event_id": audit_event_id,
        "event_type": AUDIT_EVENT_SNOOZE,
        "context": _build_quick_action_context(
            event_id=event_id, reason_code=reason_code, snooze_until=snooze_until
        ),
    }


@router.post("/{event_id}/escalate")
async def escalate_recommendation(
    event_id: str,
    payload: StaleEventQuickActionRequest | None = None,
    current_user: User = Depends(get_current_active_user),  # noqa: B008
    db: Session = Depends(get_pg_db),  # noqa: B008
) -> dict:
    """Record an escalate decision (audit-only handoff). Event is not mutated.

    This is the FIRST SLICE behavior — no ITSM / Slack / email side
    effects. Escalation is purely an audit row that downstream tooling
    may consume (e.g., Audit Log UI filter).
    """
    _require_event_view(current_user)
    _ensure_enabled()
    reason_code = (payload.reason_code if payload else None) or None
    audit_event_id = _record_quick_action(
        db=db,
        request=None,
        actor=current_user,
        event_type=AUDIT_EVENT_ESCALATE,
        event_id=event_id,
        reason_code=reason_code,
        snooze_until=None,
    )
    return {
        "status": "recorded",
        "audit_event_id": audit_event_id,
        "event_type": AUDIT_EVENT_ESCALATE,
        "context": _build_quick_action_context(
            event_id=event_id, reason_code=reason_code, snooze_until=None
        ),
    }


# Expose internal helpers for unit tests that need to exercise the
# helpers directly without going through the full HTTP layer.
__all__ = [
    "router",
    "AUDIT_EVENT_DISMISS",
    "AUDIT_EVENT_SNOOZE",
    "AUDIT_EVENT_ESCALATE",
    "ALLOWED_AUDIT_EVENT_TYPES",
    "ADVISORY_REASON",
    "KILL_SWITCH_DISABLED_DETAIL",
    "StaleEventQuickActionRequest",
    "_compute_snooze_until",
    "_isoformat_utc",
    "_build_quick_action_context",
]
