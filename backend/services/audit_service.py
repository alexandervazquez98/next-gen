"""Centralized helpers for dedicated audit event persistence and retention."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from models.audit_event import AuditEvent
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

AUDIT_SCHEMA_VERSION = 1
AUDIT_RETENTION_DAYS = 90

AUDIT_CONTEXT_ALLOWED_KEYS = {
    "route",
    "method",
    "request_id",
    "changed_fields",
    "required_permission",
    # PR1 #287 — auth session lifecycle context for
    # `session.activity_recorded` and `session.idle_expired` events.
    "session_id",
    "user_id",
    "policy_profile",
    "throttle_seconds",
    "activity_anchor",
    # PR1 #154 — stale event review reminders quick-action context. The
    # three keys below are appended to the allow-list so the audit rows
    # emitted by `routers/event_recommendations.py` (event_id, reason_code,
    # snooze_until) survive `sanitize_context` without leaking tokens,
    # cookies, authorization headers, or raw request bodies. They are
    # additive: existing call sites continue to use their existing key set.
    "event_id",
    "reason_code",
    "snooze_until",
}

SENSITIVE_CONTEXT_KEYS = {
    "authorization",
    "body",
    "cookie",
    "cookies",
    "password",
    "raw_body",
    "refresh_token",
    "request_body",
    "session_token",
    "token",
}

_MAX_REASON_LENGTH = 128
_MAX_LABEL_LENGTH = 256
_MAX_USER_AGENT_LENGTH = 256
_MAX_CONTEXT_VALUE_LENGTH = 256


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _truncate(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= max_length:
        return text
    return text[:max_length]


def _safe_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return _truncate(value, _MAX_CONTEXT_VALUE_LENGTH)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _truncate(value, _MAX_CONTEXT_VALUE_LENGTH)


def _safe_context_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _safe_context_value(nested_value)
            for key, nested_value in value.items()
            if str(key).lower() not in SENSITIVE_CONTEXT_KEYS
        }
    if isinstance(value, list):
        return [_safe_context_value(item) for item in value[:25]]
    return _safe_scalar(value)


def sanitize_context(context: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return allow-listed audit context without sensitive fields or unbounded values."""

    if not context:
        return None

    safe: dict[str, Any] = {}
    for key, value in context.items():
        key_text = str(key)
        if key_text.lower() in SENSITIVE_CONTEXT_KEYS:
            continue
        if key_text not in AUDIT_CONTEXT_ALLOWED_KEYS:
            continue
        safe[key_text] = _safe_context_value(value)
    return safe or None


def build_request_context(request: Any | None) -> dict[str, Any]:
    """Extract allow-listed, non-sensitive context from a FastAPI request."""

    if request is None:
        return {}

    context: dict[str, Any] = {}
    url = getattr(request, "url", None)
    path = getattr(url, "path", None)
    if path:
        context["route"] = path

    method = getattr(request, "method", None)
    if method:
        context["method"] = method

    headers = getattr(request, "headers", {}) or {}
    request_id = headers.get("x-request-id") if hasattr(headers, "get") else None
    if request_id:
        context["request_id"] = request_id

    return context


def _request_ip(request: Any | None) -> str | None:
    if request is None:
        return None
    headers = getattr(request, "headers", {}) or {}
    forwarded_for = headers.get("x-forwarded-for") if hasattr(headers, "get") else None
    if forwarded_for:
        return _truncate(str(forwarded_for).split(",", 1)[0].strip(), 64)
    client = getattr(request, "client", None)
    return _truncate(getattr(client, "host", None), 64)


def _request_user_agent(request: Any | None) -> str | None:
    if request is None:
        return None
    headers = getattr(request, "headers", {}) or {}
    user_agent = headers.get("user-agent") if hasattr(headers, "get") else None
    return _truncate(user_agent, _MAX_USER_AGENT_LENGTH)


def _actor_username(actor: Any | None) -> str | None:
    return _truncate(getattr(actor, "username", None), 128)


