# backend/services/event_lock.py
"""
Shared advisory-lock helpers for cross-writer event coordination.

Background
----------
Issue #322: when multiple poll collectors (see ``backend/engines/snmp_worker.py``,
``backend/services/snmp_service.py``, ``backend/polling/event_writer.py``)
observe the same failure concurrently, each can create a separate OPEN
Neo4j Event for the same ``(ci_id, metric_id, event_type)`` triplet because
the read-then-create path is atomic inside one Neo4j transaction but NOT
across transactions.

Fix (see ``openspec/changes/fix-event-duplication-cross-writer/``):
every writer MUST acquire a PostgreSQL transaction-scoped advisory lock
on the triplet BEFORE running the Neo4j OPTIONAL MATCH + head(collect) +
FOREACH(CREATE) block. PostgreSQL serializes writers for the same triplet
and releases the lock on transaction end (commit, rollback, or session close).

This module exposes the single helper all three writers call. Keep it tiny —
no session management, no Neo4j concerns, just one well-named primitive.
"""

from __future__ import annotations

import os
import socket
import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy import text

from config import EventLockSettings, get_event_lock_settings


logger = logging.getLogger(__name__)


@dataclass
class _WriterLockMetrics:
    """Bounded wait samples and acquisition count for one writer context."""

    window_size: int
    acquisitions_total: int = 0
    waits_ms: deque[float] = field(init=False)

    def __post_init__(self) -> None:
        self.waits_ms = deque(maxlen=self.window_size)

    def record(self, wait_ms: float) -> None:
        self.acquisitions_total += 1
        self.waits_ms.append(wait_ms)

    def snapshot(self) -> dict:
        values = list(self.waits_ms)
        return {
            "acquisitions_total": self.acquisitions_total,
            "wait_ms": _wait_distribution(values),
        }


@dataclass
class _EventLockMetrics:
    """Thread-safe in-process metrics for Event advisory-lock acquisition."""

    settings: EventLockSettings
    acquisitions_total: int = 0
    waits_ms: deque[float] = field(init=False)
    by_writer: dict[str, _WriterLockMetrics] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.waits_ms = deque(maxlen=self.settings.sample_window_size)

    def record(self, wait_ms: float, writer_context: str) -> None:
        writer = _bounded_writer_context(writer_context)
        with self._lock:
            self.acquisitions_total += 1
            self.waits_ms.append(wait_ms)
            writer_metrics = self.by_writer.get(writer)
            if writer_metrics is None:
                named_context_budget = max(0, self.settings.max_writer_contexts - 1)
                if writer != "other" and len(self.by_writer) >= named_context_budget:
                    writer = "other"
                    writer_metrics = self.by_writer.get(writer)
                if writer_metrics is None:
                    writer_metrics = _WriterLockMetrics(self.settings.sample_window_size)
                    self.by_writer[writer] = writer_metrics
            writer_metrics.record(wait_ms)

    def snapshot(self) -> dict:
        with self._lock:
            waits = list(self.waits_ms)
            by_writer = {
                writer: metrics.snapshot()
                for writer, metrics in sorted(self.by_writer.items())
            }
            distribution = _wait_distribution(waits)
            return {
                "acquisitions_total": self.acquisitions_total,
                "wait_ms": distribution,
                "alert_state": _derive_alert_state(distribution, self.settings),
                "thresholds_ms": {
                    "info": self.settings.slow_log_info_ms,
                    "warning_p95": self.settings.warning_p95_ms,
                    "critical_p99": self.settings.critical_p99_ms,
                },
                "by_writer": by_writer,
            }


_EVENT_LOCK_METRICS: _EventLockMetrics | None = None
_EVENT_LOCK_METRICS_INIT_LOCK = threading.Lock()


def _get_metrics() -> _EventLockMetrics:
    global _EVENT_LOCK_METRICS
    if _EVENT_LOCK_METRICS is None:
        with _EVENT_LOCK_METRICS_INIT_LOCK:
            if _EVENT_LOCK_METRICS is None:
                _EVENT_LOCK_METRICS = _EventLockMetrics(get_event_lock_settings())
    return _EVENT_LOCK_METRICS


def _bounded_writer_context(writer_context: str | None) -> str:
    value = (writer_context or "unknown").strip() or "unknown"
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in value)
    return safe[:80] or "unknown"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil((percentile / 100.0) * len(ordered)) - 1)
    return ordered[index]


def _wait_distribution(values: list[float]) -> dict:
    return {
        "count": len(values),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
        "max": max(values) if values else None,
    }


