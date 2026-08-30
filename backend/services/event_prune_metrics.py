# backend/services/event_prune_metrics.py
"""
In-process observability for the auto-prune + manual-prune path.

Background
----------
PR #1 of fix-423 ships the metric surface that the auto-prune scheduler (PR #2)
and the manual ``POST /api/events/prune`` operator path converge on, so the
``GET /api/system/status`` payload can expose ``collector.prune.*`` without
hitting Neo4j on every dashboard poll. The dashboard polls every 3 s
(``frontend/hooks/queries/useSystemStatusQuery.ts:5-9``); a per-request Cypher
``MATCH ... RETURN count(e)`` on ``Event`` would multiply DB traffic by ~20x.

Surface (REQ-OBS-PRUNE-001 / REQ-OBS-PRUNE-002 / REQ-OBS-PRUNE-003):

* ``events_recovered_stale_total`` — gauge of RECOVERED Event rows older than
  ``stale_after_seconds`` (default 3600 s) without closure. Refreshed by the
  scheduler tick; ``_build_system_status_payload`` reads it without a Cypher
  round-trip.
* ``events_pruned_total`` — per-batch counter. Increments by one when a
  scheduler tick closes at least one row; empty batches do NOT increment
  (REQ-OBS-PRUNE-002 scenario).
* ``collector.prune.last_run_closed_count`` — gauge of the most recent tick's
  closed count (0 when the tick found no candidates).
* ``collector.prune.last_run_at`` — ISO timestamp of the most recent tick
  (``None`` until the first tick).

Mirrors the lock metrics pattern in ``services/event_lock.py``:
``_EventPruneMetrics`` dataclass + thread-safe singleton +
``reset_event_prune_observability_for_tests`` for deterministic test state.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class _EventPruneMetrics:
    """Thread-safe in-process metrics for Event prune observability."""

    recovered_stale_total: int = 0
    pruned_total: int = 0
    last_run_at: datetime | None = None
    last_run_closed_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_recovered_stale(self, count: int) -> None:
        if count <= 0:
            return
        with self._lock:
            self.recovered_stale_total += count

    def record_pruned(self, closed_count: int) -> None:
        """Record one scheduler tick.

        REQ-OBS-PRUNE-002: the ``pruned_total`` counter increments by exactly
        one when ``closed_count >= 1``; empty batches MUST NOT increment.
        ``last_run_closed_count`` always reflects the most recent tick (gauge).
        ``last_run_at`` always advances on every tick (even an empty one).
        """
        with self._lock:
            if closed_count >= 1:
                self.pruned_total += 1
            self.last_run_closed_count = max(0, closed_count)
            self.last_run_at = datetime.now(UTC).replace(tzinfo=None)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "recovered_stale_total": self.recovered_stale_total,
                "pruned_total": self.pruned_total,
                "last_run_at": (self.last_run_at.isoformat() if self.last_run_at else None),
                "last_run_closed_count": self.last_run_closed_count,
            }


_EVENT_PRUNE_METRICS: _EventPruneMetrics | None = None
_EVENT_PRUNE_METRICS_INIT_LOCK = threading.Lock()


def _get_metrics() -> _EventPruneMetrics:
    global _EVENT_PRUNE_METRICS
    if _EVENT_PRUNE_METRICS is None:
        with _EVENT_PRUNE_METRICS_INIT_LOCK:
            if _EVENT_PRUNE_METRICS is None:
                _EVENT_PRUNE_METRICS = _EventPruneMetrics()
    return _EVENT_PRUNE_METRICS


def record_recovered_stale(count: int) -> None:
    """Increment the RECOVERED stale-rows gauge by ``count`` (REQ-OBS-PRUNE-001)."""
    _get_metrics().record_recovered_stale(count)


def record_pruned(closed_count: int) -> None:
    """Record one prune scheduler tick (REQ-OBS-PRUNE-002)."""
    _get_metrics().record_pruned(closed_count)


def get_event_prune_observability_snapshot() -> dict:
    """Return a snapshot of the prune observability dataclass (REQ-OBS-PRUNE-003)."""
    return _get_metrics().snapshot()


def reset_event_prune_observability_for_tests() -> None:
    """Reset in-process Event prune metrics for deterministic unit tests."""
    global _EVENT_PRUNE_METRICS
    with _EVENT_PRUNE_METRICS_INIT_LOCK:
        _EVENT_PRUNE_METRICS = _EventPruneMetrics()