def _actor_role(actor: Any | None) -> str | None:
    return _truncate(getattr(actor, "role", None), 64)


def _persist_event(db: Session, event: AuditEvent) -> AuditEvent | None:
    try:
        db.add(event)
        db.commit()
        db.refresh(event)
        return event
    except Exception as exc:  # pragma: no cover - defensive operational safety path
        db.rollback()
        logger.warning("Failed to persist audit event: %s", exc)
        return None


def record_auth_event(
    db: Session,
    request: Any | None,
    event_type: str,
    outcome: str,
    actor_username: str | None = None,
    reason: str | None = None,
    context: dict[str, Any] | None = None,
) -> AuditEvent | None:
    request_context = build_request_context(request)
    if context:
        request_context.update(context)

    event = AuditEvent(
        schema_version=AUDIT_SCHEMA_VERSION,
        event_type=event_type,
        outcome=outcome,
        actor_username=_truncate(actor_username, 128),
        target_type="auth",
        target_id=_truncate(actor_username, 256),
        target_label=_truncate(actor_username, _MAX_LABEL_LENGTH),
        source="auth",
        ip_address=_request_ip(request),
        user_agent=_request_user_agent(request),
        reason=_truncate(reason, _MAX_REASON_LENGTH),
        context=sanitize_context(request_context),
        created_at=_utcnow_naive(),
    )
    return _persist_event(db, event)


def record_critical_change(
    db: Session,
    request: Any | None,
    actor: Any | None,
    event_type: str,
    outcome: str,
    target_type: str,
    target_id: str | None,
    target_label: str | None = None,
    reason: str | None = None,
    source: str | None = None,
    context: dict[str, Any] | None = None,
) -> AuditEvent | None:
    request_context = build_request_context(request)
    if context:
        request_context.update(context)

    event = AuditEvent(
        schema_version=AUDIT_SCHEMA_VERSION,
        event_type=event_type,
        outcome=outcome,
        actor_username=_actor_username(actor),
        actor_role=_actor_role(actor),
        target_type=_truncate(target_type, 64),
        target_id=_truncate(target_id, 256),
        target_label=_truncate(target_label, _MAX_LABEL_LENGTH),
        source=_truncate(source, 64),
        ip_address=_request_ip(request),
        user_agent=_request_user_agent(request),
        reason=_truncate(reason, _MAX_REASON_LENGTH),
        context=sanitize_context(request_context),
        created_at=_utcnow_naive(),
    )
    return _persist_event(db, event)


def record_denied(
    db: Session,
    request: Any | None,
    actor: Any | None,
    required_permission: Any,
    target_type: str,
    target_id: str | None = None,
    reason: str | None = None,
    source: str | None = None,
) -> AuditEvent | None:
    permission_value = getattr(required_permission, "value", required_permission)
    return record_critical_change(
        db=db,
        request=request,
        actor=actor,
        event_type="ACCESS_DENIED",
        outcome="DENIED",
        target_type=target_type,
        target_id=target_id,
        reason=reason or f"missing_permission:{permission_value}",
        source=source,
        context={"required_permission": permission_value},
    )


def cleanup_old_events(
    db: Session,
    retention_days: int = AUDIT_RETENTION_DAYS,
    now: datetime | None = None,
) -> int:
    """Delete audit events strictly older than the retention window."""

    reference = _as_naive_utc(now or datetime.now(UTC))
    cutoff = reference - timedelta(days=retention_days)
    stale_query = db.query(AuditEvent).filter(AuditEvent.created_at < cutoff)
    deleted = stale_query.delete(synchronize_session=False)
    db.commit()
    return deleted


def run_audit_retention_cleanup(retention_days: int = AUDIT_RETENTION_DAYS) -> int:
    """Scheduler entrypoint for audit retention cleanup."""

    from postgres_db import SessionLocal

    db = SessionLocal()
    try:
        return cleanup_old_events(db, retention_days=retention_days)
    finally:
        db.close()
