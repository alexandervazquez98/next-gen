"""HTTP router for the PhysicalLink utilization endpoint — feat-439 (slice 3/4).

Slice 3/4 of the fiber-optic / physical-link visualization chain (#439). The
endpoint exposes the per-link counter-delta utilization rollup to the
frontend; the underlying read model lives in
``services.physical_link_utilization``.

Endpoints
---------

- ``GET /api/cmdb/physical-links/{id}/utilization?window=15m`` — public read,
  gated by the same ``FEATURE_CMDB_PHYSICAL_LINKS_ENABLED`` flag as the
  slice-2 CRUD router (no separate flag — slice 3 reuses slice 2's gate so
  the operator can flip the entire PhysicalLink surface in one env var).

Auth model
----------

Public read — no Bearer required. Mirrors the slice-2 GET endpoints; the
service layer does not enforce CI_VIEW when the caller is anonymous.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from schemas.physical_link_utilization import (
    PhysicalLinkUtilizationResponse,
    WindowDuration,
)

logger = logging.getLogger(__name__)


# Reuse the slice-2 feature flag so the entire PhysicalLink surface can be
# toggled in one place. ``_feature_flag_or_404`` short-circuits to 404 (NOT
# 403) when the flag is off — mirrors ``routers.physical_links``.
FEATURE_FLAG_ENV = "FEATURE_CMDB_PHYSICAL_LINKS_ENABLED"


def _feature_enabled() -> bool:
    """Mirror of ``routers.physical_links._feature_enabled``."""
    raw = os.getenv(FEATURE_FLAG_ENV, "false").strip().lower()
    return raw in ("1", "true", "yes", "on", "enabled")


def _feature_flag_or_404() -> None:
    """Short-circuit to 404 when the feature flag is off (mirrors slice 2)."""
    if not _feature_enabled():
        raise HTTPException(status_code=404, detail="feature_disabled")


router = APIRouter(
    prefix="/cmdb/physical-links",
    tags=["CMDB Physical Links Utilization"],
    dependencies=[Depends(_feature_flag_or_404)],
    responses={404: {"description": "Not found"}},
)


@router.get(
    "/{physical_link_id}/utilization",
    response_model=PhysicalLinkUtilizationResponse,
)
async def get_physical_link_utilization(
    physical_link_id: str,
    window: str = Query(default="15m", description="Rollup window: 15m, 30m, 1h, 6h, or 24h."),
) -> PhysicalLinkUtilizationResponse:
    """GET /api/cmdb/physical-links/{id}/utilization?window=15m

    Returns the counter-delta utilization rollup for the given PhysicalLink.
    The wire shape distinguishes four states:

    - happy path — ``utilization`` populated, ``empty_reason=None``
    - no capacity — ``empty_reason="no_capacity"`` (capacity_gbps not set)
    - no data — ``empty_reason="no_data"`` (no samples in window)
    - stale — ``stale=True``, ``empty_reason="stale_samples"`` (last sample
      older than the configured threshold)
    """
    try:
        window_seconds = WindowDuration.parse(window)
    except ValueError as exc:
        # Invalid window vocabulary → 422 (matches the existing Pydantic
        # validation contract; keeps the error consistent with FastAPI's
        # automatic validation behavior for typed query params).
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    from services.physical_link_utilization import (
        get_physical_link_utilization_service,
    )

    service = get_physical_link_utilization_service()
    payload = service.compute(
        physical_link_id=physical_link_id,
        window_seconds=window_seconds,
    )
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail={
                "reason": "physical_link_not_found",
                "id": physical_link_id,
            },
        )
    return PhysicalLinkUtilizationResponse(**payload)
