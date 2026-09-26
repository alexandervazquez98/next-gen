"""CMDB graph LOD router (#391 PR1 + PR2).

Exposes ``GET /graph/overview`` (PR1) and ``GET /graph/detail/{cluster_id}``
(PR2) returning the Level-of-Detail payloads defined by the contract
slice (#390, shipped v1.17.6) and the runtime spec
(``openspec/changes/cmdb-graph-lod-runtime/specs/cmdb-graph-{overview,detail}-api/spec.md``).

Hard rules (mirrored from the spec):

- Authorization/scoping happens BEFORE aggregation (REQ-OVERVIEW-2).
- Hidden and absent clusters are externally indistinguishable
  (REQ-OVERVIEW-3, REQ-DETAIL-4). The repository layer enforces
  visibility; the router never inspects the full graph.
- ``/graph/full`` shape and redaction semantics are unchanged (covered
  by ``test_graph_full_snapshot.py``).
- Cursor is bound to (cluster_id, filters_hash, revision, principal_hash);
  stale revisions surface as 409, permission changes as 400.
- ``?axis=`` query parameter must match cluster_id axis BEFORE any
  auth-sensitive lookup.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from models.user import User
from schemas.graph import DetailResponse, OverviewResponse
from services import graph_lod_service
from services.auth_service import get_current_active_user

from contracts.cluster_id import AxisConflictError, InvalidClusterIdError
from contracts.cursor import (
    InvalidCursorError,
    PermissionChangedError,
    StaleCursorError,
)

router = APIRouter(
    prefix="/graph",
    tags=["CMDB-LOD"],
    responses={401: {"description": "Not authenticated"}},
)


@router.get("/overview", response_model=OverviewResponse)
async def get_graph_overview(
    current_user: User = Depends(get_current_active_user),  # noqa: B008
    severity: str | None = Query(default=None, description="Filter by severity"),
    ci_type: str | None = Query(default=None, description="Filter by CI type"),
) -> OverviewResponse:
    """Return the location-cluster overview for the authenticated principal.

    Auth: any authenticated user with ``CMDB_READ`` (or higher) can call
    this endpoint. Non-admin principals are restricted to their
    ``allowed_locations``; admins see the full visible graph.

    Filters are forwarded into the response payload for client display;
    the repository implementation will consume them when aggregation
    grows beyond the current scope.
    """
    filters: dict[str, Any] = {}
    if severity is not None:
        filters["severity"] = severity
    if ci_type is not None:
        filters["ci_type"] = ci_type
    return graph_lod_service.get_overview(principal=current_user, filters=filters)


@router.get("/detail/{cluster_id}", response_model=DetailResponse)
async def get_graph_detail(
    cluster_id: str,
    current_user: User = Depends(get_current_active_user),  # noqa: B008
    cursor: str | None = Query(default=None, description="Opaque pagination cursor"),
    limit: int = Query(default=100, ge=1, le=1000),
    axis: str | None = Query(default=None, description="Axis (must match cluster_id)"),
    sensitive: str | None = Query(default=None, description="'include' to request sensitive"),
) -> DetailResponse:
    """Return the bounded subgraph for a single cluster.

    Auth: any authenticated user with ``CMDB_READ`` can call this endpoint.
    Non-admin principals are restricted to their ``allowed_locations``;
    admins see the full visible graph.

    Hidden and absent clusters return byte-equivalent responses
    (``cluster: null`` + ``empty_reason: "hidden_absent"``).
    """
    sensitive_requested = sensitive == "include"
    filters: dict[str, Any] = {}
    try:
        return graph_lod_service.get_detail(
            cluster_id_raw=cluster_id,
            principal=current_user,
            filters=filters,
            cursor=cursor,
            limit=limit,
            sensitive_requested=sensitive_requested,
            axis_query=axis,
        )
    except InvalidClusterIdError as exc:
        raise HTTPException(status_code=400, detail=exc.as_error_body()) from exc
    except AxisConflictError as exc:
        raise HTTPException(status_code=400, detail=exc.as_error_body()) from exc
    except InvalidCursorError as exc:
        raise HTTPException(status_code=400, detail=exc.as_error_body()) from exc
    except PermissionChangedError as exc:
        raise HTTPException(status_code=400, detail=exc.as_error_body()) from exc
    except StaleCursorError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.as_error_body(),
        ) from exc
