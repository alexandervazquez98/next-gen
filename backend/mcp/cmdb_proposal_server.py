"""MCP server wrapper for CMDB proposal operations — feat-cmdb-ai-handoff (T-2.6).

Exposes 4 tools:
- propose_ci
- list_proposals
- approve_proposal
- revoke_proposal

Each tool delegates **directly** to ``services.cmdb_proposal_service``
(no HTTP loopback), matching the in-process invocation pattern used by
``services/ai_guard_service.py``.

Auth:
- Bearer token resolved by ``_resolve_user_from_bearer`` which decodes the
  JWT subject and looks up the user (mirrors the AI agent resolver).
- Each tool checks the right permission (AI_PROPOSE_CI / CI_VIEW /
  CI_APPROVE_PROPOSAL) and raises HTTPException(403) otherwise.

Rate limit:
- CMDB_PROPOSAL_RPM (default 60) calls/min per token
- CMDB_PROPOSAL_USER_RPM (default 30) calls/min per user
- Exceeding either returns HTTPException(429)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import HTTPException

logger = logging.getLogger(__name__)


# Configurable rate limits (env-overridable)
CMDB_PROPOSAL_RPM = int(os.getenv("CMDB_PROPOSAL_RPM", "60"))
CMDB_PROPOSAL_USER_RPM = int(os.getenv("CMDB_PROPOSAL_USER_RPM", "30"))


# ── in-process rate limiter ────────────────────────────────────────────────────


class _RateLimiter:
    """Sliding-window counter, per (token / user). Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token_calls: dict[str, deque[float]] = defaultdict(deque)
        self._user_calls: dict[str, deque[float]] = defaultdict(deque)

    def allow(
        self,
        *,
        token: str | None,
        user_id: str | None,
        rpm_token: int | None = None,
        rpm_user: int | None = None,
    ) -> bool:
        now = time.monotonic()
        # Re-read env so test-time monkeypatch.setenv takes effect.
        rpm_token_eff = rpm_token if rpm_token is not None else int(
            os.getenv("CMDB_PROPOSAL_RPM", str(CMDB_PROPOSAL_RPM))
        )
        rpm_user_eff = rpm_user if rpm_user is not None else int(
            os.getenv("CMDB_PROPOSAL_USER_RPM", str(CMDB_PROPOSAL_USER_RPM))
        )
        with self._lock:
            for bucket, limit in (
                (self._token_calls.get(token or "") if token else None, rpm_token_eff),
                (self._user_calls.get(user_id or "") if user_id else None, rpm_user_eff),
            ):
                if bucket is None:
                    continue
                cutoff = now - 60.0
                while bucket and bucket[0] < cutoff:
                    bucket.popleft()
                if len(bucket) >= limit:
                    return False
            if token:
                self._token_calls[token].append(now)
            if user_id:
                self._user_calls[user_id].append(now)
            return True


_rate_limiter = _RateLimiter()


def _check_tool_rate_limit(
    token: str | None,
    user_id: str | None,
    *,
    rpm_token: int | None = None,
    rpm_user: int | None = None,
) -> bool:
    """Allow or block a tool call by sliding-window rate limit."""
    return _rate_limiter.allow(
        token=token, user_id=user_id, rpm_token=rpm_token, rpm_user=rpm_user
    )


# ── bearer -> user resolver ───────────────────────────────────────────────────


def _resolve_user_from_bearer(token: str | None) -> Any:
    """Decode the bearer JWT and return the matching User.

    Mirrors the AI agent resolver but for human-style bearer tokens (HMAC).
    Returns None when the token is invalid; the tool raises HTTPException(401).
    """
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if token.startswith("Bearer "):
        token = token[7:]

    from jose import JWTError, jwt
    from models.user import UserInDB
    from postgres_db import get_pg_db
    from repositories import user_repo

    secret = os.environ.get("JWT_SECRET_KEY")
    if not secret:
        raise HTTPException(status_code=500, detail="JWT_SECRET_KEY not configured")

    credentials_exc = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except JWTError:
        raise credentials_exc

    username = payload.get("sub")
    if not username:
        raise credentials_exc

    db = get_pg_db()
    user = user_repo.get_user_by_username(db, username=username)
    if user is None:
        raise credentials_exc

    return UserInDB(
        username=user.username,
        hashed_password=user.hashed_password,
        password=user.hashed_password,
        role=user.role,
        permissions=user.permissions,
        allowed_locations=user.allowed_locations,
        allowed_ci_types=user.allowed_ci_types,
        phone=user.phone,
        email=user.email,
        disabled=not user.is_active,
        force_password_change=user.force_password_change,
        tier=user.tier or "T1",
    )


def _require_permission(user: Any, permission_value: str) -> None:
    """HTTP 403 when user lacks the permission (Admin bypass)."""
    if user.role == "ADMIN":
        return
    if permission_value not in (user.permissions or []):
        raise HTTPException(
            status_code=403,
            detail=f"missing_permission: {permission_value} required",
        )


