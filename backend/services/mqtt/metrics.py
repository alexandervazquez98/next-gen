"""In-process thread-safe counter store for the MQTT subscriber (PR4).

:class:`MqttMetrics` is a deliberately small counter facade. It exists so the
dispatch path can increment ``parsed_ok`` / ``parse_fail`` / ``nack`` counters
without coupling to a specific metrics backend. Future emitters (Prometheus,
StatsD, structured logs, ...) can read :meth:`snapshot` and forward the dict
elsewhere.

Design choices:

  * **Thread-safe**: a single :class:`threading.Lock` guards the dict. The
    contention surface is tiny (one counter mutation per message) and the
    dispatch path is async anyway, so a coarse lock is fine.
  * **Deterministic keys**: ``name{label1=v1,label2=v2}`` with labels sorted
    alphabetically. Same labels in different orders MUST produce the same
    key, otherwise downstream label-store cardinality explodes.
  * **Snapshot returns a copy**: callers can iterate freely without holding
    the lock, and tests can compare snapshots without aliasing bugs.
  * **Optional count parameter**: ``inc(name, count=N, **labels)`` lets the
    dispatch path record ``parsed_ok`` with the number of readings produced
    by a single message (one parse → many metrics).
"""

from __future__ import annotations

import threading

__all__ = ["MqttMetrics", "metrics"]


class MqttMetrics:
    """Thread-safe counter dict with deterministic label-key formatting."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._lock = threading.Lock()

    def inc(self, name: str, count: int = 1, **labels: str | int) -> None:
        """Add ``count`` to the counter keyed by ``name`` + sorted labels.

        Args:
            name: Counter identity (e.g. ``"parsed_ok"``).
            count: Amount to add. Default ``1``. Useful for batch increments
                like ``metrics.inc("parsed_ok", count=len(readings))``.
            **labels: Key-value pairs forming the counter's label set.
                Sorted alphabetically for deterministic key formatting.
        """
        key = self._make_key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + count

    def snapshot(self) -> dict[str, int]:
        """Return a shallow copy of the counter dict.

        The copy is taken under the lock so callers see a consistent point
        in time. Subsequent mutations do NOT affect the returned dict.
        """
        with self._lock:
            return dict(self._counters)

    def reset(self) -> None:
        """Clear every counter. Test-only utility — production code should
        not call this in steady state.
        """
        with self._lock:
            self._counters.clear()

    @staticmethod
    def _make_key(name: str, labels: dict[str, str | int]) -> str:
        """Build a deterministic counter key.

        Format:
          * No labels: just ``name``.
          * With labels: ``name{label1=v1,label2=v2}`` with labels sorted.

        Sorting by key (not insertion order) means callers can pass labels
        in any order and still get the same key — critical for downstream
        label-store cardinality.
        """
        if not labels:
            return name
        label_str = ",".join(f"{k}={labels[k]}" for k in sorted(labels))
        return f"{name}{{{label_str}}}"


# Module-level singleton used by the dispatch path. Importing
# ``services.mqtt.metrics.metrics`` anywhere gives a single shared instance
# — matches the singleton pattern in ``repositories.device_metric_repo`` and
# ``config`` helpers. Test isolation comes from :meth:`MqttMetrics.reset`.
metrics = MqttMetrics()
