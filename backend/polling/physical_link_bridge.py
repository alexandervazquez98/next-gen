"""PhysicalLink polling bridge — feat-443 slice 4/4.

Scheduled job that wires ``metric_values`` to the PhysicalLink metadata
graph. For each active :PhysicalLink (status in {UP, UNKNOWN, PLANNED})
the bridge stamps ``pl.last_polled_at = now`` when at least one endpoint
has a fresh ``metric_values`` row in the last
``fresh_window_seconds`` (default 60s). Stale links are skipped — the
cached timestamp is never overwritten with ``null``.

Hard constraints (mirrored from the ODD doc):
* No changes to ``snmp_worker.py`` or ``writer_pool.py``.
* ``metric_values`` is the single source of truth.
* Time control via a ``_now`` lambda — no ``freezegun``.

PR1 covers find + stamp + feature flag. PR2 adds status derivation via
``services.physical_link_polling_state.derive_status``.
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

logger = logging.getLogger(__name__)


class _SettingsLike(Protocol):
    """Anything with ``feature_enabled`` and ``fresh_window_seconds``."""

    feature_enabled: bool
    fresh_window_seconds: int


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
          "stamped":  <int>,   # links that received a fresh stamp
          "skipped":  <int>,   # links with no recent samples (left alone)
          "errors":   <int>,   # per-link errors (logged, never raised)
          "disabled": <bool>,  # True when the feature flag is off
        }
    """
    if not getattr(settings, "feature_enabled", False):
        logger.info("PhysicalLink polling bridge is disabled")
        return {"stamped": 0, "skipped": 0, "errors": 0, "disabled": True}

    current = now or (_now() if _now is not None else _now_default())
    fresh_window_seconds = int(getattr(settings, "fresh_window_seconds", 60))
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)

    window_start = current - timedelta(seconds=fresh_window_seconds)

    repo: PhysicalLinkRepo = get_physical_link_repo(driver=driver)
    active_links = repo.find_active_links(driver=driver)
    logger.info(
        "PhysicalLink polling bridge: %d active links (window=%ds)",
        len(active_links),
        fresh_window_seconds,
    )

    stats = {"stamped": 0, "skipped": 0, "errors": 0, "disabled": False}

    for link in active_links:
        link_id = link.get("id")
        if not link_id:
            stats["errors"] += 1
            continue

        try:
            if _link_has_fresh_sample(link, window_start, current, metric_repo):
                repo.update_last_polled_at(link_id, current)
                stats["stamped"] += 1
            else:
                # No recent samples — do NOT touch the cached
                # ``last_polled_at`` (T4 invariant).
                stats["skipped"] += 1
        except Exception as exc:  # pragma: no cover - defensive
            stats["errors"] += 1
            logger.warning(
                "PhysicalLink polling bridge: link_id=%s failed: %s",
                link_id,
                exc,
            )

    logger.info(
        "PhysicalLink polling bridge done: stamped=%d skipped=%d errors=%d",
        stats["stamped"],
        stats["skipped"],
        stats["errors"],
    )
    return stats


def _link_has_fresh_sample(
    link: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
    metric_repo_module: Any,
) -> bool:
    """Return True when at least one endpoint of the link has a
    ``metric_values`` row in ``[window_start, window_end]``.

    The bridge reads via ``metric_repo.get_metric_window`` so the
    production code path matches the slice-3 service layer and the
    tests can monkeypatch the helper without a real database.

    We probe a single metric per endpoint (``ifInOctets``) — the
    slice-3 aggregate query is overkill for the bridge's needs. PR2
    will use the full aggregate for status derivation.
    """
    endpoints = link.get("endpoints") or []
    for ci_id in endpoints:
        # Any non-empty list means a fresh sample exists (the helper
        # filters on [start, end] in both the mock and the live driver).
        rows = metric_repo_module.get_metric_window(ci_id, "ifInOctets", window_start, window_end)
        if rows:
            return True
    return False
