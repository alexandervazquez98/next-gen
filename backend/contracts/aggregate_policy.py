"""Aggregate disclosure policy and tiered safe_geo_precision (REQ-9).

This module defines:

- :class:`SafeGeoPrecision` enum: ``city | region | none``.
- :class:`AggregatePolicy`: minimum_count + permission_required defaults.
- :func:`derive_safe_geo_precision`: tiered mapping from ``visible_count`` and
  ``minimum_count`` to a :class:`SafeGeoPrecision` value.

Pure functions, no IO.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MINIMUM_COUNT = 5
PERMISSION_REQUIRED = "graph:aggregate_breakdown:read"


class SafeGeoPrecision(str, Enum):
    """Tiered geographic precision for aggregates.

    - ``none``:   too few records — suppress geo summary entirely.
    - ``region``: enough to show region-level grouping but not city.
    - ``city``:   enough to show city-level grouping.
    """

    NONE = "none"
    REGION = "region"
    CITY = "city"


@dataclass(frozen=True, slots=True)
class AggregatePolicy:
    """Aggregate disclosure policy.

    ``minimum_count``: any aggregate below this threshold is redacted.
    ``permission_required``: permission needed to view per-bucket detail
        (gating the ``aggregate_breakdown`` view; the permission itself
        is added to ``UserPermission`` as a prerequisite for #391).
    """

    minimum_count: int = DEFAULT_MINIMUM_COUNT
    permission_required: str = PERMISSION_REQUIRED

    def __post_init__(self) -> None:
        if not isinstance(self.minimum_count, int) or self.minimum_count < 1:
            raise ValueError(
                f"minimum_count must be a positive integer; got {self.minimum_count!r}"
            )


# ---------------------------------------------------------------------------
# Pure function: tiered geo precision
# ---------------------------------------------------------------------------


def derive_safe_geo_precision(
    visible_count: int, minimum_count: int
) -> str:
    """Map visible_count + minimum_count to a :class:`SafeGeoPrecision` value.

    Tiers (when ``minimum_count >= 1``):
        * ``visible_count < minimum_count``     -> ``SafeGeoPrecision.NONE``
        * ``visible_count < minimum_count * 4`` -> ``SafeGeoPrecision.REGION``
        * otherwise                             -> ``SafeGeoPrecision.CITY``
    """
    if not isinstance(visible_count, int) or visible_count < 0:
        raise ValueError(
            f"visible_count must be a non-negative integer; got {visible_count!r}"
        )
    if not isinstance(minimum_count, int) or minimum_count < 1:
        raise ValueError(
            f"minimum_count must be a positive integer; got {minimum_count!r}"
        )

    if visible_count < minimum_count:
        return SafeGeoPrecision.NONE.value
    if visible_count < minimum_count * 4:
        return SafeGeoPrecision.REGION.value
    return SafeGeoPrecision.CITY.value
