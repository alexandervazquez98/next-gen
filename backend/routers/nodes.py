from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from typing import List, Dict, Any
from services.auth_service import get_current_active_user, get_current_ai_agent
from models.user import User
from models.core import Node
import services.node_service as node_service
import services.metric_service as metric_service
from services.node_service import validate_ai_metadata_update, NodeMetadataUpdate
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(
    prefix="/nodes",
    tags=["Nodes"],
    responses={404: {"description": "Not found"}},
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
async def create_node(node: Node, current_user: User = Depends(get_current_active_user)):
    """
    Create or Update a Configuration Item (CI).
    Enforces CI_EDIT permission.
    """
    return node_service.create_update_node(node, current_user)

@router.delete("/{node_id}")
async def delete_node(node_id: str, current_user: User = Depends(get_current_active_user)):
    """
    Delete a Configuration Item (CI) by its ID.
    Enforces CI_DELETE permission.
    """
    return node_service.delete_node(node_id, current_user)

@router.get("/{node_id}/usage")
async def get_node_usage(node_id: str):
    """
    Check the usage of a CI (number of relationships).
    """
    return node_service.get_node_usage(node_id)


@router.put("/{node_id}/metadata")
async def update_ci_metadata(
    node_id: str,
    metadata_update: NodeMetadataUpdate,
    current_user: User = Depends(get_current_active_user),
):
    """
    AI-safe endpoint for updating CI metadata.
    Only allows updating: status, pollingInterval, owner, location_name, metadata.
    Regular users can update all fields; AI agents are restricted.
    """
    from services.auth_service import AIAgentInfo

    ai_info = None

    # Check if user is AI agent by examining their role
    if current_user.role and str(current_user.role).startswith("AI_"):
        # C3 fix: add proper guard flow — check_all_guards before operation
        from services.ai_guard_service import check_all_guards
        guard_result = check_all_guards(current_user.username, "ci_metadata_update", [node_id])
        if not guard_result.allowed:
            raise HTTPException(status_code=403, detail=guard_result.reason)

        # AI agent — validate field restrictions
        update_data = metadata_update.dict(exclude_unset=True)
        is_valid, blocked = validate_ai_metadata_update(update_data)
        if not is_valid:
            raise HTTPException(
                status_code=403,
                detail=f"AI agents cannot modify fields: {blocked}",
            )
        ai_info = current_user.username

    # Perform the update via node_service
    result = node_service.update_node_metadata(node_id, metadata_update)

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
    from models.user import UserPermission

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
    from models.user import UserPermission

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
