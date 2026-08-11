"""Strict-TDD tests for the ``collector.prune`` namespace in system status.

PR #1 of fix-423: ``_build_system_status_payload`` must surface the
``EventPruneMetrics`` snapshot under ``collector.prune`` so the dashboard
(and operators) can poll RECOVERED-stale and pruned counters every 3 s
without a Neo4j round-trip.

Mirrors the existing ``test_build_system_status_payload_includes_event_lock_snapshot_*``
tests in ``backend/tests/test_system_status.py``; uses the same monkeypatch
pattern so no live database is required.
"""
from __future__ import annotations

import logging

import main


class _FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args, **_kwargs):
        return None


class _FakeEngine:
    def connect(self):
        return _FakeConnection()


def _patch_neo4j_and_postgres(monkeypatch):
    monkeypatch.setattr(main, "verify_connection", lambda max_retries=1, retry_delay=0: None)
    monkeypatch.setattr(main, "_get_disk_io_status", lambda: {"supported": False})
    monkeypatch.setattr(main, "get_collector_status", lambda: {"status": "RUNNING", "stats": {}})
    monkeypatch.setattr(main, "_build_time_sync_status", lambda: {"status": "OK"})
    monkeypatch.setattr("postgres_db.engine", _FakeEngine())


class TestCollectorPrunePayload:
    """RED -> GREEN: collector.prune namespace contract."""

    def test_collector_prune_namespace_carries_event_prune_snapshot(self, monkeypatch):
        expected_prune = {
            "recovered_stale_total": 12,
            "pruned_total": 3,
            "last_run_at": "2026-01-01T00:00:00Z",
            "last_run_closed_count": 4,
        }
        _patch_neo4j_and_postgres(monkeypatch)
        monkeypatch.setattr(
            "services.event_lock.get_event_lock_observability_snapshot",
            lambda: {"alert_state": "OK"},
        )
        monkeypatch.setattr(
            "services.event_prune_metrics.get_event_prune_observability_snapshot",
            lambda: expected_prune,
        )

        status = main._build_system_status_payload()

        assert status["collector"]["prune"] == expected_prune, (
            f"collector.prune must carry the EventPruneMetrics snapshot; "
            f"got {status['collector']['prune']!r}"
        )
        # Other service fields are unchanged.
        assert status["neo4j"] == "CONNECTED"
        assert status["postgres"] == "CONNECTED"
        assert status["collector"]["status"] == "RUNNING"
        assert status["event_lock"] == {"alert_state": "OK"}

    def test_collector_prune_falls_back_when_snapshot_raises(self, monkeypatch, caplog):
        _patch_neo4j_and_postgres(monkeypatch)
        monkeypatch.setattr(
            "services.event_lock.get_event_lock_observability_snapshot",
            lambda: {"alert_state": "OK"},
        )

        def raise_prune_error():
            raise RuntimeError("prune snapshot unavailable")

        monkeypatch.setattr(
            "services.event_prune_metrics.get_event_prune_observability_snapshot",
            raise_prune_error,
        )

        with caplog.at_level(logging.WARNING, logger="main"):
            status = main._build_system_status_payload()

        assert status["collector"]["prune"] == {"snapshot_error": True}, (
            f"Fallback prune payload must carry snapshot_error; got "
            f"{status['collector']['prune']!r}"
        )
        # Service-level fields are preserved even when the snapshot fails.
        assert status["neo4j"] == "CONNECTED"
        assert status["postgres"] == "CONNECTED"
        assert status["collector"]["status"] == "RUNNING"
        assert "Failed to build event prune observability snapshot" in caplog.text

    def test_collector_prune_namespace_is_initialized_to_zero_for_fresh_process(
        self, monkeypatch
    ):
        """Fresh process exposes the four declared keys at zero before any tick."""
        from services import event_prune_metrics

        event_prune_metrics.reset_event_prune_observability_for_tests()
        _patch_neo4j_and_postgres(monkeypatch)
        monkeypatch.setattr(
            "services.event_lock.get_event_lock_observability_snapshot",
            lambda: {"alert_state": "OK"},
        )

        status = main._build_system_status_payload()

        prune = status["collector"]["prune"]
        assert prune["recovered_stale_total"] == 0
        assert prune["pruned_total"] == 0
        assert prune["last_run_closed_count"] == 0
        assert prune["last_run_at"] is None
