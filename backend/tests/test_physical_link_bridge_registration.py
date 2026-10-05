"""Tests for the PhysicalLink polling bridge scheduler registration — feat-443 (PR1).

The bridge is registered as an APScheduler ``IntervalTrigger`` job on
``backup_scheduler`` (mirrors the existing ``_register_*_job`` pattern).

TDD task coverage: T6.
"""

from __future__ import annotations

from unittest.mock import MagicMock


def _set_feature_flag(monkeypatch, enabled: bool) -> None:
    """Set the env var that the main module's reload helper reads."""
    monkeypatch.setenv(
        "FEATURE_CMDB_PHYSICAL_LINK_POLLING_ENABLED",
        "true" if enabled else "false",
    )


class TestRegisterPhysicalLinkPollingBridgeJob:
    """T6: registration is a no-op when off; registers an IntervalTrigger when on."""

    def test_is_noop_when_feature_disabled(self, monkeypatch):
        from main import _register_physical_link_polling_bridge_job

        _set_feature_flag(monkeypatch, enabled=False)
        fake_scheduler = MagicMock()
        monkeypatch.setattr("main.backup_scheduler", fake_scheduler)
        # Mutate the module-level flag directly — the registration
        # function reads ``main._PHYSICAL_LINK_POLLING_ENABLED`` which
        # is populated from env on import.
        monkeypatch.setattr("main._PHYSICAL_LINK_POLLING_ENABLED", False)

        result = _register_physical_link_polling_bridge_job()

        assert result is False
        fake_scheduler.add_job.assert_not_called()

    def test_registers_interval_job_when_feature_enabled(self, monkeypatch):
        from main import _register_physical_link_polling_bridge_job

        _set_feature_flag(monkeypatch, enabled=True)
        fake_scheduler = MagicMock()
        monkeypatch.setattr("main.backup_scheduler", fake_scheduler)
        monkeypatch.setattr("main._PHYSICAL_LINK_POLLING_ENABLED", True)
        monkeypatch.setattr("main._PHYSICAL_LINK_POLLING_INTERVAL_SECONDS", 60)

        result = _register_physical_link_polling_bridge_job()

        assert result is True
        fake_scheduler.add_job.assert_called_once()
        # The positional first arg is the bridge entry point; we just
        # verify it's callable. The lazy import in the registration
        # function makes a strict identity check brittle.
        args, kwargs = fake_scheduler.add_job.call_args
        assert callable(args[0])
        assert kwargs["id"] == "physical_link_polling_bridge"
        assert kwargs["name"] == "PhysicalLink Polling Bridge"
        assert kwargs["replace_existing"] is True
        assert kwargs["max_instances"] == 1
        assert kwargs["coalesce"] is True
        trigger = kwargs["trigger"]
        # APScheduler IntervalTrigger exposes the interval as a
        # ``timedelta`` on ``.interval`` (matches the assertion in
        # ``test_register_system_status_snapshot_job_registers_interval_job``).
        assert trigger.interval.total_seconds() == 60
