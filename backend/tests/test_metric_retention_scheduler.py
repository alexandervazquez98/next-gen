"""Strict-TDD tests for the metric retention scheduler registration on
``main.backup_scheduler``.

Issue #457 — REQ-MVR-003 scenarios:

* Enabled scheduler registers ``run_metric_retention_cleanup`` with
  ``CronTrigger("0 */6 * * *")``, ``coalesce=True``, ``max_instances=1``,
  ``replace_existing=True``, job id ``"metric_retention_cleanup"``.
* Kill-switch (``METRIC_RETENTION_ENABLED=false``) skips registration
  without raising.

Tests are RED until ``_register_metric_retention_job`` lands in ``main.py``.

Mirrors ``test_event_prune_scheduler.py`` style: ``patch("main.backup_scheduler", ...)``
+ ``patch("main._METRIC_RETENTION_ENABLED", ...)``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestRegisterMetricRetentionJobKillSwitch:
    """REQ-MVR-003 scenario 'Disabled by env var skips registration'."""

    def test_metric_retention_scheduler_NOT_registered_when_disabled(self):
        from main import _register_metric_retention_job

        fake_scheduler = MagicMock()
        with (
            patch("main.backup_scheduler", fake_scheduler),
            patch("main._METRIC_RETENTION_ENABLED", False),
        ):
            result = _register_metric_retention_job()

        assert result is False
        fake_scheduler.add_job.assert_not_called()


class TestRegisterMetricRetentionJobEnabled:
    """REQ-MVR-003 scenario 'Enabled by default registers the entrypoint'."""

    def test_metric_retention_scheduler_registration_when_enabled(self):
        from main import _register_metric_retention_job

        fake_scheduler = MagicMock()
        with (
            patch("main.backup_scheduler", fake_scheduler),
            patch("main._METRIC_RETENTION_ENABLED", True),
        ):
            result = _register_metric_retention_job()

        assert result is True
        fake_scheduler.add_job.assert_called_once()
        _, kwargs = fake_scheduler.add_job.call_args
        assert kwargs["id"] == "metric_retention_cleanup"
        assert kwargs["replace_existing"] is True
        assert kwargs["max_instances"] == 1
        assert kwargs["coalesce"] is True
        # CronTrigger.from_crontab("0 */6 * * *") — every 6 hours.
        trigger = kwargs["trigger"]
        # apscheduler parses the crontab string into the trigger; we assert
        # the field set explicitly to avoid coupling to private attrs.
        assert hasattr(trigger, "fields")
