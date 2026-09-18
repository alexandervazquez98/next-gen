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

import csv
import io
import json
import logging
import os
import re
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


def _enforce_bulk_import_permission(user: User) -> None:
    """HTTP 403 when caller lacks CI_BULK_IMPORT (or is not Admin)."""
    if not _has_user_permission(UserPermission.CI_BULK_IMPORT, user):
        raise HTTPException(
            status_code=403,
            detail="missing_permission: CI_BULK_IMPORT required to bulk-import CIs",
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

    # feat-489 Slice 1B: bulk manifests must use ``bulk_import_proposals``
    # so the per-row validators (id uniqueness, secret rejection, CSV
    # injection guard, MIME check) get a chance to run. The legacy
    # single-CI create_proposal path is preserved exactly as-is for the
    # chat + MCP ``propose_ci`` tool — no behavioural drift on the hot
    # path.
    if payload.mode == "bulk" or payload.cis:
        raise HTTPException(
            status_code=422,
            detail={
                "reason": "bulk_manifest_requires_bulk_import",
                "hint": "POST /api/cmdb/proposals/bulk-import",
            },
        )

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


# ── bulk import (feat-489 Slice 1B) ─────────────────────────────────────


# feat-489: secret REJECTION (not redaction) for the CSV bulk path.
# Matches the deny-list used by ``redact_manifest_secrets`` in audit_service
# PLUS the hard-coded leaf names so a column like ``snmp.community`` is
# caught even when it lives under a non-secret-looking parent key.
_BULK_SECRET_COLUMN_DENYLIST = frozenset(
    {
        # leaf-name matches (the audit walker does this too)
        "community",
        "authkey",
        "privkey",
        # substring matches on key (case-insensitive) — mirrors
        # ``_SECRET_FIELD_PATTERN`` from audit_service so admin guidance
        # matches what gets redacted in MCP / chat paths.
        "key",
        "token",
        "secret",
        "password",
    }
)

# CSV-injection guard — a cell that starts with one of these chars is a
# classic Excel / Sheets / Numbers formula-injection vector if the CSV is
# later rendered in a spreadsheet. Reject at submit time.
_CSV_INJECTION_CHARS = ("=", "+", "-", "@")


def _secret_column_match(column_name: str) -> str | None:
    """Return the matched deny-list token if ``column_name`` looks like a
    secret column. Match is case-insensitive; checks both substring on the
    whole key and equality on the trailing leaf after the last ``.``.
    """
    if not column_name:
        return None
    lower = column_name.lower()
    leaf = lower.split(".")[-1]
    if leaf in _BULK_SECRET_COLUMN_DENYLIST:
        return leaf
    for token in _BULK_SECRET_COLUMN_DENYLIST:
        if token in lower:
            return token
    return None


def _csv_injection_risk(cell_value: str) -> bool:
    if not cell_value:
        return False
    first = cell_value[0]
    return first in _CSV_INJECTION_CHARS


_BULK_MAX_BYTES = int(os.getenv("CMDB_PROPOSAL_BULK_MAX_BYTES", str(5 * 1024 * 1024)))
_BULK_MAX_ROWS = int(os.getenv("CMDB_PROPOSAL_BULK_MAX_ROWS", "1000"))


def _looks_like_csv(file_bytes: bytes) -> bool:
    """Cheap magic-byte sniff — real CSV starts with printable ASCII (or
    a UTF-8 BOM ``\\xef\\xbb\\xbf``). Reject anything else (PE binary,
    Office OOXML, etc.) regardless of the client-supplied Content-Type."""
    if not file_bytes:
        return False
    # Strip BOM if present.
    sample = file_bytes[:4096]
    if sample.startswith(b"\xef\xbb\xbf"):
        sample = sample[3:]
    if not sample:
        return False
    try:
        text = sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    # Reject if any non-printable / non-CSV control char appears.
    for ch in text:
        if ch in ("\n", "\r", "\t"):
            continue
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            return False
    return True


def bulk_import_proposals(
    *,
    file_bytes: bytes,
    default_category: str | None,
    default_owner: str | None,
    user: User,
    db: Any,
    request: Any | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """feat-489 Slice 1B: parse a CSV, validate every row, persist ONE
    bulk proposal covering every CI. The HITL review at
    ``/#/proposals/cmdb?id=<id>`` stays the only place where CIs land in
    the active CMDB.

    Validation chain (each is its own line in the response ``errors[]``
    when it fires so the operator can fix the file):

    1. **File-level**: byte cap (default 5 MB), CSV magic-byte sniff,
       row cap (default 1000).
    2. **Per-row schema**: ``id``, ``label``, ``category`` (or
       ``default_category``) present and non-empty.
    3. **Idempotency**: ``id`` unique across the file AND not colliding
       with existing ``:CI`` nodes.
    4. **Category drift**: each ``category`` (or ``default_category``)
       must exist live at submit time.
    5. **CSV-injection guard**: cells in ``id`` / ``label`` / ``category``
       starting with ``=`` / ``+`` / ``-`` / ``@`` are rejected.
    6. **Secret REJECTION** (not redaction): columns matching
       ``*key|*token|*secret|*password|*community|*authkey|*privkey``
       cause the whole row to be rejected with a hint pointing at
       ``snmp_community_ref`` / ``secret://...``.

    Atomicity: any single row's failure means the WHOLE file is
    rejected with HTTP 422 listing every offending row. No partial
    success — the operator fixes the CSV and resubmits.

    ``dry_run=True`` runs all validators up to (but not including) the
    repo write + audit row + op log + guard counter increment, so the
    admin UI can preview before committing.
    """
    _enforce_bulk_import_permission(user)

    # ── File-level guards ────────────────────────────────────────────────────
    if len(file_bytes) > _BULK_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "reason": "file_too_large",
                "bytes": len(file_bytes),
                "max_bytes": _BULK_MAX_BYTES,
            },
        )

    if not _looks_like_csv(file_bytes):
        raise HTTPException(
            status_code=415,
            detail={
                "reason": "not_a_csv",
                "hint": "file must be a UTF-8 CSV (optionally with BOM); rejected at magic-byte sniff",
            },
        )

    # ── CSV parse ────────────────────────────────────────────────────────────
    try:
        text = file_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise HTTPException(
            status_code=422,
            detail={"reason": "csv_parse_failed", "error": str(exc)},
        ) from exc

    if not rows:
        raise HTTPException(
            status_code=422, detail={"reason": "empty_csv", "hint": "CSV has no data rows"}
        )

    if len(rows) > _BULK_MAX_ROWS:
        raise HTTPException(
            status_code=413,
            detail={
                "reason": "too_many_rows",
                "rows": len(rows),
                "max_rows": _BULK_MAX_ROWS,
            },
        )

    # ── Per-row validation ───────────────────────────────────────────────────
    errors: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    categories_live = _resolve_category(None) or []
    categories_set = set(categories_live)
    nodes: list[Node] = []
    proposed_categories: list[str] = []

    for idx, raw in enumerate(rows, start=2):  # start=2 to match CSV row numbers (header=1)
        row_errors: list[str] = []

        ci_id = (raw.get("id") or "").strip()
        label = (raw.get("label") or "").strip()
        category = (raw.get("category") or "").strip() or (default_category or "").strip()
        owner = (raw.get("owner") or "").strip() or (default_owner or "").strip()
        brand = (raw.get("brand") or "").strip() or None
        model = (raw.get("model") or "").strip() or None
        serial = (raw.get("serialNumber") or "").strip() or None
        firmware = (raw.get("firmwareVersion") or "").strip() or None
        ip = (raw.get("ip") or "").strip() or None
        location_name = (raw.get("location_name") or "").strip() or None
        status_val = (raw.get("status") or "").strip() or "OK"

        if not ci_id:
            row_errors.append("missing id")
        if not label:
            row_errors.append("missing label")
        if not category:
            row_errors.append(
                "missing category (column empty and no default_category provided)"
            )

        # CSV-injection guard.
        for field_name, value in (
            ("id", ci_id),
            ("label", label),
            ("category", category),
        ):
            if value and _csv_injection_risk(value):
                row_errors.append(
                    f"{field_name} starts with '{value[0]}' (CSV-injection risk)"
                )

        # Secret REJECTION (not redaction). Any column that looks like a
        # secret is rejected with a hint pointing at the secret:// form.
        secret_match_column: str | None = None
        secret_match_token: str | None = None
        for col_name, col_value in raw.items():
            if col_value is None or col_value == "":
                continue
            token = _secret_column_match(col_name)
            if token:
                secret_match_column = col_name
                secret_match_token = token
                break
        if secret_match_column:
            row_errors.append(
                f"column '{secret_match_column}' matches secret deny-list "
                f"('{secret_match_token}'); use '<field>_ref' with a secret:// URL instead"
            )

        # Idempotency — duplicate within file.
        if ci_id and ci_id in seen_ids:
            row_errors.append(f"duplicate id '{ci_id}' inside the file")
        # Idempotency — collision with existing :CI.
        if ci_id and not any(e.startswith("duplicate") for e in row_errors):
            if _ci_id_exists(ci_id):
                row_errors.append(f"id '{ci_id}' collides with an existing :CI")

        # Category drift.
        if category and category not in categories_set:
            row_errors.append(f"category '{category}' does not exist (live :Category required)")

        if row_errors:
            errors.append({"row": idx, "errors": row_errors})
            continue

        seen_ids.add(ci_id)
        proposed_categories.append(category)

        # Build the Node-shaped CI. Snmp lives under ``metadata.snmp`` so
        # it doesn't collide with the top-level CI fields; the audit
        # walker redacts any plain-text community that slips through.
        metadata: dict[str, Any] = {}
        if owner:
            metadata["owner"] = owner
        if location_name:
            metadata["location_name"] = location_name
        if raw.get("metadata_json"):
            try:
                extra = json.loads(raw["metadata_json"])
                if isinstance(extra, dict):
                    metadata.update(extra)
            except json.JSONDecodeError:
                row_errors.append("metadata_json is not valid JSON")

        # Re-check after metadata_json parse — the same row may have failed
        # for multiple reasons.
        if row_errors:
            errors.append({"row": idx, "errors": row_errors})
            continue

        try:
            node = Node(
                id=ci_id,
                type=category,
                label=label,
                brand=brand,
                model=model,
                serialNumber=serial,
                firmwareVersion=firmware,
                ip=ip,
                metadata=metadata or None,
            )
        except Exception as exc:
            errors.append({"row": idx, "errors": [f"node validation failed: {exc}"]})
            continue

        nodes.append(node)

    if errors:
        # Atomicity: NO partial success. All errors collected, file rejected.
        raise HTTPException(
            status_code=422,
            detail={"reason": "bulk_validation_failed", "errors": errors},
        )

    # ── Manifest build + persistence ─────────────────────────────────────────
    manifest_dict: dict[str, Any] = {
        "schema_version": 1,
        "cis": [n.model_dump(mode="json", exclude_none=True) for n in nodes],
        "mode": "bulk",
        "rationale": f"Bulk CSV import: {len(nodes)} CI(s) by {user.username}",
        "source_refs": [f"csv:upload:{user.username}"],
    }
    manifest_json = json.dumps(manifest_dict, default=str)

    # Validate via the schema one more time so the operator sees the
    # Pydantic error if anything slipped past the per-row checks.
    from models.cmdb_proposal import ManifestPayload

    try:
        payload = ManifestPayload.model_validate(manifest_dict)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail={"reason": "invalid_manifest", "errors": str(exc)}
        ) from exc

    # Guard gate — one propose_ci tick regardless of cis.length.
    guard = _get_guard()
    guard_target = "ci_proposal:bulk"
    guard_result = guard.check_all_guards(
        user.username, "propose_ci", [guard_target]
    )
    if not guard_result.allowed:
        try:
            guard.record_operation(
                ai_persona=user.role or "OPERATOR",
                ai_agent_id=user.username,
                operation="propose_ci",
                target_type="ci_proposal",
                target_id=guard_target,
                target_name=f"bulk:{len(nodes)}",
                result="blocked",
                blocked_reason=getattr(guard_result, "reason", None),
            )
        except Exception:
            logger.exception("Failed to record AIOperationLog for bulk propose_ci block")
        return {
            "harness_result": {
                "denied": True,
                "status": "denied",
                "reason": getattr(guard_result, "reason", "") or "",
                "reason_code": (
                    "bulk_threshold"
                    if "bulk" in (getattr(guard_result, "reason", "") or "").lower()
                    else "cooldown_active"
                ),
            }
        }

    if dry_run:
        # Return the parsed manifest + counts so the UI can preview
        # without writing to the graph or incrementing guards.
        return {
            "dry_run": True,
            "cis_count": len(nodes),
            "categories": sorted(set(proposed_categories)),
            "manifest": manifest_dict,
        }

    # Persist the draft.
    proposal_id = str(uuid.uuid4())
    repo = _get_repo()
    primary_category = proposed_categories[0] if proposed_categories else None
    primary_ci_id = nodes[0].id if nodes else None
    row = repo.create_draft(
        proposal_id=proposal_id,
        manifest_json=manifest_json,
        proposed_by=user.username,
        proposed_role=user.role or "OPERATOR",
        proposed_category=primary_category,
        ci_id=primary_ci_id,
        manifest_mode="bulk",
        ci_count=len(nodes),
    )

    # Audit + op log.
    redacted_summary = redact_manifest_secrets(manifest_dict)
    context = _audit_context(
        proposal_id=proposal_id,
        proposed_by=user.username,
        actor_role=user.role or "OPERATOR",
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
        reason="proposal_created_bulk_csv",
        context=context,
    )

    try:
        guard.record_operation(
            ai_persona=user.role or "OPERATOR",
            ai_agent_id=user.username,
            operation="propose_ci",
            target_type="ci_proposal",
            target_id=proposal_id,
            target_name=f"bulk:{len(nodes)}",
            result="success",
        )
    except Exception:
        logger.exception("Failed to record AIOperationLog for bulk propose_ci success")

    return {
        "proposal_id": proposal_id,
        "status": row.get("status", "DRAFT"),
        "version": row.get("version", 1),
        "cis_count": len(nodes),
        "manifest_mode": "bulk",
        "created_at": row.get("created_at"),
    }


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
    # feat-489 Slice 1B: dispatch on manifest_mode. Legacy rows without
    # ``manifest_mode`` default to ``"single"`` (see migration 006).
    manifest_mode = manifest_obj.get("mode") or proposal.get("manifest_mode") or "single"
    if manifest_mode == "bulk":
        cis_raw = manifest_obj.get("cis") or []
        if not cis_raw:
            raise HTTPException(
                status_code=409,
                detail={"reason": "empty_bulk_manifest", "ci_count": 0},
            )
        cis: list[Node] = [Node.model_validate(entry) for entry in cis_raw]

        # Bulk-mode does not accept a single expected_category (the operator
        # would have to pick one). Reject if the caller supplies one for a
        # bulk proposal so the audit trail stays honest.
        if expected_category is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": "expected_category_not_supported_for_bulk",
                    "expected": expected_category,
                },
            )

        # Category drift + collision check for every CI in cis[].
        all_categories = _resolve_category(None) or []
        collision_ids: list[str] = []
        renamed_cis: list[str] = []
        for entry in cis:
            if entry.type not in all_categories:
                renamed_cis.append(entry.type)
                continue
            if _ci_id_exists(entry.id):
                collision_ids.append(entry.id)
        if renamed_cis:
            raise HTTPException(
                status_code=409,
                detail={"reason": "category_renamed", "categories": renamed_cis},
            )
        if collision_ids:
            raise HTTPException(
                status_code=409,
                detail={"reason": "ci_id_collision", "ci_ids": collision_ids},
            )

        # Commit every CI in cis[].
        commit_errors: list[dict[str, Any]] = []
        for entry in cis:
            try:
                node_service.create_update_node(entry, user)
            except HTTPException as exc:
                commit_errors.append({"ci_id": entry.id, "detail": exc.detail})
            except Exception as exc:
                logger.exception(
                    "node_service.create_update_node failed for bulk ci %s in proposal %s",
                    entry.id,
                    proposal_id,
                )
                commit_errors.append(
                    {"ci_id": entry.id, "detail": {"reason": "ci_commit_failed", "error": str(exc)}}
                )
        if commit_errors:
            raise HTTPException(
                status_code=500,
                detail={"reason": "ci_commit_failed", "errors": commit_errors},
            )

        applied_manifest_json = json.dumps(manifest_obj, default=str)
        # For bulk we record the FIRST CI's id in the legacy resulted_ci_id
        # column so existing audit reads stay consistent; reviewers should
        # read the manifest_json / applied_manifest_json for the full list.
        primary_ci_id = cis[0].id

        try:
            row = repo.approve(
                proposal_id=proposal_id,
                expected_version=expected_version,
                reviewer_by=user.username,
                applied_manifest_json=applied_manifest_json,
                resulted_ci_id=primary_ci_id,
            )
        except Exception as exc:
            from repositories.cmdb_proposal_repo import CmdbProposalVersionConflictError

            if isinstance(exc, CmdbProposalVersionConflictError):
                raise HTTPException(
                    status_code=409,
                    detail={"reason": "version_conflict", "proposal_id": proposal_id},
                ) from exc
            raise

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
            resulted_ci_id=primary_ci_id,
        )
        _record(
            db=db,
            request=request,
            actor=user,
            event_type=AUDIT_EVENT_APPROVE,
            outcome=OUTCOME_SUCCESS,
            target_id=proposal_id,
            reason="proposal_approved_bulk",
            context=context,
        )

        return row

    # Single-mode (legacy path).
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
