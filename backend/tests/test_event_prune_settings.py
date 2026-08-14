"""Strict-TDD tests for ``backend/config.py:EventPruneSettings``.

PR #2 of fix-423: EventPruneSettings is the Pydantic config object that drives
the auto-prune scheduler registration on ``backup_scheduler``. REQ-PRUNE-003
scenarios require:

* Defaults that match the design (1h interval, batch size borrowed from
  EventBatchSettings, stale threshold 3600 s, kill-switch default true).
* Env-var overrides for every field with safe parse + minimum guards.
* Invalid types fall back to defaults without crashing (mirror the existing
  ``_parse_system_status_int`` / ``_parse_system_status_bool`` idiom in
  ``main.py:45-71``).

Tests are RED until ``EventPruneSettings`` and its ``from_env`` classmethod
land in ``backend/config.py``.

Follows the existing ``test_polling_pipeline_config.py`` pattern (``from config
import X`` + ``patch.dict(os.environ, ..., clear=True)``).
"""

from __future__ import annotations

from unittest.mock import patch


class TestEventPruneSettingsDefaults:
    """RED -> GREEN: defaults that match design.md §Observability."""

    def test_defaults_match_design(self):
        from config import EventBatchSettings, EventPruneSettings

        settings = EventPruneSettings()

        # design.md §Observability: default interval 3600s, stale threshold 3600s.
        assert settings.enabled is True
        assert settings.interval_seconds == 3600
        # Default batch size borrows from EventBatchSettings.batch_size (500).
        assert settings.batch_size == EventBatchSettings().batch_size
        assert settings.stale_after_seconds == 3600

    def test_from_env_returns_defaults_when_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            from config import EventBatchSettings, EventPruneSettings

            settings = EventPruneSettings.from_env()

        assert settings.enabled is True
        assert settings.interval_seconds == 3600
        assert settings.batch_size == EventBatchSettings().batch_size
        assert settings.stale_after_seconds == 3600


class TestEventPruneSettingsEnvOverrides:
    """RED -> GREEN: env vars override every field with safe parse."""

    def test_enabled_false_via_env(self):
        with patch.dict("os.environ", {"EVENT_PRUNE_ENABLED": "false"}, clear=True):
            from config import EventPruneSettings

            settings = EventPruneSettings.from_env()

        assert settings.enabled is False

    def test_interval_seconds_override(self):
        with patch.dict("os.environ", {"EVENT_PRUNE_INTERVAL_SECONDS": "120"}, clear=True):
            from config import EventPruneSettings

            settings = EventPruneSettings.from_env()

        assert settings.interval_seconds == 120

    def test_batch_size_override(self):
        with patch.dict("os.environ", {"EVENT_PRUNE_BATCH_SIZE": "250"}, clear=True):
            from config import EventPruneSettings

            settings = EventPruneSettings.from_env()

        assert settings.batch_size == 250

    def test_stale_after_seconds_override(self):
        with patch.dict("os.environ", {"EVENT_PRUNE_STALE_AFTER_SECONDS": "7200"}, clear=True):
            from config import EventPruneSettings

            settings = EventPruneSettings.from_env()

        assert settings.stale_after_seconds == 7200


class TestEventPruneSettingsInvalidInput:
    """RED -> GREEN: invalid input falls back to defaults without raising.

    Mirrors ``_parse_system_status_int`` / ``_parse_system_status_bool`` in
    ``main.py:45-71`` — a malformed env var logs a warning and uses the
    default rather than crashing the API process.
    """

    def test_invalid_interval_seconds_falls_back_to_default(self):
        with patch.dict("os.environ", {"EVENT_PRUNE_INTERVAL_SECONDS": "not-a-number"}, clear=True):
            from config import EventPruneSettings

            settings = EventPruneSettings.from_env()

        assert settings.interval_seconds == 3600

    def test_invalid_batch_size_falls_back_to_default(self):
        with patch.dict("os.environ", {"EVENT_PRUNE_BATCH_SIZE": "oops"}, clear=True):
            from config import EventBatchSettings, EventPruneSettings

            settings = EventPruneSettings.from_env()

        # Default borrows from EventBatchSettings — 500 in HEAD.
        assert settings.batch_size == EventBatchSettings().batch_size

    def test_invalid_stale_after_seconds_falls_back_to_default(self):
        with patch.dict("os.environ", {"EVENT_PRUNE_STALE_AFTER_SECONDS": "abc"}, clear=True):
            from config import EventPruneSettings

            settings = EventPruneSettings.from_env()

        assert settings.stale_after_seconds == 3600

    def test_invalid_enabled_falls_back_to_true(self):
        """Mirrors ``SYSTEM_STATUS_SNAPSHOTS_ENABLED`` parsing — invalid value
        falls back to True (the safe default) so the scheduler can still run
        unless the operator explicitly opted out."""
        with patch.dict("os.environ", {"EVENT_PRUNE_ENABLED": "banana"}, clear=True):
            from config import EventPruneSettings

            settings = EventPruneSettings.from_env()

        assert settings.enabled is True
