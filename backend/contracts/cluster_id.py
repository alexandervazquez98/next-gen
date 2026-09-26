"""Cluster ID codec for the LOD endpoints (REQ-4, REQ-7).

Wire format: ``<axis>:<url-safe-key>``.

- First-slice accepted axis: ``location`` only.
- Reserved sentinel: ``location:__unassigned__`` (display "Unassigned").
- Key regex: ``[A-Za-z0-9._\\-]{1,128}`` (URL-safe, no slashes).
- Match is case-insensitive (lowercased key for compare). Display preserves the
  caller's canonical case so labels do not flicker.
- Malformed input raises :class:`InvalidClusterIdError` with a body that
  contains ONLY ``error``, ``reason``, ``cluster_id`` — never label/count/geo.
- A conflicting ``?axis=`` query parameter raises :class:`AxisConflictError`
  BEFORE any authorization-sensitive lookup.

No IO. No imports outside the standard library.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOCATION_AXIS = "location"
UNASSIGNED_KEY = "__unassigned__"
UNASSIGNED_DISPLAY = "Unassigned"

# Regex: <axis>:<url-safe-key>
# axis: literal "location" for the first slice; key: 1..128 URL-safe chars.
_KEY_PATTERN = r"[A-Za-z0-9._\-]{1,128}"
_CLUSTER_ID_RE = re.compile(rf"^(?P<axis>{LOCATION_AXIS}):(?P<key>{_KEY_PATTERN})$")

_MAX_KEY_LEN = 128


# ---------------------------------------------------------------------------
# Errors — structured bodies, no metadata leak
# ---------------------------------------------------------------------------


class InvalidClusterIdError(ValueError):
    """Raised when a cluster_id does not match the wire format."""

    def __init__(self, cluster_id: str, reason: str) -> None:
        super().__init__(reason)
        self.cluster_id = cluster_id
        self.reason = reason

    def as_error_body(self) -> dict[str, str]:
        """Return the wire body for an invalid_cluster_id error.

        No metadata leak: label, count, geo, location_name are NOT included.
        """
        return {
            "error": "invalid_cluster_id",
            "reason": self.reason,
            "cluster_id": self.cluster_id,
        }


class AxisConflictError(ValueError):
    """Raised when ``?axis=`` query parameter conflicts with the parsed cluster axis.

    The conflict must be rejected BEFORE any authorization-sensitive lookup
    (REQ-4). Body shape contains no cluster metadata.
    """

    def __init__(self, parsed_axis: str, query_axis: str) -> None:
        super().__init__(f"axis_conflict: parsed={parsed_axis!r}, query={query_axis!r}")
        self.parsed_axis = parsed_axis
        self.query_axis = query_axis

    def as_error_body(self) -> dict[str, str]:
        return {
            "error": "axis_conflict",
            "reason": "axis query parameter conflicts with cluster_id axis",
        }


# ---------------------------------------------------------------------------
# Value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClusterId:
    """Parsed cluster identifier.

    ``key_normalized`` is the lowercased key used for equality/match. The
    original ``key`` casing is preserved in ``display_label``.
    """

    axis: str
    key: str  # original case (display)
    key_normalized: str  # lowercase (match)
    display_label: str

    @property
    def wire(self) -> str:
        """Return the canonical wire form (``axis:key`` with original case)."""
        return f"{self.axis}:{self.key}"


# ---------------------------------------------------------------------------
# Codec functions
# ---------------------------------------------------------------------------


def parse_cluster_id(raw: str | None) -> ClusterId:
    """Parse a wire cluster_id into a :class:`ClusterId`.

    Raises :class:`InvalidClusterIdError` with a structured body when the
    input does not match the wire format. The error body MUST NOT include
    any cluster metadata.
    """
    if not isinstance(raw, str):
        raise InvalidClusterIdError(str(raw), "cluster_id must be a string")

    if raw == "":
        raise InvalidClusterIdError(raw, "cluster_id is empty")

    if ":" not in raw:
        raise InvalidClusterIdError(raw, "cluster_id must be in '<axis>:<key>' format")

    # Reject slashes anywhere — the regex already enforces this, but an early
    # check yields a clearer reason for the most common misuse.
    if "/" in raw:
        raise InvalidClusterIdError(raw, "cluster_id must not contain '/'")

    match = _CLUSTER_ID_RE.match(raw)
    if match is None:
        # Distinguish a couple of common reasons so the error is actionable
        # without leaking metadata.
        axis, _, key = raw.partition(":")
        if axis != LOCATION_AXIS:
            raise InvalidClusterIdError(raw, f"axis must be {LOCATION_AXIS!r}")
        if len(key) > _MAX_KEY_LEN:
            raise InvalidClusterIdError(raw, f"key length exceeds {_MAX_KEY_LEN}")
        raise InvalidClusterIdError(raw, "key contains disallowed characters")

    axis = match.group("axis")
    key = match.group("key")

    display = UNASSIGNED_DISPLAY if key == UNASSIGNED_KEY else key

    return ClusterId(
        axis=axis,
        key=key,
        key_normalized=key.lower(),
        display_label=display,
    )


def cluster_ids_equal(a: ClusterId, b: ClusterId) -> bool:
    """Equality is axis+key (case-insensitive on key)."""
    return a.axis == b.axis and a.key_normalized == b.key_normalized


def assert_axis_matches(parsed: ClusterId, query_axis: str | None) -> None:
    """Reject a conflicting ``?axis=`` BEFORE any authorization-sensitive lookup.

    If ``query_axis`` is None or equal to ``parsed.axis``, this is a no-op.
    Otherwise it raises :class:`AxisConflictError`. The check MUST NOT
    depend on whether the cluster actually exists in the data store.
    """
    if query_axis is None:
        return
    if query_axis == parsed.axis:
        return
    raise AxisConflictError(parsed.axis, query_axis)
