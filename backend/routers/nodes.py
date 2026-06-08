from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Request
from sqlalchemy.orm import Session

from services.auth_service import check_permission, get_current_active_user
from models.user import User, UserPermission
from models.core import Node
import services.node_service as node_service
import services.metric_service as metric_service
from services.node_service import NodeMetadataUpdate, validate_ai_metadata_update

from postgres_db import get_pg_db
from services import audit_service

router = APIRouter(
    prefix="/nodes",
    tags=["Nodes"],
    responses={404: {"description": "Not found"}},
)

# Audit constants
AUDIT_TARGET_TYPE_CI = "ci"
AUDIT_SOURCE_NODES = "nodes"

AUDIT_OUTCOME_SUCCESS = "SUCCESS"
AUDIT_OUTCOME_VALIDATION_FAILURE = "VALIDATION_FAILURE"

AUDIT_EVENT_CI_CREATE_OR_UPDATE = "CI_CREATE_OR_UPDATE"
AUDIT_EVENT_CI_DELETE = "CI_DELETE"
AUDIT_EVENT_CI_UPDATE_METADATA = "CI_UPDATE_METADATA"

AUDIT_REASON_MISSING_PERMISSION = "missing_permission"
AUDIT_REASON_SERVICE_DENIED = "service_denied"
AUDIT_REASON_NOT_FOUND = "ci_not_found"
AUDIT_REASON_INVALID_PAYLOAD = "invalid_ci_payload"


def _record_ci_denied(db: Session, request: Request, actor: User, permission: str, target_id: str, reason: str | None):
    audit_service.record_denied(
        db=db,
        request=request,
        actor=actor,
        required_permission=permission,
        target_type=AUDIT_TARGET_TYPE_CI,
        target_id=target_id,
        reason=reason,
        source=AUDIT_SOURCE_NODES,
    )


def _record_ci_change(
    db: Session,
    request: Request,
    actor: User,
    event_type: str,
    outcome: str,
    target_id: str,
    target_label: str,
    reason: str,
    context: dict[str, Any] | None = None,
):
    audit_service.record_critical_change(
        db=db,
        request=request,
        actor=actor,
        event_type=event_type,
        outcome=outcome,
        target_type=AUDIT_TARGET_TYPE_CI,
        target_id=target_id,
        target_label=target_label,
        reason=reason,
        source=AUDIT_SOURCE_NODES,
        context=context,
    )


@router.get("", response_model=List[Dict[str, Any]])
async def get_nodes(current_user: User = Depends(get_current_active_user)):
    """
    Fetch all Configuration Items (CIs).
    Parses metadata and SNMP configurations for frontend consumption.
    Enforces Data Scoping based on User Permissions.
    """
    return node_service.get_nodes(current_user)


@router.post("")
async def create_node(
    request: Request,
    node: Node,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db),
):
    """
    Create or Update a Configuration Item (CI).
    Enforces CI_EDIT permission.
    """
    if not check_permission(UserPermission.CI_EDIT, current_user):
        _record_ci_denied(
            db=db,
            request=request,
            actor=current_user,
            permission=UserPermission.CI_EDIT,
            target_id=node.id,
            reason=AUDIT_REASON_MISSING_PERMISSION,
        )
        raise HTTPException(status_code=403, detail="Permission denied: CI_EDIT required")

    try:
        result = node_service.create_update_node(node, current_user)
    except HTTPException as exc:
        if exc.status_code == 403:
            _record_ci_denied(
                db=db,
                request=request,
                actor=current_user,
                permission=UserPermission.CI_EDIT,
                target_id=node.id,
                reason=AUDIT_REASON_SERVICE_DENIED,
            )
        else:
            _record_ci_change(
                db=db,
                request=request,
                actor=current_user,
                event_type=AUDIT_EVENT_CI_CREATE_OR_UPDATE,
                outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
                target_id=node.id,
                target_label=node.id,
                reason=AUDIT_REASON_INVALID_PAYLOAD,
                context={"required_permission": UserPermission.CI_EDIT.value},
            )
        raise

    _record_ci_change(
        db=db,
        request=request,
        actor=current_user,
        event_type=AUDIT_EVENT_CI_CREATE_OR_UPDATE,
        outcome=AUDIT_OUTCOME_SUCCESS,
        target_id=node.id,
        target_label=node.label,
        reason="ci_saved",
        context={"required_permission": UserPermission.CI_EDIT.value},
    )
    return result


@router.delete("/{node_id}")
async def delete_node(
    request: Request,
    node_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db),
):
    """
    Delete a Configuration Item (CI) by its ID.
    Enforces CI_DELETE permission.
    """
    if not check_permission(UserPermission.CI_DELETE, current_user):
        _record_ci_denied(
            db=db,
            request=request,
            actor=current_user,
            permission=UserPermission.CI_DELETE,
            target_id=node_id,
            reason=AUDIT_REASON_MISSING_PERMISSION,
        )
        raise HTTPException(status_code=403, detail="Permission denied: CI_DELETE required")

    try:
        result = node_service.delete_node(node_id, current_user)
    except HTTPException as exc:
        if exc.status_code == 403:
            _record_ci_denied(
                db=db,
                request=request,
                actor=current_user,
                permission=UserPermission.CI_DELETE,
                target_id=node_id,
                reason=AUDIT_REASON_SERVICE_DENIED,
            )
        else:
            _record_ci_change(
                db=db,
                request=request,
                actor=current_user,
                event_type=AUDIT_EVENT_CI_DELETE,
                outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
                target_id=node_id,
                target_label=node_id,
                reason=AUDIT_REASON_NOT_FOUND,
                context={"required_permission": UserPermission.CI_DELETE.value},
            )
        raise

    _record_ci_change(
        db=db,
        request=request,
        actor=current_user,
        event_type=AUDIT_EVENT_CI_DELETE,
        outcome=AUDIT_OUTCOME_SUCCESS,
        target_id=node_id,
        target_label=node_id,
        reason="ci_deleted",
        context={"required_permission": UserPermission.CI_DELETE.value},
    )
    return result