# ── service layer seam (tests monkeypatch this) ───────────────────────────────


def _service():
    """Default factory; tests monkeypatch to swap in a stub."""
    from services import cmdb_proposal_service

    return cmdb_proposal_service


# ── tool implementations ──────────────────────────────────────────────────────


def tool_propose_ci(*, token: str | None, manifest: dict[str, Any]) -> dict[str, Any]:
    """MCP tool: propose_ci — submit a CI manifest."""
    user = _resolve_user_from_bearer(token)
    if not _check_tool_rate_limit(token=getattr(user, "username", None), user_id=user.username):
        raise HTTPException(status_code=429, detail="rate_limit_exceeded")

    _require_permission(user, "AI_PROPOSE_CI")

    result = _service().create_proposal(
        manifest=manifest,
        user=user,
        ai_agent_id=user.username,
        db=None,
        request=None,
    )
    if isinstance(result, dict) and result.get("harness_result", {}).get("denied"):
        return result
    return {
        "proposal_id": result["id"],
        "status": result["status"],
        "version": result["version"],
    }


def tool_list_proposals(
    *,
    token: str | None,
    status: str | None = None,
    category: str | None = None,
    proposed_by: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """MCP tool: list_proposals — paginated list with filters."""
    user = _resolve_user_from_bearer(token)
    if not _check_tool_rate_limit(token=getattr(user, "username", None), user_id=user.username):
        raise HTTPException(status_code=429, detail="rate_limit_exceeded")

    _require_permission(user, "CI_VIEW")

    return _service().list_proposals(
        status=status,
        category=category,
        proposed_by=proposed_by,
        page=page,
        page_size=page_size,
    )


def tool_approve_proposal(
    *,
    token: str | None,
    proposal_id: str,
    version: int,
    expected_category: str | None = None,
) -> dict[str, Any]:
    """MCP tool: approve_proposal — DRAFT -> APPROVED."""
    user = _resolve_user_from_bearer(token)
    if not _check_tool_rate_limit(token=getattr(user, "username", None), user_id=user.username):
        raise HTTPException(status_code=429, detail="rate_limit_exceeded")

    _require_permission(user, "CI_APPROVE_PROPOSAL")

    row = _service().approve_proposal(
        proposal_id=proposal_id,
        expected_version=version,
        user=user,
        db=None,
        expected_category=expected_category,
        request=None,
    )
    return {
        "proposal_id": row["id"],
        "status": row["status"],
        "version": row["version"],
        "resulted_ci_id": row.get("resulted_ci_id"),
    }


def tool_revoke_proposal(
    *,
    token: str | None,
    proposal_id: str,
    version: int,
    reason: str | None = None,
) -> dict[str, Any]:
    """MCP tool: revoke_proposal — DRAFT/APPROVED -> REVOKED."""
    user = _resolve_user_from_bearer(token)
    if not _check_tool_rate_limit(token=getattr(user, "username", None), user_id=user.username):
        raise HTTPException(status_code=429, detail="rate_limit_exceeded")

    _require_permission(user, "CI_APPROVE_PROPOSAL")

    row = _service().revoke_proposal(
        proposal_id=proposal_id,
        expected_version=version,
        user=user,
        reason=reason,
        db=None,
        request=None,
    )
    return {
        "proposal_id": row["id"],
        "status": row["status"],
        "version": row["version"],
    }


# ── MCP tool manifest ──────────────────────────────────────────────────────────


TOOL_REGISTRY = {
    "propose_ci": {
        "description": (
            "Submit a CI manifest for human approval. Requires AI_PROPOSE_CI permission."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "manifest": {
                    "type": "object",
                    "description": "The structured CI manifest (schema_version=1).",
                },
                "rationale": {"type": "string"},
                "source_refs": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["manifest"],
        },
        "handler": tool_propose_ci,
    },
    "list_proposals": {
        "description": "List proposals with filters. Requires CI_VIEW.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "category": {"type": "string"},
                "proposed_by": {"type": "string"},
                "page": {"type": "integer"},
                "page_size": {"type": "integer"},
            },
        },
        "handler": tool_list_proposals,
    },
    "approve_proposal": {
        "description": (
            "Approve a DRAFT proposal — commits the live :CI via node_service."
            " Requires CI_APPROVE_PROPOSAL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "version": {"type": "integer"},
                "expected_category": {"type": "string"},
            },
            "required": ["id", "version"],
        },
        "handler": tool_approve_proposal,
    },
    "revoke_proposal": {
        "description": "Revoke a DRAFT or APPROVED proposal. Requires CI_APPROVE_PROPOSAL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "version": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["id", "version"],
        },
        "handler": tool_revoke_proposal,
    },
}


__all__ = [
    "TOOL_REGISTRY",
    "tool_propose_ci",
    "tool_list_proposals",
    "tool_approve_proposal",
    "tool_revoke_proposal",
    "_check_tool_rate_limit",
    "_resolve_user_from_bearer",
    "_service",
]