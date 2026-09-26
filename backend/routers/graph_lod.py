"""CMDB graph LOD router (#391 PR1).

Exposes ``GET /graph/overview`` returning the Level-of-Detail overview
payload defined by the contract slice (#390, shipped v1.17.6) and the
runtime spec (``openspec/changes/cmdb-graph-lod-runtime/specs/cmdb-graph-overview-api/spec.md``).

The detail endpoint (``GET /graph/detail/{cluster_id}``) is implemented
in #391 PR2; this router owns only the overview endpoint for now.

Hard rules (mirrored from the spec):

- Authorization/scoping happens BEFORE aggregation (REQ-OVERVIEW-2).
- Hidden and absent clusters are externally indistinguishable
  (REQ-OVERVIEW-3). The repository layer enforces visibility; the
  router never inspects the full graph.
- ``/graph/full`` shape and redaction semantics are unchanged (covered
  by ``test_graph_full_snapshot.py``).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from models.user import User
from schemas.graph import OverviewResponse
from services import graph_lod_service
from services.auth_service import get_current_active_user

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
    the repository implementation #391 PR2 will consume them when
    aggregation grows beyond the current scope.
    """
    filters: dict[str, Any] = {}
    if severity is not None:
        filters["severity"] = severity
    if ci_type is not None:
        filters["ci_type"] = ci_type
    return graph_lod_service.get_overview(principal=current_user, filters=filters)
