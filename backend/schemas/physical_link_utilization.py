"""Pydantic schemas + WindowDuration parser for the PhysicalLink utilization endpoint.

Slice 3/4 of the fiber-optic / physical-link visualization chain (#439). Mirrors
the discipline of ``backend/schemas/graph.py`` (extra="forbid", strict literal
enums) — the wire shape is the contract with the frontend, and silent field
coercion is forbidden at this boundary.

Wire shape
----------

Happy path (link UP, samples present, capacity 10 Gbps)::

    {
      "physical_link_id": "pl-fiber-test-01",
      "window_seconds": 900,
      "computed_at": "2026-10-03T20:54:37Z",
      "stale": false,
      "empty_reason": null,
      "last_sample_at": "2026-10-03T20:53:00Z",
      "utilization": {
        "endpoint_a": {"in_bytes_delta": ..., "out_bytes_delta": ..., "in_bps": ..., "out_bps": ...},
        "endpoint_b": {"in_bytes_delta": ..., "out_bytes_delta": ..., "in_bps": ..., "out_bps": ...},
        "max_endpoint_bps": ...,
        "capacity_bps": ...,
        "utilization_percent": 0.5,
        "saturated": false
      }
    }

Empty case (no samples in window)::

    {
      "physical_link_id": "pl-fiber-test-01",
      "window_seconds": 900,
      "computed_at": "2026-10-03T20:54:37Z",
      "stale": false,
      "empty_reason": "no_data",
      "last_sample_at": null,
      "utilization": null
    }
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# WindowDuration parser
# ---------------------------------------------------------------------------


class WindowDuration:
    """Parse + serialize the canonical rollup window vocabulary.

    The spec locks the supported set: ``15m | 30m | 1h | 6h | 24h`` (15m is
    the default; the others are operator-selectable). Any other input is
    rejected with ``ValueError`` so the router can map the failure to HTTP
    422.
    """

    _TO_SECONDS: dict[str, int] = {
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "6h": 21600,
        "24h": 86400,
    }
    _FROM_SECONDS: dict[int, str] = {v: k for k, v in _TO_SECONDS.items()}

    @classmethod
    def parse(cls, raw: str) -> int:
        """Convert a canonical duration string to seconds.

        Raises:
            ValueError: when the input is not in the documented vocabulary.
        """
        if not isinstance(raw, str) or not raw:
            raise ValueError(f"invalid window: {raw!r}")
        key = raw.strip().lower()
        if key not in cls._TO_SECONDS:
            raise ValueError(f"invalid window {raw!r}; expected one of {sorted(cls._TO_SECONDS)}")
        return cls._TO_SECONDS[key]

    @classmethod
    def to_string(cls, seconds: int) -> str:
        """Inverse of :meth:`parse` — returns the canonical string for ``seconds``."""
        if seconds not in cls._FROM_SECONDS:
            raise ValueError(
                f"unknown window in seconds: {seconds!r}; expected one of {sorted(cls._FROM_SECONDS)}"
            )
        return cls._FROM_SECONDS[seconds]


# ---------------------------------------------------------------------------
# EmptyReason literal — extends the set from schemas/graph.py with
# the three values unique to the PhysicalLink utilization surface.
# ---------------------------------------------------------------------------


EmptyReasonLiteral = Literal[
    "none",
    "no_visible_members",
    "hidden_absent",
    "unavailable",
    "no_data",
    "stale_samples",
    "no_capacity",
]


# ---------------------------------------------------------------------------
# Base config — strict model: forbid unknown fields, validate on assignment
# ---------------------------------------------------------------------------


def _strict_model() -> ConfigDict:
    return ConfigDict(
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
        use_enum_values=False,
    )


# ---------------------------------------------------------------------------
# Response DTOs
# ---------------------------------------------------------------------------


class UtilizationEndpoint(BaseModel):
    """Per-endpoint counter deltas + computed bit rate."""

    model_config = _strict_model()

    in_bytes_delta: int = Field(..., ge=0)
    out_bytes_delta: int = Field(..., ge=0)
    in_bps: int = Field(..., ge=0)
    out_bps: int = Field(..., ge=0)


class UtilizationMetric(BaseModel):
    """Aggregate utilization metric for a PhysicalLink.

    ``utilization_percent`` is the *clipped* ratio in [0.0, 1.0]. When the
    raw max exceeds 1.0, ``saturated`` is true and the wire value is 1.0
    (callers should still inspect ``max_endpoint_bps`` vs ``capacity_bps``
    to see the overrun).
    """

    model_config = _strict_model()

    endpoint_a: UtilizationEndpoint | None
    endpoint_b: UtilizationEndpoint | None
    max_endpoint_bps: int = Field(..., ge=0)
    capacity_bps: int = Field(..., ge=0)
    utilization_percent: float = Field(..., ge=0.0, le=1.0)
    saturated: bool


class PhysicalLinkUtilizationResponse(BaseModel):
    """Wire shape for ``GET /api/cmdb/physical-links/{id}/utilization``."""

    model_config = _strict_model()

    physical_link_id: str
    window_seconds: int = Field(..., gt=0)
    computed_at: str
    stale: bool
    empty_reason: EmptyReasonLiteral | None
    last_sample_at: str | None
    utilization: UtilizationMetric | None


# Re-export surface for callers that want a single import.
__all__ = [
    "EmptyReasonLiteral",
    "PhysicalLinkUtilizationResponse",
    "UtilizationEndpoint",
    "UtilizationMetric",
    "WindowDuration",
]
