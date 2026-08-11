"""Strict-TDD tests for the auto-prune scheduler registration.

PR #2 of fix-423. REQ-PRUNE-003 scenarios:

* Enabled scheduler fires the run_prune_recovered_events job on
  ``backup_scheduler`` with ``IntervalTrigger``, ``coalesce=True``,
  ``max_instances=1``, ``replace_existing=True``.
* Kill-switch (``EVENT_PRUNE_ENABLED=false``) skips registration
  without raising.
* ``run_prune_recovered_events_sync`` acquires ``prune_lock``,
  calls ``prune_recovered_events``, records metrics, releases the lock.

Tests are RED until ``_register_event_prune_job`` and
``run_prune_recovered_events_sync`` land in main.py / event_service.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestRegisterEventPruneJobKillSwitch:
    """REQ-PRUNE-003 scenario 'Kill-switch skips execution'."""

    def test_disabled_returns_false_without_adding_job(self):
        from main import _register_event_prune_job

        fake_scheduler = MagicMock()
        with patch("main.backup_scheduler", fake_scheduler), patch(
            "main._EVENT_PRUNE_ENABLED", False
        ):
            result = _register_event_prune_job()

        assert result is False
        fake_scheduler.add_job.assert_not_called()

    def test_enabled_registers_interval_job_with_required_knobs(self):
        from main import _register_event_prune_job

        fake_scheduler = MagicMock()
        with patch("main.backup_scheduler", fake_scheduler), patch(
            "main._EVENT_PRUNE_ENABLED", True
        ), patch("main._EVENT_PRUNE_INTERVAL_SECONDS", 900):
            result = _register_event_prune_job()

        assert result is True
        fake_scheduler.add_job.assert_called_once()
        _, kwargs = fake_scheduler.add_job.call_args
        assert kwargs["id"] == "run_prune_recovered_events"
        assert kwargs["replace_existing"] is True
        assert kwargs["max_instances"] == 1
        assert kwargs["coalesce"] is True
        trigger = kwargs["trigger"]
        assert trigger.interval.total_seconds() == 900


class TestRegisterEventPruneJobHooks:
    """The job body MUST delegate to ``run_prune_recovered_events_sync``."""

    def test_job_callback_is_sync_entrypoint(self):
        from main import _register_event_prune_job

        fake_scheduler = MagicMock()
        with patch("main.backup_scheduler", fake_scheduler), patch(
            "main._EVENT_PRUNE_ENABLED", True
        ), patch("main._EVENT_PRUNE_INTERVAL_SECONDS", 3600):
            _register_event_prune_job()

        callback = fake_scheduler.add_job.call_args[0][0]
        # The callback should be the sync entrypoint — name match avoids
        # importing event_service here (which would create a hard import
        # edge that complicates module reloading in other tests).
        assert callable(callback)
        assert getattr(callback, "__name__", "") == "run_prune_recovered_events_sync"


class TestEventPruneSettingsReExport:
    """``main.py`` must surface the configured interval via a module-level
    constant so the registration function can read it without re-parsing
    env vars every tick.
    """

    def test_module_exposes_event_prune_enabled_flag(self):
        import main

        assert hasattr(main, "_EVENT_PRUNE_ENABLED")
        assert isinstance(main._EVENT_PRUNE_ENABLED, bool)

    def test_module_exposes_event_prune_interval_seconds(self):
        import main

        assert hasattr(main, "_EVENT_PRUNE_INTERVAL_SECONDS")
        assert isinstance(main._EVENT_PRUNE_INTERVAL_SECONDS, int)
        assert main._EVENT_PRUNE_INTERVAL_SECONDS > 0


class TestRunPruneRecoveredEventsSync:
    """The sync entrypoint must acquire/release the prune lock and record
    metrics, mirroring AD-8 (lock contract) + AD-5 (per-batch counter).
    """

    def test_sync_entrypoint_acquires_lock_runs_prune_records_metrics_releases(
        self,
    ):
        from services import event_service
        from services.event_prune_metrics import reset_event_prune_observability_for_tests

        reset_event_prune_observability_for_tests()

        fake_lock = MagicMock()
        fake_lock.acquire_prune_lock.return_value = True
        fake_lock.release_prune_lock.return_value = True
        fake_prune = MagicMock(return_value={"message": "ok", "count": 7})

        with patch.object(event_service, "acquire_prune_lock", fake_lock.acquire_prune_lock), patch.object(
            event_service, "release_prune_lock", fake_lock.release_prune_lock
        ), patch.object(event_service, "prune_recovered_events", fake_prune):
            count = event_service.run_prune_recovered_events_sync()

        assert count == 7
        fake_lock.acquire_prune_lock.assert_called_once()
        fake_lock.release_prune_lock.assert_called_once()
        fake_prune.assert_called_once_with("system-prune")
        snapshot = (
            event_service.get_event_prune_observability_snapshot()
            if hasattr(event_service, "get_event_prune_observability_snapshot")
            else __import__(
                "services.event_prune_metrics", fromlist=["get_event_prune_observability_snapshot"]
            ).get_event_prune_observability_snapshot()
        )
        assert snapshot["pruned_total"] == 1
        assert snapshot["last_run_closed_count"] == 7

    def test_sync_entrypoint_returns_zero_when_lock_held(self):
        """If the lock is held by an operator, the scheduler tick returns 0
        without crashing (AD-8)."""
        from services import event_service

        fake_lock = MagicMock()
        fake_lock.acquire_prune_lock.return_value = False
        fake_lock.release_prune_lock.return_value = False
        fake_prune = MagicMock(return_value={"message": "should not run", "count": 99})

        with patch.object(event_service, "acquire_prune_lock", fake_lock.acquire_prune_lock), patch.object(
            event_service, "release_prune_lock", fake_lock.release_prune_lock
        ), patch.object(event_service, "prune_recovered_events", fake_prune):
            count = event_service.run_prune_recovered_events_sync()

        assert count == 0
        fake_prune.assert_not_called()
        fake_lock.release_prune_lock.assert_not_called()

    def test_sync_entrypoint_releases_lock_even_when_prune_raises(self):
        """If ``prune_recovered_events`` raises, the lock MUST be released."""
        import contextlib

        from services import event_service

        fake_lock = MagicMock()
        fake_lock.acquire_prune_lock.return_value = True
        fake_lock.release_prune_lock.return_value = True
        fake_prune = MagicMock(side_effect=RuntimeError("neo4j exploded"))

        with patch.object(event_service, "acquire_prune_lock", fake_lock.acquire_prune_lock), patch.object(
            event_service, "release_prune_lock", fake_lock.release_prune_lock
        ), patch.object(event_service, "prune_recovered_events", fake_prune), contextlib.suppress(
            RuntimeError
        ):
            event_service.run_prune_recovered_events_sync()

        fake_lock.release_prune_lock.assert_called_once()

    def test_sync_entrypoint_uses_owner_scheduler(self):
        from services import event_service

        fake_lock = MagicMock()
        fake_lock.acquire_prune_lock.return_value = True
        fake_lock.release_prune_lock.return_value = True
        fake_prune = MagicMock(return_value={"count": 0})

        with patch.object(event_service, "acquire_prune_lock", fake_lock.acquire_prune_lock), patch.object(
            event_service, "release_prune_lock", fake_lock.release_prune_lock
        ), patch.object(event_service, "prune_recovered_events", fake_prune):
            event_service.run_prune_recovered_events_sync()

        owner_arg = fake_lock.acquire_prune_lock.call_args.kwargs.get("owner")
        assert owner_arg == "scheduler"

    def test_sync_entrypoint_zero_closed_count_does_not_increment_pruned_total(
        self,
    ):
        """REQ-OBS-PRUNE-002: empty batch does not increment the counter."""
        from services import event_service
        from services.event_prune_metrics import reset_event_prune_observability_for_tests

        reset_event_prune_observability_for_tests()

        fake_lock = MagicMock()
        fake_lock.acquire_prune_lock.return_value = True
        fake_lock.release_prune_lock.return_value = True
        fake_prune = MagicMock(return_value={"count": 0})

        with patch.object(event_service, "acquire_prune_lock", fake_lock.acquire_prune_lock), patch.object(
            event_service, "release_prune_lock", fake_lock.release_prune_lock
        ), patch.object(event_service, "prune_recovered_events", fake_prune):
            event_service.run_prune_recovered_events_sync()

        from services.event_prune_metrics import get_event_prune_observability_snapshot

        snapshot = get_event_prune_observability_snapshot()
        assert snapshot["pruned_total"] == 0
        assert snapshot["last_run_closed_count"] == 0
