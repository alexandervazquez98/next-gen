# backend/tests/test_snmp_worker.py
"""
Unit tests for backend/engines/snmp_worker.py
Tests ICMP polling: fetch_icmp_ping retry logic and debounce counter behavior.
"""

import pytest
from unittest.mock import patch, MagicMock
import sys
import os

# Ensure backend root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the conftest MockNeo4jSession for proper mocking
from tests.conftest import MockNeo4jSession, MockNeo4jDriver


class TestICMPSettings:
    """Tests for ICMPSettings class in config.py."""

    def test_icmp_settings_defaults(self):
        """ICMPSettings has correct defaults."""
        from config import ICMPSettings
        settings = ICMPSettings()
        assert settings.timeout_ms == 3000
        assert settings.retries == 2
        assert settings.debounce_count == 3

    def test_icmp_settings_from_env_override(self):
        """ICMPSettings.from_env reads env vars correctly."""
        from config import ICMPSettings
        with patch.dict(os.environ, {
            "ICMP_TIMEOUT_MS": "5000",
            "ICMP_RETRIES": "5",
            "ICMP_DEBOUNCE_COUNT": "7"
        }, clear=True):
            settings = ICMPSettings.from_env()
            assert settings.timeout_ms == 5000
            assert settings.retries == 5
            assert settings.debounce_count == 7

    def test_get_icmp_settings_singleton(self):
        """get_icmp_settings returns cached singleton."""
        from config import get_icmp_settings, ICMPSettings
        # Clear any cached value first
        import config as config_module
        config_module._icmp_settings = None

        settings1 = get_icmp_settings()
        settings2 = get_icmp_settings()
        assert settings1 is settings2  # same instance


class TestFetchICMPPing:
    """Tests for fetch_icmp_ping retry logic."""

    @patch("engines.snmp_worker.subprocess.run")
    def test_fetch_icmp_ping_success_first_attempt(self, mock_run):
        """Returns 1.0 when first ping succeeds."""
        mock_run.return_value = MagicMock(returncode=0)
        from engines.snmp_worker import fetch_icmp_ping
        result = fetch_icmp_ping("192.168.1.1", timeout_ms=3000, retries=2)
        assert result == 1.0
        assert mock_run.call_count == 1

    @patch("engines.snmp_worker.subprocess.run")
    def test_fetch_icmp_ping_success_on_retry(self, mock_run):
        """Returns 1.0 when retry succeeds after first failure."""
        mock_run.side_effect = [
            MagicMock(returncode=1),  # first attempt fails
            MagicMock(returncode=0),  # retry succeeds
        ]
        from engines.snmp_worker import fetch_icmp_ping
        result = fetch_icmp_ping("192.168.1.1", timeout_ms=3000, retries=2)
        assert result == 1.0
        assert mock_run.call_count == 2

    @patch("engines.snmp_worker.subprocess.run")
    def test_fetch_icmp_ping_all_retries_fail(self, mock_run):
        """Returns 0.0 when all attempts fail."""
        mock_run.return_value = MagicMock(returncode=1)
        from engines.snmp_worker import fetch_icmp_ping
        result = fetch_icmp_ping("192.168.1.1", timeout_ms=3000, retries=2)
        assert result == 0.0
        assert mock_run.call_count == 3  # 1 initial + 2 retries

    @patch("engines.snmp_worker.subprocess.run")
    def test_fetch_icmp_ping_zero_retries(self, mock_run):
        """With retries=0, stops after single attempt."""
        mock_run.return_value = MagicMock(returncode=1)
        from engines.snmp_worker import fetch_icmp_ping
        result = fetch_icmp_ping("192.168.1.1", timeout_ms=3000, retries=0)
        assert result == 0.0
        assert mock_run.call_count == 1

    @patch("engines.snmp_worker.subprocess.run")
    def test_fetch_icmp_ping_exception_fails_attempt(self, mock_run):
        """Exception during ping attempt fails that attempt, retry continues."""
        mock_run.side_effect = [
            Exception("network error"),  # first attempt throws
            MagicMock(returncode=0),      # retry succeeds
        ]
        from engines.snmp_worker import fetch_icmp_ping
        result = fetch_icmp_ping("192.168.1.1", timeout_ms=3000, retries=2)
        assert result == 1.0
        assert mock_run.call_count == 2


