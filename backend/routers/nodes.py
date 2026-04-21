from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from typing import List, Dict, Any
from services.auth_service import get_current_active_user
from models.user import User
from models.core import Node
import services.node_service as node_service
import services.metric_service as metric_service
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(
    prefix="/api/nodes",
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

@router.get("/{node_id}/metrics")
async def get_node_metrics(node_id: str):
    """
    Get all applicable metrics for a specific Node based on its properties.
    """
    return metric_service.get_applicable_metrics(node_id)
