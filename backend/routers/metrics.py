from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any, Optional
from models.core import MetricDef, Node
from pydantic import BaseModel
import services.metric_service as metric_service
from services.snmp_service import validate_snmp_oid
from services.auth_service import get_current_active_user, check_permission
from models.user import User, UserPermission
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from postgres_db import get_pg_db
from repositories import metric_repo

router = APIRouter(
    prefix="/api/metrics",
    tags=["Metrics"],
    responses={404: {"description": "Not found"}},
)


class MetricPromotion(BaseModel):
    ci_id: str
    metric_name: str
    display_name: Optional[str] = None


class SNMPTestRequest(BaseModel):
    ip: str
    community: str
    oid: str
    port: int = 161


@router.get("", response_model=List[Dict[str, Any]])
async def get_metrics():
    """
    Fetch all Metric Definitions.
    Includes details like OID, thresholds, unit, and applicable criteria.
    """
    return metric_service.get_metrics()


@router.post("")
async def create_metric(
    metric: MetricDef,
    current_user: User = Depends(get_current_active_user),
):
    """
    Define a new Metric for monitoring.
    Requires authentication and CI_EDIT permission.
    """
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to create metrics")
    return metric_service.create_metric(metric)


@router.delete("/{metric_id}")
async def delete_metric(
    metric_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Delete a Metric Definition. Requires authentication and CI_EDIT permission."""
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to delete metrics")
    return metric_service.delete_metric(metric_id)


@router.get("/{metric_id}/usage")
async def get_metric_usage(metric_id: str):
    """
    Analyze how many CIs currently match this metric's criteria.
    """
    return metric_service.get_metric_usage(metric_id)


@router.post("/promote")
async def promote_metric_node(
    data: MetricPromotion,
    current_user: User = Depends(get_current_active_user),
):
    """
    Promote a specific metric property of a CI to a first-class Graph Node.
    Requires authentication and CI_EDIT permission.
    """
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to promote metrics")
    return metric_service.promote_metric_node(
        data.ci_id, data.metric_name, data.display_name
    )


@router.post("/validate")
async def validate_oid_endpoint(
    req: SNMPTestRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Validate an OID against a target agent via SNMP. Requires authentication."""
    result = validate_snmp_oid(req.ip, req.community, req.oid, req.port)
    return result


@router.get("/{node_id}/{metric_id}/history")
async def get_metric_history(
    node_id: str,
    metric_id: str,
    hours: int = 24,
    limit: int = 1000,  # Increased limit for charts
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    db: Session = Depends(get_pg_db),
):
    """
    Fetch historical data for a specific metric on a node.
    Supports fixed 'hours' lookback or custom 'start_time'/'end_time' range (ISO format).
    """
    return metric_repo.get_metric_history(
        db, node_id, metric_id, limit, hours, start_time, end_time
    )