class TestICMPDebounce:
    """Tests for ICMP debounce counter in poll_snmp."""

    def _make_mock_driver_with_session(self, records):
        """Create a mock driver with a session that returns given records."""
        mock_driver = MockNeo4jDriver()
        mock_session = mock_driver.mock_session
        mock_session.set_response("match", records)
        mock_session.set_default_response([])
        return mock_driver, mock_session

    @patch("engines.snmp_worker.fetch_icmp_ping")
    @patch("engines.snmp_worker.bulk_insert_metrics")
    @patch("engines.snmp_worker.SessionLocal")
    def test_debounce_counter_below_threshold_no_event(
        self, mock_session_local, mock_bulk_insert, mock_fetch_icmp
    ):
        """Counter below debounce threshold does not create event."""
        from engines.snmp_worker import _consecutive_failures
        _consecutive_failures.clear()

        mock_fetch_icmp.return_value = 0.0  # ping fails

        mock_session = MockNeo4jSession()
        mock_session.set_response("match", [{
            "node_id": "ci-001",
            "metric_id": "PING-CHECK",
            "protocol": "ICMP",
            "ip": "192.168.1.1",
            "community": "public",
            "oid": None,
            "port": 161
        }])

        mock_session_local.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_local.return_value.__exit__ = MagicMock(return_value=None)

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        with patch("engines.snmp_worker.driver", mock_driver):
            from engines.snmp_worker import poll_snmp
            poll_snmp()

        # No CRITICAL status set because debounce_count=3 and we only have 1 failure
        critical_calls = [
            q for q in mock_session.queries
            if "set n.status" in q["query"].lower() and q["params"].get("status") == "CRITICAL"
        ]
        assert len(critical_calls) == 0, f"Unexpected CRITICAL calls: {critical_calls}"
        assert _consecutive_failures.get("ci-001", 0) == 1

    @patch("engines.snmp_worker.fetch_icmp_ping")
    @patch("engines.snmp_worker.bulk_insert_metrics")
    @patch("engines.snmp_worker.SessionLocal")
    def test_debounce_counter_at_threshold_creates_event(
        self, mock_session_local, mock_bulk_insert, mock_fetch_icmp
    ):
        """Counter reaches debounce threshold and creates CRITICAL event."""
        from engines.snmp_worker import _consecutive_failures
        _consecutive_failures.clear()

        mock_fetch_icmp.return_value = 0.0  # ping fails

        mock_session = MockNeo4jSession()
        mock_session.set_response("match", [{
            "node_id": "ci-001",
            "metric_id": "PING-CHECK",
            "protocol": "ICMP",
            "ip": "192.168.1.1",
            "community": "public",
            "oid": None,
            "port": 161
        }])

        mock_session_local.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_local.return_value.__exit__ = MagicMock(return_value=None)

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        with patch("engines.snmp_worker.driver", mock_driver):
            from engines.snmp_worker import poll_snmp

            # Simulate 3 consecutive failures
            for _ in range(3):
                poll_snmp()

        # After 3rd failure, CRITICAL status should be set
        critical_calls = [
            q for q in mock_session.queries
            if "set n.status" in q["query"].lower() and q["params"].get("status") == "CRITICAL"
        ]
        assert len(critical_calls) >= 1, f"Expected at least 1 CRITICAL call, got {len(critical_calls)}: {mock_session.queries}"
        # Counter resets after event
        assert _consecutive_failures.get("ci-001", 0) == 0

    @patch("engines.snmp_worker.fetch_icmp_ping")
    @patch("engines.snmp_worker.bulk_insert_metrics")
    @patch("engines.snmp_worker.SessionLocal")
    def test_debounce_recovery_resets_counter(
        self, mock_session_local, mock_bulk_insert, mock_fetch_icmp
    ):
        """Successful ping resets debounce counter to 0."""
        from engines.snmp_worker import _consecutive_failures
        _consecutive_failures.clear()
        _consecutive_failures["ci-001"] = 2  # simulate 2 prior failures

        mock_fetch_icmp.return_value = 1.0  # ping succeeds

        mock_session = MockNeo4jSession()
        mock_session.set_response("match", [{
            "node_id": "ci-001",
            "metric_id": "PING-CHECK",
            "protocol": "ICMP",
            "ip": "192.168.1.1",
            "community": "public",
            "oid": None,
            "port": 161
        }])

        mock_session_local.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_local.return_value.__exit__ = MagicMock(return_value=None)

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        with patch("engines.snmp_worker.driver", mock_driver):
            from engines.snmp_worker import poll_snmp
            poll_snmp()

        # Counter should be reset to 0
        assert _consecutive_failures.get("ci-001", 0) == 0

    @patch("engines.snmp_worker.fetch_icmp_ping")
    @patch("engines.snmp_worker.bulk_insert_metrics")
    @patch("engines.snmp_worker.SessionLocal")
    def test_recovery_after_critical_creates_recovered_event(
        self, mock_session_local, mock_bulk_insert, mock_fetch_icmp
    ):
        """After CRITICAL, successful ping creates OK status update."""
        from engines.snmp_worker import _consecutive_failures
        _consecutive_failures.clear()
        _consecutive_failures["ci-001"] = 3  # already at threshold (pre-simulated)

        mock_fetch_icmp.return_value = 1.0  # ping succeeds

        mock_session = MockNeo4jSession()
        mock_session.set_response("match", [{
            "node_id": "ci-001",
            "metric_id": "PING-CHECK",
            "protocol": "ICMP",
            "ip": "192.168.1.1",
            "community": "public",
            "oid": None,
            "port": 161
        }])

        mock_session_local.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_local.return_value.__exit__ = MagicMock(return_value=None)

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        with patch("engines.snmp_worker.driver", mock_driver):
            from engines.snmp_worker import poll_snmp
            poll_snmp()

        # Should set OK status (recovery)
        ok_calls = [
            q for q in mock_session.queries
            if "set n.status" in q["query"].lower() and q["params"].get("status") == "OK"
        ]
        assert len(ok_calls) == 1, f"Expected 1 OK call, got {len(ok_calls)}: {mock_session.queries}"
        assert _consecutive_failures.get("ci-001", 0) == 0