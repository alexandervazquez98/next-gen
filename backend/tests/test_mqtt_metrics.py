"""Tests for :class:`MqttMetrics` (PR4).

The metrics module is a small, in-process counter store for the subscriber.
It is intentionally NOT a Prometheus client — it just exposes a dict-shaped
snapshot that callers (or a future emission layer) can scrape. Tests cover
the public surface: incrementing, label determinism, snapshot shape, reset,
and thread-safety under concurrent increments.
"""

from __future__ import annotations

import threading

import pytest

pytestmark = [pytest.mark.unit]


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def metrics():
    """Fresh :class:`MqttMetrics` per test — no global state to clear."""
    from services.mqtt.metrics import MqttMetrics

    return MqttMetrics()


# ── Task 4.2: counter API ──────────────────────────────────────────────────


class TestMqttMetricsIncrement:
    """``inc()`` adds to the right key, with or without labels."""

    def test_inc_increments(self, metrics):
        """Two ``inc("foo")`` calls → snapshot shows ``foo=2``."""
        metrics.inc("foo")
        metrics.inc("foo")
        snap = metrics.snapshot()
        assert snap["foo"] == 2

    def test_inc_with_labels(self, metrics):
        """Labels form the key suffix and start at 1."""
        metrics.inc("parsed_ok", parser="bliiot")
        snap = metrics.snapshot()
        # Key format: name{label=value,...} with labels sorted alphabetically.
        assert snap["parsed_ok{parser=bliiot}"] == 1


class TestMqttMetricsShape:
    """The snapshot / reset contract must hold."""

    def test_snapshot_returns_dict(self, metrics):
        """``snapshot()`` returns a fresh ``dict[str, int]``."""
        metrics.inc("a")
        snap = metrics.snapshot()
        assert isinstance(snap, dict)
        assert all(isinstance(k, str) for k in snap)
        assert all(isinstance(v, int) for v in snap.values())

    def test_reset_clears(self, metrics):
        """``reset()`` empties every counter — used by tests and ops tooling."""
        metrics.inc("foo")
        metrics.inc("bar", parser="x")
        metrics.reset()
        assert metrics.snapshot() == {}


class TestMqttMetricsKeyDeterminism:
    """Same labels in different order must produce the same key."""

    def test_keys_are_deterministic(self, metrics):
        """``inc(a=1, b=2)`` and ``inc(b=2, a=1)`` share a key."""
        metrics.inc("event", a="1", b="2")
        metrics.inc("event", b="2", a="1")
        snap = metrics.snapshot()
        # Exactly one key, value == 2.
        assert len(snap) == 1
        ((key, count),) = snap.items()
        assert key == "event{a=1,b=2}"
        assert count == 2


class TestMqttMetricsThreadSafety:
    """The lock must serialize concurrent ``inc()`` calls."""

    def test_concurrent_increments_are_safe(self, metrics):
        """10 threads × 1000 inc → final count == 10000 (no lost updates)."""
        # The `metrics` fixture gives us a fresh instance; the comment
        # below explains why no module-level singleton is involved.
        barrier = threading.Barrier(10)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                barrier.wait()  # Release all threads simultaneously.
                for _ in range(1000):
                    metrics.inc("hits")
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert metrics.snapshot()["hits"] == 10_000
