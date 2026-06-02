from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import List, Dict, Any, Optional
from models.core import MetricDef, Node
from pydantic import BaseModel
import services.metric_service as metric_service
from services.snmp_service import validate_snmp_oid
from services.auth_service import get_current_active_user, check_permission
from models.user import User, UserPermission
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from postgres_db import get_pg_db
from repositories import metric_repo
from services.metric_operation_guard import MetricOperationInProgress

router = APIRouter(
    prefix="/metrics",
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


@router.get("/{metric_id}", response_model=Dict[str, Any])
async def get_metric(metric_id: str):
    """Fetch a single metric definition."""
    metric = metric_service.get_metric(metric_id)
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")
    return metric


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
    try:
        return await run_in_threadpool(metric_service.create_metric, metric)
    except MetricOperationInProgress as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Metric operation already in progress",
                "metric_id": exc.metric_id,
            },
        ) from exc


@router.delete("/{metric_id}")
async def delete_metric(
    metric_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Delete a Metric Definition. Requires authentication and CI_EDIT permission."""
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to delete metrics")
    try:
        return await run_in_threadpool(metric_service.delete_metric, metric_id)
    except MetricOperationInProgress as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Metric operation already in progress",
                "metric_id": exc.metric_id,
            },
        ) from exc


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
    if not result.get("success"):
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=result)
    return result


@router.get("/{metric_id}/history")
async def get_metric_history(
    metric_id: str,
    hours: int = 24,
    limit: int = 1000,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    node_ids: Optional[str] = Query(None, description="Comma-separated list of node IDs, max 10"),
    db: Session = Depends(get_pg_db),
):
    """
    Fetch historical data for the same metric across multiple CIs.

    Supports two modes:
    - Multi-CI:  GET /api/metrics/{metric_id}/history?node_ids=ci1,ci2,ci3&hours=24
    - Single-CI: GET /api/metrics/{node_id}/{metric_id}/history (backward compatible, see below)

    When node_ids is provided (comma-separated list), returns batch data for all CIs
    with server-side 30-second interpolation onto a common time grid.
    Maximum 10 CIs allowed per request.

    Without node_ids, raises HTTP 400 directing callers to the single-CI endpoint.
    """
    if node_ids:
        node_id_list = [n.strip() for n in node_ids.split(",") if n.strip()]
        if len(node_id_list) > 10:
            raise HTTPException(status_code=400, detail="Max 10 CIs allowed")
        if not node_id_list:
            raise HTTPException(status_code=400, detail="node_ids must not be empty")

        return {"nodes": metric_repo.get_metric_history_batch(
            db, node_id_list, metric_id, hours, start_time, end_time, limit
        )}

    raise HTTPException(
        status_code=400,
        detail="Use GET /api/metrics/{node_id}/{metric_id}/history for single-CI or include node_ids for multi-CI"
    )


@router.get("/{node_id}/{metric_id}/history-days")
async def get_metric_history_days(
    node_id: str,
    metric_id: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    db: Session = Depends(get_pg_db),
):
    """Return YYYY-MM-DD dates that have at least one metric sample."""
    return metric_repo.get_metric_history_days(
        db, node_id, metric_id, start_time, end_time
    )


# Original single-CI history endpoint — preserved for backward compatibility
@router.get("/{node_id}/{metric_id}/history")
async def get_metric_history_single(
    node_id: str,
    metric_id: str,
    hours: int = 24,
    limit: int = 1000,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    db: Session = Depends(get_pg_db),
):
    """
    Fetch historical data for a specific metric on a single node.
    Supports fixed 'hours' lookback or custom 'start_time'/'end_time' range (ISO format).
    """
    return metric_repo.get_metric_history(
        db, node_id, metric_id, limit, hours, start_time, end_time
    )
