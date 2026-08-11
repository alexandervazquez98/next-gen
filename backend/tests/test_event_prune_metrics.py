"""Strict-TDD tests for ``backend/services/event_prune_metrics.py``.

PR #1 of fix-423: in-process observability for the auto-prune path that ships
in PR #2. The scheduler tick and manual prune converge on this module so
``GET /api/system/status`` can expose the gauges without hitting Neo4j on
every poll (the dashboard polls every 3 s; per-request Cypher would 20x
the DB load).

Tests cover:

* ``record_recovered_stale`` / ``record_pruned`` counters and the
  ``last_run_closed_count`` gauge all surface in the snapshot under their
  declared names.
* ``reset_for_tests`` clears state so the test suite never bleeds counters
  across cases.
* Snapshot shape is stable: ``recovered_stale_total``, ``pruned_total``,
  ``last_run_at``, ``last_run_closed_count`` — every key REQ-OBS-PRUNE-003
  declares.
"""

from __future__ import annotations


def _load_module():
    """Import the metrics module (red until implemented)."""
    from services import event_prune_metrics as module

    return module


class TestEventPruneMetricsSnapshot:
    """RED -> GREEN: snapshot shape contract."""

    def test_snapshot_exposes_declared_keys(self, monkeypatch):
        module = _load_module()
        module.reset_event_prune_observability_for_tests()

        snapshot = module.get_event_prune_observability_snapshot()

        # REQ-OBS-PRUNE-001/002/003 declare these keys.
        for key in (
            "recovered_stale_total",
            "pruned_total",
            "last_run_at",
            "last_run_closed_count",
        ):
            assert key in snapshot, (
                f"Prune observability snapshot missing required key {key!r}; "
                f"got keys={sorted(snapshot.keys())!r}"
            )

    def test_initial_snapshot_has_zero_counters_and_null_run_at(self, monkeypatch):
        module = _load_module()
        module.reset_event_prune_observability_for_tests()

        snapshot = module.get_event_prune_observability_snapshot()

        assert snapshot["recovered_stale_total"] == 0
        assert snapshot["pruned_total"] == 0
        assert snapshot["last_run_closed_count"] == 0
        # last_run_at is None until the first scheduler tick records a run.
        assert snapshot["last_run_at"] is None

    def test_record_recovered_stale_increments_gauge(self, monkeypatch):
        module = _load_module()
        module.reset_event_prune_observability_for_tests()

        module.record_recovered_stale(7)
        module.record_recovered_stale(3)

        snapshot = module.get_event_prune_observability_snapshot()
        assert snapshot["recovered_stale_total"] == 10

    def test_record_pruned_increments_counter_and_captures_last_run(self, monkeypatch):
        module = _load_module()
        module.reset_event_prune_observability_for_tests()

        module.record_pruned(closed_count=5)
        module.record_pruned(closed_count=2)

        snapshot = module.get_event_prune_observability_snapshot()
        assert snapshot["pruned_total"] == 2
        # last_run_closed_count reflects the most recent tick, not the total.
        assert snapshot["last_run_closed_count"] == 2
        # last_run_at must be populated after the first tick.
        assert snapshot["last_run_at"] is not None

    def test_record_pruned_with_zero_does_not_increment_counter(self, monkeypatch):
        """REQ-OBS-PRUNE-002 scenario: empty batch does not increment."""
        module = _load_module()
        module.reset_event_prune_observability_for_tests()

        module.record_pruned(closed_count=0)
        module.record_pruned(closed_count=0)

        snapshot = module.get_event_prune_observability_snapshot()
        assert snapshot["pruned_total"] == 0
        # last_run_at is still recorded (a tick happened), but closed count is 0.
        assert snapshot["last_run_closed_count"] == 0
        assert snapshot["last_run_at"] is not None

    def test_record_pruned_overwrites_last_run_closed_count(self, monkeypatch):
        """Each scheduler tick overwrites last_run_closed_count with that tick's count."""
        module = _load_module()
        module.reset_event_prune_observability_for_tests()

        module.record_pruned(closed_count=10)
        assert module.get_event_prune_observability_snapshot()["last_run_closed_count"] == 10

        module.record_pruned(closed_count=3)
        snapshot = module.get_event_prune_observability_snapshot()
        assert snapshot["last_run_closed_count"] == 3
        # Counter accumulates across ticks (per-batch).
        assert snapshot["pruned_total"] == 2


class TestEventPruneMetricsReset:
    """Strict-TDD: ``reset_event_prune_observability_for_tests`` clears all state."""

    def test_reset_clears_counter_and_gauge_and_last_run(self, monkeypatch):
        module = _load_module()
        module.record_recovered_stale(42)
        module.record_pruned(closed_count=9)

        module.reset_event_prune_observability_for_tests()
        snapshot = module.get_event_prune_observability_snapshot()

        assert snapshot["recovered_stale_total"] == 0
        assert snapshot["pruned_total"] == 0
        assert snapshot["last_run_closed_count"] == 0
        assert snapshot["last_run_at"] is None
