"""Pydantic schemas for the /api/cmdb/physical-links router — feat-444 (slice 2).

Slice 2/4 of the fiber-optic / physical-link visualization chain (#444).
The metadata model + migration shipped in slice 1 (#323); these schemas
are the wire boundary that the router exposes to the frontend.

Two shapes on the wire:
- ``PhysicalLinkCreateRequest``: accepts ``endpoints: tuple[str, str]`` to
  match the backend ``PhysicalLink`` Pydantic model.
- ``PhysicalLinkResponse``: projects ``endpoints`` as ``list[str]`` for JSON
  wire compatibility with the frontend ``PhysicalLink.endpoints: [string,
  string]`` DTO.

The Literal types use the canonical allow-lists from the backend model. An
invalid value at the wire boundary returns 422 by Pydantic; the service
layer additionally validates with frozensets as defence in depth.
"""

from __future__ import annotations

from models.core import PhysicalLinkStatus, PhysicalLinkType
from pydantic import BaseModel, Field


class PhysicalLinkCreateRequest(BaseModel):
    """Request body for ``POST /api/cmdb/physical-links``."""

    id: str = Field(..., min_length=1, description="Stable id for the PhysicalLink row.")
    type: PhysicalLinkType = Field(
        ..., description="One of fiber / copper / microwave / wireless_ptp."
    )
    endpoints: tuple[str, str] = Field(..., description="Two CI ids that the link connects.")
    status: PhysicalLinkStatus = Field(
        default="UNKNOWN",
        description="One of UP / DOWN / UNKNOWN / PLANNED.",
    )
    capacity_gbps: float | None = Field(
        default=None,
        ge=0,
        description="Link capacity in Gbps (informational).",
    )
    install_date: str | None = Field(
        default=None,
        description="ISO 8601 install date (informational).",
    )


class PhysicalLinkUpdateStatusRequest(BaseModel):
    """Request body for ``PATCH /api/cmdb/physical-links/{id}/status``."""

    status: PhysicalLinkStatus = Field(
        ...,
        description="One of UP / DOWN / UNKNOWN / PLANNED.",
    )


class PhysicalLinkResponse(BaseModel):
    """Wire shape returned by every PhysicalLink endpoint.

    ``endpoints`` is projected as ``list[str]`` (NOT tuple) for JSON wire
    compatibility — matches the frontend ``PhysicalLink.endpoints:
    [string, string]`` DTO byte-for-byte.
    """

    id: str
    type: PhysicalLinkType
    endpoints: list[str] = Field(..., min_length=2, max_length=2)
    status: PhysicalLinkStatus
    capacity_gbps: float | None = None
    install_date: str | None = None


# Re-export for callers that want a single import surface.
__all__ = [
    "PhysicalLinkCreateRequest",
    "PhysicalLinkUpdateStatusRequest",
    "PhysicalLinkResponse",
]
