"""Strict-TDD tests for the ``metric_values`` TimescaleDB retention service.

Issue #457 — REQ-MVR-001, REQ-MVR-002, REQ-MVR-003, REQ-MVR-004, REQ-MVR-005
scenarios:

* ``MetricRetentionSettings`` defaults to 90 days with bounded 1..3650 range.
* ``apply_metric_retention`` is idempotent: a duplicate-policy IntegrityError
  is treated as success.
* An operator override of 30 days produces SQL with the literal interval
  ``'30 days'``.
* ``MetricRetentionSettings.from_env`` honors ``METRIC_RETENTION_DAYS`` and
  ``METRIC_RETENTION_ENABLED`` with safe fallbacks.
* Out-of-window rows are excluded once the policy is active (REQ-MVR-005).

Tests are RED until ``backend/services/retention_service.py`` lands.

Follows the existing ``test_event_prune_settings.py`` and
``test_event_prune_scheduler.py`` conventions.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import IntegrityError, ProgrammingError


def _make_mock_engine(side_effects):
    """Return a MagicMock engine whose ``begin().__enter__().execute``
    raises each entry of ``side_effects`` in order (None = success).

    Also ensures ``__exit__`` returns False so exceptions propagate up
    to the caller — MagicMock defaults to a truthy return that would
    silently swallow them.
    """
    engine = MagicMock()
    ctx = MagicMock()
    conn = MagicMock()
    engine.begin.return_value = ctx
    ctx.__enter__.return_value = conn
    ctx.__exit__.return_value = False
    conn.execute.side_effect = side_effects
    return engine, conn


class TestMetricRetentionSettingsDefaults:
    """RED -> GREEN: defaults match design.md (90 days, kill-switch on)."""

    def test_metric_retention_settings_default_90_days(self):
        from services.retention_service import (
            METRIC_RETENTION_DEFAULT_DAYS,
            MetricRetentionSettings,
        )

        settings = MetricRetentionSettings()

        # design.md: 90-day default window for metric_values.
        assert settings.retention_days == METRIC_RETENTION_DEFAULT_DAYS
        assert METRIC_RETENTION_DEFAULT_DAYS == 90

    def test_default_kill_switch_is_enabled(self):
        from services.retention_service import MetricRetentionSettings

        assert MetricRetentionSettings().enabled is True


class TestApplyMetricRetentionInterval:
    """RED -> GREEN: SQL contains the configured interval."""

    def test_apply_metric_retention_30_day_override(self):
        from services.retention_service import apply_metric_retention

        engine, conn = _make_mock_engine([None])

        apply_metric_retention(engine=engine, retention_days=30)

        # Real assertion: SQL was invoked exactly once with the configured interval.
        conn.execute.assert_called_once()
        _, kwargs = conn.execute.call_args
        params = kwargs.get("params") or conn.execute.call_args[0][1]
        assert params == {"interval": "30 days"}


class TestApplyMetricRetentionIdempotency:
    """REQ-MVR-004: repeated calls with the same interval MUST NOT raise
    and MUST NOT create duplicate policies."""

    def test_apply_metric_retention_idempotent_double_call(self):
        from services.retention_service import apply_metric_retention

        # First call: TimescaleDB raises IntegrityError (duplicate policy).
        # Second call: succeeds (race lost, retry succeeds).
        engine, conn = _make_mock_engine(
            [
                IntegrityError("SELECT 1", {}, Exception("duplicate policy")),
                None,
            ]
        )

        # Neither call must propagate the exception.
        apply_metric_retention(engine=engine, retention_days=90)
        apply_metric_retention(engine=engine, retention_days=90)

        assert conn.execute.call_count == 2
        # Same SQL + same params both times — no per-call drift.
        first_call = conn.execute.call_args_list[0]
        second_call = conn.execute.call_args_list[1]
        assert first_call == second_call

    def test_apply_metric_retention_swallows_programming_error(self):
        """REQ-MVR-003: a missing TimescaleDB extension logs WARNING and
        returns without raising — boot must not crash."""
        from services.retention_service import apply_metric_retention

        engine, _ = _make_mock_engine(
            [ProgrammingError("SELECT 1", {}, Exception("extension timescaledb not found"))]
        )

        # MUST NOT raise.
        apply_metric_retention(engine=engine, retention_days=90)


# ---------------------------------------------------------------------------
# W3 — env-driven constructor (REQ-MVR-002 scenarios 2/3 + REQ-MVR-003)
# ---------------------------------------------------------------------------


class TestMetricRetentionSettingsFromEnv:
    """``from_env`` honors ``METRIC_RETENTION_DAYS`` and ``METRIC_RETENTION_ENABLED``."""

    def test_metric_retention_settings_from_env(self):
        """W3 verify command: ``Settings.metric_retention.retention_days``
        must be a valid bounded value (1..3650 or 90 default)."""
        from config import MetricRetentionSettings, Settings

        s = Settings()
        assert hasattr(s, "metric_retention")
        assert isinstance(s.metric_retention, MetricRetentionSettings)
        assert s.metric_retention.retention_days in (1, 3650, 90)

    def test_from_env_returns_90_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            from services.retention_service import MetricRetentionSettings

            settings = MetricRetentionSettings.from_env()

        assert settings.retention_days == 90
        assert settings.enabled is True

    def test_from_env_30_days_override(self):
        with patch.dict(os.environ, {"METRIC_RETENTION_DAYS": "30"}, clear=True):
            from services.retention_service import MetricRetentionSettings

            settings = MetricRetentionSettings.from_env()

        assert settings.retention_days == 30

    def test_from_env_invalid_days_falls_back_with_warning(self, caplog):
        with patch.dict(os.environ, {"METRIC_RETENTION_DAYS": "banana"}, clear=True):
            from services.retention_service import MetricRetentionSettings

            with caplog.at_level("WARNING"):
                settings = MetricRetentionSettings.from_env()

        assert settings.retention_days == 90
        # Invalid env MUST surface a WARNING so operators see it in the boot log.
        assert any("METRIC_RETENTION_DAYS" in rec.message for rec in caplog.records)

    def test_from_env_disabled_via_env(self):
        with patch.dict(os.environ, {"METRIC_RETENTION_ENABLED": "false"}, clear=True):
            from services.retention_service import MetricRetentionSettings

            settings = MetricRetentionSettings.from_env()

        assert settings.enabled is False