@router.get("/{node_id}/usage")
async def get_node_usage(node_id: str):
    """
    Check the usage of a CI (number of relationships).
    """
    return node_service.get_node_usage(node_id)


@router.put("/{node_id}/metadata")
async def update_ci_metadata(
    request: Request,
    node_id: str,
    metadata_update: NodeMetadataUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db),
):
    """
    AI-safe endpoint for updating CI metadata.
    Only allows updating: status, pollingInterval, owner, location_name, metadata.
    Regular users can update all fields; AI agents are restricted.
    """

    ai_info = None

    # Check if user is AI agent by examining their role
    if current_user.role and str(current_user.role).startswith("AI_"):
        # C3 fix: add proper guard flow — check_all_guards before operation
        from services.ai_guard_service import check_all_guards

        guard_result = check_all_guards(current_user.username, "ci_metadata_update", [node_id])
        if not guard_result.allowed:
            _record_ci_denied(
                db=db,
                request=request,
                actor=current_user,
                permission=UserPermission.CI_EDIT,
                target_id=node_id,
                reason=guard_result.reason,
            )
            raise HTTPException(status_code=403, detail=guard_result.reason)

        # AI agent — validate field restrictions
        update_data = metadata_update.dict(exclude_unset=True)
        is_valid, blocked = validate_ai_metadata_update(update_data)
        if not is_valid:
            _record_ci_change(
                db=db,
                request=request,
                actor=current_user,
                event_type=AUDIT_EVENT_CI_UPDATE_METADATA,
                outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
                target_id=node_id,
                target_label=node_id,
                reason=", ".join(blocked),
                context={
                    "changed_fields": list(update_data.keys()),
                    "required_permission": UserPermission.CI_EDIT.value,
                },
            )
            raise HTTPException(
                status_code=403,
                detail=f"AI agents cannot modify fields: {blocked}",
            )
        ai_info = current_user.username

    try:
        # Perform the update via node_service
        result = node_service.update_node_metadata(node_id, metadata_update)
    except HTTPException as exc:
        if exc.status_code == 400:
            _record_ci_change(
                db=db,
                request=request,
                actor=current_user,
                event_type=AUDIT_EVENT_CI_UPDATE_METADATA,
                outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
                target_id=node_id,
                target_label=node_id,
                reason=AUDIT_REASON_INVALID_PAYLOAD,
                context={
                    "changed_fields": list(metadata_update.dict(exclude_unset=True).keys()),
                    "required_permission": UserPermission.CI_EDIT.value,
                },
            )
        else:
            _record_ci_denied(
                db=db,
                request=request,
                actor=current_user,
                permission=UserPermission.CI_EDIT,
                target_id=node_id,
                reason=exc.detail,
            )
        raise

    _record_ci_change(
        db=db,
        request=request,
        actor=current_user,
        event_type=AUDIT_EVENT_CI_UPDATE_METADATA,
        outcome=AUDIT_OUTCOME_SUCCESS,
        target_id=node_id,
        target_label=node_id,
        reason="ci_metadata_updated",
        context={
            "changed_fields": list(metadata_update.dict(exclude_unset=True).keys()),
            "required_permission": UserPermission.CI_EDIT.value,
        },
    )

    # C3 fix: record operation for AI agents
    if ai_info is not None:
        from services.ai_guard_service import record_operation
        record_operation(
            ai_persona=str(current_user.role),
            ai_agent_id=current_user.username,
            operation="ci_metadata_update",
            target_type="ci",
            target_id=node_id,
            target_name=f"CI {node_id}",
            result="success",
        )

    return result


@router.post("/upload")
async def upload_nodes(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user)
):
    """
    Bulk upload Configuration Items (CIs) from an Excel file.
    Enforces CI_EDIT permission and a 5MB file size limit.
    """
    from services.auth_service import check_permission

    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Permission denied: CI_EDIT required")

    # DoS Protection: Limit file size to 5MB
    MAX_FILE_SIZE = 5 * 1024 * 1024
    size = 0
    contents = await file.read()
    size = len(contents)

    if size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Maximum size allowed is 5MB.")

    if not file.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="Invalid file format. Please upload an Excel file (.xlsx)")

    return await node_service.bulk_upload_nodes(contents, file.filename)


@router.get("/template")
async def get_node_template(current_user: User = Depends(get_current_active_user)):
    """
    Generates a pre-filled Excel template for bulk import.
    Requires CI_EDIT permission.
    """
    from services.auth_service import check_permission

    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Permission denied: CI_EDIT required")

    return node_service.get_node_template()


@router.get("/search", response_model=List[Dict[str, Any]])
async def search_nodes(q: str, current_user: User = Depends(get_current_active_user)):
    """
    Search Configuration Items (CIs) by text query.
    Returns matching nodes with id, label, ip, status, brand, model.
    Minimum query length: 2 characters.
    """
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query must be at least 2 characters")
    return node_service.search_nodes(current_user, q)


@router.get("/{node_id}/metrics")
async def get_node_metrics(node_id: str):
    """
    Get all applicable metrics for a specific Node based on its properties.
    """
    return metric_service.get_applicable_metrics(node_id)