def _derive_alert_state(distribution: dict, settings: EventLockSettings) -> str:
    p99 = distribution["p99"]
    p95 = distribution["p95"]
    max_wait = distribution["max"]
    if p99 is not None and p99 >= settings.critical_p99_ms:
        return "CRITICAL"
    if p95 is not None and p95 >= settings.warning_p95_ms:
        return "WARNING"
    if (
        settings.slow_log_info_ms > 0
        and max_wait is not None
        and max_wait >= settings.slow_log_info_ms
    ):
        return "INFO"
    return "OK"


def record_event_lock_acquisition(wait_ms: float, writer_context: str = "unknown") -> None:
    """Record a successful Event advisory-lock acquisition wait duration."""
    _get_metrics().record(wait_ms, writer_context)


def get_event_lock_observability_snapshot() -> dict:
    """Return a bounded in-process snapshot for Event lock observability."""
    return _get_metrics().snapshot()


def reset_event_lock_observability_for_tests(sample_window_size: int | None = None) -> None:
    """Reset in-process Event lock metrics for deterministic unit tests."""
    global _EVENT_LOCK_METRICS
    with _EVENT_LOCK_METRICS_INIT_LOCK:
        settings = get_event_lock_settings()
        if sample_window_size is not None:
            settings = settings.model_copy(update={"sample_window_size": sample_window_size})
        _EVENT_LOCK_METRICS = _EventLockMetrics(settings)


def acquire_event_triplet_lock(
    pg_db,
    ci_id: str,
    metric_id: str,
    event_type: str,
    *,
    writer_context: str = "unknown",
) -> None:
    """Acquire a transaction-scoped PostgreSQL advisory lock for one triplet.

    The lock key is ``"{ci_id}|{metric_id}|{event_type}"``; ``hashtext`` collapses
    it to a 32-bit integer that ``pg_advisory_xact_lock`` accepts.

    The lock is held until ``pg_db``'s transaction commits, rolls back, or the
    session closes. Concurrent calls for the same triplet block until the
    holder's transaction ends; concurrent calls for different triplets run
    in parallel.

    Parameters
    ----------
    pg_db:
        An open SQLAlchemy ``Session`` (or any object exposing
        ``.execute(statement, params)``). MUST stay open for the duration of
        the Neo4j Event write that follows.
    ci_id, metric_id, event_type:
        The triplet identifying the Event being created/updated.
    """
    key = f"{ci_id}|{metric_id}|{event_type}"
    start = time.monotonic()
    pg_db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": key},
    )
    wait_ms = round((time.monotonic() - start) * 1000, 3)
    bounded_context = _bounded_writer_context(writer_context)
    record_event_lock_acquisition(wait_ms, writer_context=bounded_context)

    settings = get_event_lock_settings()
    if settings.slow_log_info_ms > 0 and wait_ms >= settings.slow_log_info_ms:
        logger.info(
            "event_lock_slow_acquisition",
            extra={
                "event_lock_writer_context": bounded_context,
                "event_lock_wait_ms": round(wait_ms),
                "event_lock_threshold_ms": round(settings.slow_log_info_ms),
            },
        )


# ---------------------------------------------------------------------------
# poll_collector_id — forensic attribution for #322 / spec §Poll collector
# identity persistence. Every Event CREATE / SET clause persists the
# hostname of the container that observed the failure so operators can
# correlate Events with the collector instance responsible. Cached at
# module load so per-row writes don't trigger repeated socket / env reads.
# ---------------------------------------------------------------------------

_CACHED_HOSTNAME: str | None = None


def get_poll_collector_id() -> str:
    """Return the hostname of the current container/pod for ``poll_collector_id``.

    Sources the value from the ``HOSTNAME`` env var (set automatically in
    Kubernetes / Docker / systemd-nspawn containers) with a fallback to
    ``socket.gethostname()`` for bare-metal deployments. The value is
    cached at module load — subsequent calls return the cached string.

    Raises
    ------
    RuntimeError
        If both the ``HOSTNAME`` env var and ``socket.gethostname()``
        return empty strings. We refuse to silently persist an empty
        ``poll_collector_id`` because that would defeat forensic
        correlation entirely.
    """
    global _CACHED_HOSTNAME
    if _CACHED_HOSTNAME is None:
        raw = (os.getenv("HOSTNAME") or "").strip() or socket.gethostname().strip()
        if not raw:
            raise RuntimeError(
                "Cannot determine poll_collector_id: HOSTNAME env var and "
                "socket.gethostname() are both empty"
            )
        _CACHED_HOSTNAME = raw
    return _CACHED_HOSTNAME


# Resolve once at import time so all three writers see the same constant
# without re-running the env / socket lookup on every Event CREATE.
POLL_COLLECTOR_ID = get_poll_collector_id()
