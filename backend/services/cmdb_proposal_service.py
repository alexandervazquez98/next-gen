"""Service layer for CMDB AI proposal lifecycle — feat-cmdb-ai-handoff.

Public surface:
- create_proposal(manifest, user, ai_agent_id, db, request=None) -> dict
- approve_proposal(proposal_id, expected_version, user, db, expected_category=None, request=None) -> dict
- revoke_proposal(proposal_id, expected_version, user, reason=None, db, request=None) -> dict
- list_proposals(...) -> dict with rows + total
- get_proposal(proposal_id) -> dict | None

Layered guards (REQ-CMAP-011 / REQ-AICHG-005):
1. Permission (HTTP 403): missing -> deny immediately, audit ACCESS_DENIED.
2. AI guard (HTTP 200 with harness_result.denied=true): record_operation, no :CIProposal write.

The CI commit path is delegated to the existing ``node_service.create_update_node()`` —
this module never modifies that function (REQ-CMAP-006, design.md §Approach).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import HTTPException
from models.core import Node
from models.user import AIPermission, User, UserPermission, UserRole
from services import audit_service, node_service
from services.audit_service import redact_manifest_secrets

logger = logging.getLogger(__name__)


# ── audit event names / outcomes (REQ-AUDIT-001) ────────────────────────────────

AUDIT_EVENT_CREATE = "CI_PROPOSAL_CREATE"
AUDIT_EVENT_APPROVE = "CI_PROPOSAL_APPROVE"
AUDIT_EVENT_REVOKE = "CI_PROPOSAL_REVOKE"

AUDIT_TARGET_TYPE = "ci_proposal"
AUDIT_SOURCE = "cmdb_proposals"

OUTCOME_SUCCESS = "SUCCESS"
OUTCOME_VALIDATION_FAILURE = "VALIDATION_FAILURE"

# actor_role for system-driven TTL sweep
ACTOR_ROLE_SYSTEM = "SYSTEM"

# ── tiny dependency seams (overridden by tests via monkeypatch) ────────────────


def _get_repo():
    """Default repo factory; tests monkeypatch this."""
    from repositories.cmdb_proposal_repo import get_cmdb_proposal_repo

    return get_cmdb_proposal_repo()


def _get_guard():
    """Default ai_guard_service module."""
    import services.ai_guard_service as guard

    return guard


def _resolve_category(category: str | None) -> list[str] | None:
    """Return live Category names from Neo4j. None on failure."""
    if not category:
        return None
    try:
        import services.catalog_service as catalog

        names = [c["name"] for c in catalog.get_categories()]
        return names
    except Exception:
        logger.warning("Could not resolve categories; assuming offline mode.")
        return None


def _ci_id_exists(ci_id: str | None) -> bool:
    """Return True if :CI {id: ci_id} already exists (collision check)."""
    if not ci_id:
        return False
    try:
        from repositories import topology_repo

        nodes = topology_repo.get_nodes(allowed_locations=None, is_admin=True)
        return any(n.get("id") == ci_id for n in nodes)
    except Exception:
        # Conservative: when we cannot confirm absence, treat as collision-free
        # so the proposal can be queued; approve-time check covers the race.
        return False


# ── permission helpers ────────────────────────────────────────────────────────


def _has_user_permission(permission: UserPermission, user: User) -> bool:
    """Check UserPermission membership (reuses auth_service.check_permission pattern)."""
    if user.role == UserRole.ADMIN.value or user.role == "ADMIN":
        return True
    return permission.value in (user.permissions or [])


def _has_ai_permission(permission: AIPermission, user: User) -> bool:
    """Check AIPermission membership; Admin also allowed for break-glass."""
    if user.role == UserRole.ADMIN.value or user.role == "ADMIN":
        return True
    return permission.value in (user.permissions or [])


def _enforce_create_permission(user: User) -> None:
    """HTTP 403 when caller lacks AI_PROPOSE_CI (or is not Admin)."""
    if not _has_ai_permission(AIPermission.AI_PROPOSE_CI, user):
        raise HTTPException(
            status_code=403,
            detail="missing_permission: AI_PROPOSE_CI required to propose a CI",
        )


def _enforce_approve_permission(user: User) -> None:
    """HTTP 403 when caller lacks CI_APPROVE_PROPOSAL (or is not Admin)."""
    if not _has_user_permission(UserPermission.CI_APPROVE_PROPOSAL, user):
        raise HTTPException(
            status_code=403,
            detail="missing_permission: CI_APPROVE_PROPOSAL required",
        )


# ── audit context builders (REQ-AUDIT-001/002/003) ───────────────────────────


def _audit_context(
    *,
    proposal_id: str,
    proposed_by: str | None,
    actor_role: str,
    previous_state: str | None,
    next_state: str,
    version: int,
    applied_manifest_summary: dict | None = None,
    applied_manifest_attributes: dict | None = None,
    resulted_ci_id: str | None = None,
    revoke_reason: str | None = None,
    manifest_diff: dict | None = None,
) -> dict[str, Any]:
    return {
        "proposal_id": proposal_id,
        "proposed_by": proposed_by,
        "actor_role": actor_role,
        "previous_state": previous_state,
        "next_state": next_state,
        "version": version,
        "applied_manifest_summary": applied_manifest_summary,
        "applied_manifest_attributes": applied_manifest_attributes,
        "resulted_ci_id": resulted_ci_id,
        "revoke_reason": revoke_reason,
        "manifest_diff": manifest_diff,
    }


def _record(
    db: Any,
    request: Any | None,
    actor: User | None,
    event_type: str,
    outcome: str,
    target_id: str,
    reason: str,
    context: dict[str, Any],
) -> None:
    audit_service.record_critical_change(
        db=db,
        request=request,
        actor=actor,
        event_type=event_type,
        outcome=outcome,
        target_type=AUDIT_TARGET_TYPE,
        target_id=target_id,
        target_label=target_id,
        reason=reason,
        source=AUDIT_SOURCE,
        context=context,
    )


# ── public API ────────────────────────────────────────────────────────────────


def create_proposal(
    *,
    manifest: dict[str, Any],
    user: User,
    ai_agent_id: str,
    db: Any,
    request: Any | None = None,
) -> dict[str, Any]:
    """Submit a CI manifest as an AI agent or human with CI_EDIT+.

    Permission gate -> guard gate -> category resolve -> CI id collision ->
    repo.create_draft -> audit CI_PROPOSAL_CREATE.

    Returns the created proposal row. On guardrail denial, returns the
    conversationally-stable shape ``{harness_result: {denied: true, ...}}``
    instead of a proposal.
    """
    _enforce_create_permission(user)

    # ── 1. Manifest schema validation (REQ-CMAP-001) ─────────────────────────
    from models.cmdb_proposal import ManifestPayload

    try:
        payload = ManifestPayload.model_validate(manifest)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail={"reason": "invalid_manifest", "errors": str(exc)}
        ) from exc

    ci = payload.ci

    # ── 2. Category resolve (REQ-CMAP-002) ───────────────────────────────────
    category_names = _resolve_category(ci.type)
    if category_names is None or ci.type not in category_names:
        raise HTTPException(
            status_code=422,
            detail={"reason": "unknown_category", "category": ci.type},
        )

    # ── 3. CI id collision check (REQ-CMAP-009) ──────────────────────────────
    if _ci_id_exists(ci.id):
        raise HTTPException(
            status_code=409,
            detail={"reason": "ci_id_collision", "ci_id": ci.id},
        )

    # ── 4. Guardrail gate (REQ-AICHG-003 / REQ-CMAP-010/011) ────────────────
    guard = _get_guard()
    guard_target = "ci_proposal:new"
    guard_result = guard.check_all_guards(
        ai_agent_id,
        "propose_ci",
        [guard_target],
    )
    if not guard_result.allowed:
        # Persist a blocked AIOperationLog and return harness_result denial.
        try:
            guard.record_operation(
                ai_persona=user.role or "AI_OPERATOR",
                ai_agent_id=ai_agent_id,
                operation="propose_ci",
                target_type="ci_proposal",
                target_id=guard_target,
                target_name=ci.id,
                result="blocked",
                blocked_reason=getattr(guard_result, "reason", None),
            )
        except Exception:
            logger.exception("Failed to record AIOperationLog for propose_ci block")

        reason_code = "cooldown_active"
        reason_text = getattr(guard_result, "reason", "") or ""
        if "bulk" in reason_text.lower():
            reason_code = "bulk_threshold"

        return {
            "harness_result": {
                "denied": True,
                "status": "denied",
                "reason": reason_text,
                "reason_code": reason_code,
            }
        }

    # ── 5. Repo write (REQ-CMAP-003) ────────────────────────────────────────
    proposal_id = str(uuid.uuid4())
    manifest_json = json.dumps(payload.model_dump(mode="json"), default=str)
    repo = _get_repo()
    row = repo.create_draft(
        proposal_id=proposal_id,
        manifest_json=manifest_json,
        proposed_by=user.username,
        proposed_role=user.role or "AI_OPERATOR",
        proposed_category=ci.type,
        ci_id=ci.id,
    )

    # ── 6. Audit row (REQ-AUDIT-001/003) ────────────────────────────────────
    redacted_summary = redact_manifest_secrets(payload.model_dump(mode="json"))
    context = _audit_context(
        proposal_id=proposal_id,
        proposed_by=user.username,
        actor_role=user.role or "AI_OPERATOR",
        previous_state=None,
        next_state="DRAFT",
        version=1,
        applied_manifest_summary=redacted_summary,
    )
    _record(
        db=db,
        request=request,
        actor=user,
        event_type=AUDIT_EVENT_CREATE,
        outcome=OUTCOME_SUCCESS,
        target_id=proposal_id,
        reason="proposal_created",
        context=context,
    )

    # ── 7. Operation log ────────────────────────────────────────────────────
    try:
        guard.record_operation(
            ai_persona=user.role or "AI_OPERATOR",
            ai_agent_id=ai_agent_id,
            operation="propose_ci",
            target_type="ci_proposal",
            target_id=proposal_id,
            target_name=ci.id,
            result="success",
        )
    except Exception:
        logger.exception("Failed to record AIOperationLog for propose_ci success")

    return row


def approve_proposal(
    *,
    proposal_id: str,
    expected_version: int,
    user: User,
    db: Any,
    expected_category: str | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """Transition DRAFT -> APPROVED; commit the live :CI via node_service."""
    _enforce_approve_permission(user)

    repo = _get_repo()
    proposal = repo.get(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail={"reason": "proposal_not_found"})

    if proposal["status"] != "DRAFT":
        raise HTTPException(
            status_code=409,
            detail={"reason": "invalid_state", "current_state": proposal["status"]},
        )

    # Re-resolve category (REQ-CMAP-002 scenario 2)
    manifest_obj = json.loads(proposal["manifest_json"])
    ci_dict = manifest_obj["ci"]
    ci = Node.model_validate(ci_dict)
    if expected_category is not None and ci.type != expected_category:
        raise HTTPException(
            status_code=409,
            detail={"reason": "category_renamed", "expected": expected_category, "got": ci.type},
        )
    category_names = _resolve_category(ci.type)
    if category_names is None or ci.type not in category_names:
        raise HTTPException(
            status_code=409,
            detail={"reason": "category_renamed", "category": ci.type},
        )

    # Re-check CI id collision at approve time (REQ-CMAP-009 race)
    if _ci_id_exists(ci.id):
        raise HTTPException(
            status_code=409,
            detail={"reason": "ci_id_collision", "ci_id": ci.id},
        )

    # Delegate to node_service.create_update_node (REQ-CMAP-006 scenario 1)
    try:
        node_service.create_update_node(ci, user)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("node_service.create_update_node failed for proposal %s", proposal_id)
        raise HTTPException(
            status_code=500, detail={"reason": "ci_commit_failed", "error": str(exc)}
        ) from exc

    # Repo transition (optimistic version)
    applied_manifest_json = json.dumps(manifest_obj, default=str)
    try:
        row = repo.approve(
            proposal_id=proposal_id,
            expected_version=expected_version,
            reviewer_by=user.username,
            applied_manifest_json=applied_manifest_json,
            resulted_ci_id=ci.id,
        )
    except Exception as exc:
        # Optimistic-version conflict or repo error
        from repositories.cmdb_proposal_repo import CmdbProposalVersionConflictError

        if isinstance(exc, CmdbProposalVersionConflictError):
            raise HTTPException(
                status_code=409,
                detail={"reason": "version_conflict", "proposal_id": proposal_id},
            ) from exc
        raise

    # Audit row (REQ-AUDIT-001/002)
    redacted_summary = redact_manifest_secrets(manifest_obj)
    context = _audit_context(
        proposal_id=proposal_id,
        proposed_by=proposal.get("proposed_by"),
        actor_role=user.role or "OPERATOR",
        previous_state="DRAFT",
        next_state="APPROVED",
        version=row["version"],
        applied_manifest_summary=redacted_summary,
        applied_manifest_attributes=redacted_summary,
        resulted_ci_id=ci.id,
    )
    _record(
        db=db,
        request=request,
        actor=user,
        event_type=AUDIT_EVENT_APPROVE,
        outcome=OUTCOME_SUCCESS,
        target_id=proposal_id,
        reason="proposal_approved",
        context=context,
    )

    return row


def revoke_proposal(
    *,
    proposal_id: str,
    expected_version: int,
    user: User,
    reason: str | None = None,
    db: Any,
    request: Any | None = None,
    actor_role: str | None = None,
) -> dict[str, Any]:
    """Transition DRAFT or APPROVED -> REVOKED.

    When revoking from APPROVED, the live :CI is PRESERVED (REQ-CMAP-007 scenario 2).
    """
    if actor_role is None:
        # System TTL sweep callers can pass actor_role="SYSTEM".
        _enforce_approve_permission(user)
        actor_role = user.role or "OPERATOR"
    else:
        # SYSTEM-driven revokes skip the human-permission gate.
        if actor_role != ACTOR_ROLE_SYSTEM:
            _enforce_approve_permission(user)
            actor_role = user.role or "OPERATOR"

    repo = _get_repo()
    proposal = repo.get(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail={"reason": "proposal_not_found"})

    if proposal["status"] not in ("DRAFT", "APPROVED"):
        raise HTTPException(
            status_code=409,
            detail={"reason": "invalid_state", "current_state": proposal["status"]},
        )

    previous_state = proposal["status"]
    try:
        row = repo.revoke(
            proposal_id=proposal_id,
            expected_version=expected_version,
            reviewer_by=actor_role,
            reason=reason,
        )
    except Exception as exc:
        from repositories.cmdb_proposal_repo import CmdbProposalVersionConflictError

        if isinstance(exc, CmdbProposalVersionConflictError):
            raise HTTPException(
                status_code=409,
                detail={"reason": "version_conflict", "proposal_id": proposal_id},
            ) from exc
        raise

    # Audit row
    context = _audit_context(
        proposal_id=proposal_id,
        proposed_by=proposal.get("proposed_by"),
        actor_role=actor_role,
        previous_state=previous_state,
        next_state="REVOKED",
        version=row["version"],
        revoke_reason=reason,
        manifest_diff=None,
    )
    _record(
        db=db,
        request=request,
        actor=user,
        event_type=AUDIT_EVENT_REVOKE,
        outcome=OUTCOME_SUCCESS,
        target_id=proposal_id,
        reason="proposal_revoked",
        context=context,
    )

    return row


def list_proposals(
    *,
    status: str | None = None,
    category: str | None = None,
    proposed_by: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Return paginated proposals (no permission gate — caller's router enforces CI_VIEW)."""
    repo = _get_repo()
    rows = repo.list(
        status=status,
        category=category,
        proposed_by=proposed_by,
        created_from=created_from,
        created_to=created_to,
        page=page,
        page_size=page_size,
    )
    return {
        "rows": rows,
        "total": len(rows),
        "page": page,
        "page_size": page_size,
    }


def get_proposal(proposal_id: str) -> dict[str, Any] | None:
    """Read-only accessor."""
    return _get_repo().get(proposal_id)
