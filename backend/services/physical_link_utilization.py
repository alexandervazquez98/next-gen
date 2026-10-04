"""Service layer for the PhysicalLink utilization read model — feat-439 (slice 3/4).

Slice 3/4 of the fiber-optic / physical-link visualization chain (#439). The
service composes three slices of behavior:

1. Fetch the ``PhysicalLink`` row (via ``physical_link_repo``) and its
   per-endpoint counter samples (via ``metric_repo`` — delegated from
   ``PhysicalLinkRepo.get_aggregate_counter_samples``).
2. Apply the three empty-case branches defined by the spec:
   - ``empty_reason="no_capacity"`` when ``capacity_gbps`` is unset
   - ``empty_reason="no_data"`` when no samples in the window
   - ``empty_reason="stale_samples"`` when the most recent sample is older
     than ``stale_after_seconds``
3. Compute the utilization rollup (counter-delta / window-seconds, full-
   duplex max-bottleneck semantic, clipped to [0, 1]).

Time control
------------
``_now`` is a lambda that defaults to ``datetime.now(UTC)``. Tests override
it via ``service._now = lambda: datetime(...)`` — the same pattern used by
``backend/services/mqtt_runtime_status.py``. ``freezegun`` is intentionally
NOT used (constraint from the ODD doc).

The default ``stale_after_seconds`` is read from
``config.PhysicalLinkUtilizationSettings`` so the operator can override
via ``PHYSICAL_LINK_UTILIZATION_STALE_AFTER_SECONDS``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from config import PhysicalLinkUtilizationSettings, get_physical_link_utilization_settings
from repositories.physical_link_repo import (
    PhysicalLinkRepo,
    get_physical_link_repo,
)

# Default metric ids used to compute link utilization. Locked by the spec;
# slice 4 (#443) may extend with error counters as a follow-up.
_METRICS_FOR_UTILIZATION: tuple[str, ...] = ("ifInOctets", "ifOutOctets")


def _iso_z(dt: datetime | None) -> str | None:
    """Format ``dt`` as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC). Returns None for None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _first_last(samples: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    """Return ``(first_value, last_value)`` for the sample list, or ``(None, None)`` when empty.

    The caller relies on positional ordering (oldest first) — the repo
    layer guarantees that contract via the TimescaleDB ``ORDER BY time ASC``.
    """
    if not samples:
        return None, None
    first = samples[0].get("value")
    last = samples[-1].get("value")
    if first is None or last is None:
        return None, None
    return float(first), float(last)


class PhysicalLinkUtilizationService:
    """Compute the utilization rollup for a single PhysicalLink.

    Parameters
    ----------
    repo:
        Optional ``PhysicalLinkRepo`` override (tests inject a stub).
    stale_after_seconds:
        Optional override for the staleness threshold. When unset, reads
        the runtime value from
        :func:`config.get_physical_link_utilization_settings`.
    """

    def __init__(
        self,
        repo: PhysicalLinkRepo | None = None,
        stale_after_seconds: int | None = None,
    ):
        self._repo = repo or get_physical_link_repo()
        if stale_after_seconds is None:
            settings: PhysicalLinkUtilizationSettings = get_physical_link_utilization_settings()
            self._stale_seconds = settings.stale_after_seconds
        else:
            self._stale_seconds = int(stale_after_seconds)

    # ── time control (test seam — mirrors mqtt_runtime_status pattern) ────

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    # ── main entry point ──────────────────────────────────────────────────

    def compute(
        self,
        *,
        physical_link_id: str,
        window_seconds: int,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Return the wire-shape dict for the given PhysicalLink, or None when missing.

        ``None`` is the router's signal to return 404.
        """
        now = now or self._now()

        aggregate = self._repo.get_aggregate_counter_samples(
            physical_link_id,
            window_seconds=window_seconds,
            now=now,
        )
        if aggregate is None:
            return None

        link = aggregate["physical_link"]
        endpoints = aggregate.get("endpoints") or {}

        # Wire envelope (always present, even in the empty case).
        envelope: dict[str, Any] = {
            "physical_link_id": link.get("id", physical_link_id),
            "window_seconds": int(window_seconds),
            "computed_at": _iso_z(now),
            "stale": False,
            "empty_reason": None,
            "last_sample_at": None,
            "utilization": None,
        }

        # Branch 1: capacity missing → empty_reason="no_capacity"
        if link.get("capacity_gbps") is None:
            envelope["empty_reason"] = "no_capacity"
            return envelope

        # Build the endpoint rollup first; we need the max_sample_at to
        # decide between "no_data" and the happy path.
        endpoint_rollups: list[dict[str, Any] | None] = []
        max_seen: datetime | None = None
        for ci_id, samples in endpoints.items():
            rollup, ep_max = self._rollup_endpoint(ci_id, samples, window_seconds)
            endpoint_rollups.append(rollup)
            if ep_max is not None and (max_seen is None or ep_max > max_seen):
                max_seen = ep_max

        # Branch 2: no samples in the window → empty_reason="no_data"
        if max_seen is None:
            envelope["empty_reason"] = "no_data"
            return envelope

        envelope["last_sample_at"] = _iso_z(max_seen)

        # Branch 3: stale — last sample older than threshold.
        # We treat a "fresh" sample as one whose timestamp is within the
        # threshold relative to ``now``. ``max_seen`` is the newest across
        # ALL endpoints AND metrics, so a single fresh endpoint refreshes
        # the whole link's status.
        if max_seen.tzinfo is None:
            max_seen = max_seen.replace(tzinfo=UTC)
        age_seconds = (now - max_seen).total_seconds()
        if age_seconds > self._stale_seconds:
            envelope["stale"] = True
            envelope["empty_reason"] = "stale_samples"
            return envelope

        # Happy path: compute max-bottleneck utilization.
        capacity_gbps = float(link["capacity_gbps"])
        capacity_bps = int(capacity_gbps * 1_000_000_000)

        endpoint_bps_list: list[int] = []
        for rollup in endpoint_rollups:
            if rollup is None:
                # Endpoint has no samples in window — it contributes 0 bps
                # rather than excluding the link. Matches RFC 1213 "silent"
                # behavior for an interface that stopped reporting mid-cycle.
                endpoint_bps_list.append(0)
                continue
            endpoint_bps_list.append(int(rollup["in_bps"] + rollup["out_bps"]))

        max_endpoint_bps = max(endpoint_bps_list) if endpoint_bps_list else 0
        raw_ratio = max_endpoint_bps / capacity_bps if capacity_bps > 0 else 0.0
        utilization_percent = float(max(0.0, min(raw_ratio, 1.0)))
        saturated = max_endpoint_bps > capacity_bps

        # Build the per-endpoint block; slots are nullable so the wire shape
        # is stable when one endpoint is silent.
        endpoint_a = endpoint_rollups[0] if len(endpoint_rollups) >= 1 else None
        endpoint_b = endpoint_rollups[1] if len(endpoint_rollups) >= 2 else None

        envelope["utilization"] = {
            "endpoint_a": endpoint_a,
            "endpoint_b": endpoint_b,
            "max_endpoint_bps": int(max_endpoint_bps),
            "capacity_bps": int(capacity_bps),
            "utilization_percent": utilization_percent,
            "saturated": bool(saturated),
        }
        return envelope

    # ── helpers ──────────────────────────────────────────────────────────

    def _rollup_endpoint(
        self,
        ci_id: str,
        samples: dict[str, Any] | None,
        window_seconds: int,
    ) -> tuple[dict[str, Any] | None, datetime | None]:
        """Compute the per-endpoint rollup dict + the newest sample timestamp.

        Returns ``(None, max_sample_at)`` when the endpoint has no samples in
        the window — the caller's job is to decide whether the link as a
        whole is in the empty case.
        """
        if not isinstance(samples, dict):
            # Defensive: the repo layer always returns a dict (possibly
            # empty), but a None entry here would NPE the series loop.
            return None, None

        # The repo may also stash a pre-computed ``max_sample_at`` on the
        # endpoint dict. Prefer that when present (saves a re-scan).
        precomputed_max = samples.get("max_sample_at")

        in_first, in_last = _first_last(samples.get("ifInOctets") or [])
        out_first, out_last = _first_last(samples.get("ifOutOctets") or [])

        # Cross-check max_sample_at: pick the newest timestamp across both
        # metric series. If the repo already provided one, keep whichever
        # is newer (the repo's value should match but the service must
        # not depend on that assumption).
        max_seen: datetime | None = precomputed_max
        for metric_id in _METRICS_FOR_UTILIZATION:
            for row in samples.get(metric_id) or []:
                t = row.get("time")
                if t is None:
                    continue
                if max_seen is None or t > max_seen:
                    max_seen = t

        if in_first is None and out_first is None:
            return None, max_seen

        in_first = in_first or 0.0
        in_last = in_last or 0.0
        out_first = out_first or 0.0
        out_last = out_last or 0.0

        # Counter-delta semantic. A negative delta is clamped to 0 because
        # 32-bit / 64-bit counter rollovers cannot be inferred safely
        # without the device's ifSpeed — slice 3 reports 0 and lets slice
        # 4 (polling) carry the rollover-derivation burden.
        in_delta = max(0.0, in_last - in_first)
        out_delta = max(0.0, out_last - out_first)

        safe_window = max(1, int(window_seconds))
        in_bps = int((in_delta / safe_window) * 8)
        out_bps = int((out_delta / safe_window) * 8)

        return (
            {
                "in_bytes_delta": int(in_delta),
                "out_bytes_delta": int(out_delta),
                "in_bps": int(in_bps),
                "out_bps": int(out_bps),
            },
            max_seen,
        )


# ---------------------------------------------------------------------------
# Singleton helper (lazy)
# ---------------------------------------------------------------------------

_utilization_service: PhysicalLinkUtilizationService | None = None


def get_physical_link_utilization_service(
    repo: PhysicalLinkRepo | None = None,
    stale_after_seconds: int | None = None,
) -> PhysicalLinkUtilizationService:
    """Return a cached service singleton (test seam: ``repo`` / ``stale_after_seconds``)."""
    global _utilization_service
    if _utilization_service is None:
        _utilization_service = PhysicalLinkUtilizationService(
            repo=repo,
            stale_after_seconds=stale_after_seconds,
        )
    return _utilization_service
