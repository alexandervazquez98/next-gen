"""Service layer for PhysicalLink polling status derivation — feat-443 (PR2, slice 4/4).

Slice 4/4 of the fiber-optic / physical-link visualization chain (#443).
This module derives a fresh ``status`` for each :PhysicalLink from the
freshness and completeness of the connected CIs' ``metric_values`` rows.
The function is pure — it does not touch Neo4j, the polling pipeline,
or any tunnel code — so the service can be unit-tested without external
state.

Hard rules (mirrored from the ODD doc):
* ``metric_values`` is the single source of truth — no parallel state.
* Status derivation rules are LOCKED:
  - ``PLANNED`` when ``capacity_gbps`` is unset (utilization is
    undefined until the operator provisions capacity).
  - ``UP`` when at least one endpoint has a fresh sample (timestamp
    inside ``[now - stale_after_seconds, now]``).
  - ``DOWN`` when *every* endpoint's most-recent sample is older than
    ``stale_after_seconds``.
  - ``UNKNOWN`` when no samples exist for either endpoint (avoid false
    alarms), or when one endpoint is stale and none is fresh.
* ``freezegun`` is NOT used; ``now`` is injected directly and a
  ``_now`` lambda is accepted for the default — mirrors slice 3
  (``physical_link_utilization.py``) and ``mqtt_runtime_status``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

LinkStatus = Literal["UP", "DOWN", "UNKNOWN", "PLANNED"]

# The slice-3 service uses the same two RFC 1213 counters. Keeping the
# list explicit lets ``derive_status`` recompute ``max_sample_at`` if the
# caller forgets to populate it (defensive — repo layer normally does).
_DEFAULT_METRICS: tuple[str, ...] = ("ifInOctets", "ifOutOctets")


def _now_default() -> datetime:
    """UTC-aware wall clock. Override via the ``_now`` kwarg for tests."""
    return datetime.now(UTC)


def _endpoint_max_sample_at(endpoint_data: dict[str, Any] | None) -> datetime | None:
    """Return the newest timestamp across the endpoint's metric samples.

    Prefers ``max_sample_at`` pre-computed by the repo (matches slice 3
    contract), but recomputes from the raw rows when missing — keeps the
    function tolerant of partially-shaped inputs.
    """
    if not isinstance(endpoint_data, dict):
        return None

    precomputed = endpoint_data.get("max_sample_at")
    max_seen: datetime | None = precomputed if isinstance(precomputed, datetime) else None

    for metric_id in _DEFAULT_METRICS:
        for row in endpoint_data.get(metric_id) or []:
            if not isinstance(row, dict):
                continue
            t = row.get("time")
            if not isinstance(t, datetime):
                continue
            if max_seen is None or t > max_seen:
                max_seen = t

    return max_seen


def _ensure_aware(dt: datetime, fallback: datetime) -> datetime:
    """Attach UTC when ``dt`` is naive so comparisons against ``now`` work."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=fallback.tzinfo or UTC)
    return dt


def derive_status(
    link_row: dict[str, Any],
    endpoint_samples: dict[str, dict[str, Any]] | None,
    now: datetime | None = None,
    stale_after_seconds: int | None = None,
    *,
    _now: Callable[[], datetime] | None = None,
) -> LinkStatus:
    """Derive the new ``status`` for a PhysicalLink.

    Parameters
    ----------
    link_row:
        The :PhysicalLink row dict (must carry ``capacity_gbps``).
    endpoint_samples:
        Mapping ``ci_id -> {ifInOctets: [...], ifOutOctets: [...], max_sample_at: dt}``.
        Missing endpoints are treated as silent (no samples).
    now:
        UTC-aware timestamp for the derivation. Defaults to ``_now()``
        (or ``datetime.now(UTC)`` when ``_now`` is ``None``).
    stale_after_seconds:
        Maximum age (in seconds) of the newest sample before the
        endpoint is considered stale. Defaults to 1800 (slice 3 locked
        value from ``PHYSICAL_LINK_UTILIZATION_STALE_AFTER_SECONDS``).
    _now:
        Optional lambda for time control — mirrors the slice-3 service.

    Returns
    -------
    Literal["UP", "DOWN", "UNKNOWN", "PLANNED"]
    """
    if now is None:
        now = _now() if _now is not None else _now_default()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    if stale_after_seconds is None:
        stale_after_seconds = 1800

    # Rule 1: PLANNED wins before any freshness check. A link with no
    # capacity has no defined utilization, so derivation is a no-op.
    if link_row.get("capacity_gbps") is None:
        return "PLANNED"

    samples = endpoint_samples or {}

    # Compute the per-endpoint max_sample_at. An endpoint with no entry
    # in the mapping is treated as silent (max=None).
    endpoint_maxes: dict[str, datetime | None] = {
        ci_id: _endpoint_max_sample_at(data) for ci_id, data in samples.items()
    }

    # Rule 2: at least one fresh endpoint -> UP.
    # "Fresh" = sample timestamp inside [now - stale_after_seconds, now].
    # Track silent endpoints separately so the DOWN branch can require
    # *every* endpoint to have a stale sample (no silent endpoint allowed).
    has_fresh_endpoint = False
    has_stale_endpoint = False
    has_silent_endpoint = False
    for ts in endpoint_maxes.values():
        if ts is None:
            has_silent_endpoint = True
            continue
        ts_aware = _ensure_aware(ts, now)
        age_seconds = (now - ts_aware).total_seconds()
        if age_seconds <= stale_after_seconds:
            has_fresh_endpoint = True
        else:
            has_stale_endpoint = True

    if has_fresh_endpoint:
        return "UP"

    # Rule 3: every endpoint with a sample is stale AND no endpoint is
    # silent -> DOWN. This is the maximally-strict rule per Decision 9.
    if has_stale_endpoint and not has_silent_endpoint:
        return "DOWN"

    # Rule 4: no samples at all, OR some stale + some silent -> UNKNOWN.
    # Avoids the false-alarm case (DOWN when one endpoint is just silent).
    return "UNKNOWN"


__all__ = ["derive_status", "LinkStatus"]
