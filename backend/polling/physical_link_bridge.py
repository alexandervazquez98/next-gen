"""PhysicalLink polling bridge — feat-443 slice 4/4.

Scheduled job that wires ``metric_values`` to the PhysicalLink metadata
graph. For each active :PhysicalLink (status in {UP, UNKNOWN, PLANNED})
the bridge stamps ``pl.last_polled_at = now`` when at least one endpoint
has a fresh ``metric_values`` row in the last
``fresh_window_seconds`` (default 60s). Stale links are skipped — the
cached timestamp is never overwritten with ``null``.

PR2 (this iteration) adds status derivation: after each
``last_polled_at`` write, the bridge calls
``services.physical_link_polling_state.derive_status`` and persists the
new ``pl.status`` ONLY when it differs from the current value (idempotent
upserts; tunnel polling path is untouched).

Hard constraints (mirrored from the ODD doc):
* No changes to ``snmp_worker.py`` or ``writer_pool.py``.
* ``metric_values`` is the single source of truth.
* Time control via a ``_now`` lambda — no ``freezegun``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from repositories import metric_repo
from repositories.physical_link_repo import (
    PhysicalLinkRepo,
    get_physical_link_repo,
)
from services.physical_link_polling_state import derive_status

logger = logging.getLogger(__name__)


class _SettingsLike(Protocol):
    """Anything with ``feature_enabled``, ``fresh_window_seconds``,
    and ``stale_after_seconds``."""

    feature_enabled: bool
    fresh_window_seconds: int
    stale_after_seconds: int


def _now_default() -> datetime:
    """Default ``_now`` — overridable via the ``_now`` kwarg. UTC-aware."""
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_once(
    settings: _SettingsLike,
    driver: Any,
    now: datetime | None = None,
    *,
    _now: Callable[[], datetime] | None = None,
) -> dict[str, int]:
    """Run one polling bridge pass.

    Returns a small stats dict::

        {
          "stamped":        <int>,  # links that received a fresh stamp
          "skipped":        <int>,  # links with no recent samples (left alone)
          "status_changes": <int>,  # links whose pl.status changed this pass
          "errors":         <int>,  # per-link errors (logged, never raised)
          "disabled":       <bool>, # True when the feature flag is off
        }
    """
    if not getattr(settings, "feature_enabled", False):
        logger.info("PhysicalLink polling bridge is disabled")
        return {
            "stamped": 0,
            "skipped": 0,
            "status_changes": 0,
            "errors": 0,
            "disabled": True,
        }

    current = now or (_now() if _now is not None else _now_default())
    fresh_window_seconds = int(getattr(settings, "fresh_window_seconds", 60))
    # PR2: derive_status uses the same slice-3 threshold (default 1800s)
    # so the derived status and the slice-3 read model agree on staleness.
    stale_after_seconds = int(getattr(settings, "stale_after_seconds", 1800))
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)

    # Status derivation needs the wider window so it can identify stale
    # endpoints. Use that for both the fresh check (subset of stale
    # window) and the sample fetch (avoids a second round-trip to the
    # metrics DB).
    derivation_window_start = current - timedelta(seconds=stale_after_seconds)
    fresh_window_start = current - timedelta(seconds=fresh_window_seconds)

    repo: PhysicalLinkRepo = get_physical_link_repo(driver=driver)
    active_links = repo.find_active_links(driver=driver)
    logger.info(
        "PhysicalLink polling bridge: %d active links (window=%ds, stale=%ds)",
        len(active_links),
        fresh_window_seconds,
        stale_after_seconds,
    )

    stats = {
        "stamped": 0,
        "skipped": 0,
        "status_changes": 0,
        "errors": 0,
        "disabled": False,
    }

    for link in active_links:
        link_id = link.get("id")
        if not link_id:
            stats["errors"] += 1
            continue

        try:
            endpoint_samples = _collect_endpoint_samples(
                link, derivation_window_start, current, metric_repo
            )

            if _has_fresh_sample(endpoint_samples, fresh_window_start, current):
                repo.update_last_polled_at(link_id, current)
                stats["stamped"] += 1
            else:
                # No recent samples — do NOT touch the cached
                # ``last_polled_at`` (T4 invariant).
                stats["skipped"] += 1

            # PR2: derive the new status and persist only on change.
            # Idempotent upsert — no churn when the derived status matches.
            derived = derive_status(
                link,
                endpoint_samples,
                now=current,
                stale_after_seconds=stale_after_seconds,
            )
            if derived != link.get("status"):
                repo.update_status(link_id, derived)
                stats["status_changes"] += 1
                logger.info(
                    "PhysicalLink polling bridge: link_id=%s status %s -> %s",
                    link_id,
                    link.get("status"),
                    derived,
                )
        except Exception as exc:  # pragma: no cover - defensive
            stats["errors"] += 1
            logger.warning(
                "PhysicalLink polling bridge: link_id=%s failed: %s",
                link_id,
                exc,
            )

    logger.info(
        "PhysicalLink polling bridge done: stamped=%d skipped=%d status_changes=%d errors=%d",
        stats["stamped"],
        stats["skipped"],
        stats["status_changes"],
        stats["errors"],
    )
    return stats


def _collect_endpoint_samples(
    link: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
    metric_repo_module: Any,
) -> dict[str, dict[str, Any]]:
    """Read ``metric_values`` for every endpoint into the shape
    ``derive_status`` expects.

    The bridge probes both RFC 1213 counters (``ifInOctets`` /
    ``ifOutOctets``) per endpoint so the status derivation sees the
    same data the slice-3 read model aggregates. ``max_sample_at`` is
    computed eagerly so the service layer can short-circuit.
    """
    per_endpoint: dict[str, dict[str, Any]] = {}
    for ci_id in link.get("endpoints") or []:
        ci_data: dict[str, Any] = {"ifInOctets": [], "ifOutOctets": []}
        max_seen: datetime | None = None
        for metric_id in ("ifInOctets", "ifOutOctets"):
            rows = metric_repo_module.get_metric_window(ci_id, metric_id, window_start, window_end)
            ci_data[metric_id] = rows
            for row in rows:
                t = row.get("time")
                if t is None:
                    continue
                if max_seen is None or t > max_seen:
                    max_seen = t
        ci_data["max_sample_at"] = max_seen
        per_endpoint[ci_id] = ci_data
    return per_endpoint


def _has_fresh_sample(
    endpoint_samples: dict[str, dict[str, Any]],
    fresh_window_start: datetime,
    window_end: datetime,
) -> bool:
    """Return True when at least one endpoint has a sample timestamped
    in ``[fresh_window_start, window_end]``.

    Operates on pre-fetched samples so we don't issue a second round of
    ``metric_repo.get_metric_window`` calls just for the fresh check.
    """
    for ci_data in endpoint_samples.values():
        max_seen = ci_data.get("max_sample_at")
        if max_seen is None:
            continue
        if max_seen.tzinfo is None:
            max_seen = max_seen.replace(tzinfo=window_end.tzinfo or UTC)
        if fresh_window_start <= max_seen <= window_end:
            return True
    return False


def _link_has_fresh_sample(
    link: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
    metric_repo_module: Any,
) -> bool:
    """Legacy single-metric probe — kept for backwards-compatible callers.

    New code paths should use ``_collect_endpoint_samples`` +
    ``_has_fresh_sample`` so the same fetch feeds both the fresh check
    and the status derivation.
    """
    endpoints = link.get("endpoints") or []
    for ci_id in endpoints:
        rows = metric_repo_module.get_metric_window(ci_id, "ifInOctets", window_start, window_end)
        if rows:
            return True
    return False
