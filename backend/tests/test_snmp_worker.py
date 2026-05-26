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
    def test_fetch_icmp_ping_os_error_fails_attempt(self, mock_run):
        """Expected OS/subprocess failures fail that attempt, retry continues."""
        mock_run.side_effect = [
            OSError("network error"),  # first attempt throws
            MagicMock(returncode=0),    # retry succeeds
        ]
        from engines.snmp_worker import fetch_icmp_ping
        result = fetch_icmp_ping("192.168.1.1", timeout_ms=3000, retries=2)
        assert result == 1.0
        assert mock_run.call_count == 2


class TestSNMPWorkerObservability:
    """Regression tests for observe-only instrumentation in poll_snmp."""

    @patch("engines.snmp_worker.logger")
    @patch("engines.snmp_worker.get_polling_pipeline_settings")
    @patch("engines.snmp_worker.bulk_insert_metrics")
    @patch("engines.snmp_worker.SessionLocal")
    def test_observe_only_logs_structured_cycle_summary_without_saving_metrics(
        self, mock_session_local, mock_bulk_insert, mock_get_settings, mock_logger
    ):
        from config import PollingPipelineSettings

        mock_get_settings.return_value = PollingPipelineSettings(pipeline_observe_only=True)
        mock_session_local.return_value = MagicMock()

        mock_session = MockNeo4jSession()
        mock_session.set_response("match", [])
        mock_session.set_default_response([])

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        with patch("engines.snmp_worker.driver", mock_driver):
            from engines.snmp_worker import poll_snmp
            poll_snmp()

        mock_bulk_insert.assert_not_called()
        observe_calls = [
            call for call in mock_logger.info.call_args_list
            if call.args and call.args[0] == "polling_observe_cycle"
        ]
        assert observe_calls
        observe_fields = observe_calls[0].kwargs["extra"]["polling"]
        assert observe_fields["metrics_processed"] == 0
        assert observe_fields["metrics_collected"] == 0
        assert observe_fields["metrics_failed"] == 0
        assert observe_fields["pipeline_observe_only"] is True

    @patch("engines.snmp_worker.logger")
    @patch("engines.snmp_worker.get_polling_pipeline_settings")
    @patch("engines.snmp_worker.fetch_snmp_value")
    @patch("engines.snmp_worker.bulk_insert_metrics")
    @patch("engines.snmp_worker.SessionLocal")
    def test_observe_only_logs_non_empty_cycle_without_changing_persistence(
        self, mock_session_local, mock_bulk_insert, mock_fetch_snmp, mock_get_settings, mock_logger
    ):
        from config import PollingPipelineSettings

        mock_get_settings.return_value = PollingPipelineSettings(pipeline_observe_only=True)
        mock_fetch_snmp.return_value = 42.0
        mock_session_local.return_value = MagicMock()

        mock_session = MockNeo4jSession()
        mock_session.set_response("match", [{
            "node_id": "ci-001",
            "metric_id": "CPU",
            "protocol": "SNMP",
            "ip": "192.168.1.1",
            "community": "public",
            "oid": "1.3.6.1.2.1.25.3.3.1.2",
            "port": 161,
        }])
        mock_session.set_default_response([])

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        with patch("engines.snmp_worker.driver", mock_driver):
            from engines.snmp_worker import poll_snmp
            poll_snmp()

        mock_bulk_insert.assert_called_once()
        saved_metrics = mock_bulk_insert.call_args.args[1]
        assert saved_metrics[0]["node_id"] == "ci-001"
        assert saved_metrics[0]["metric_id"] == "CPU"
        assert saved_metrics[0]["value"] == 42.0

        latest_update_calls = [
            call for call in mock_session.queries
            if "r.last_value" in call["query"] and call["params"].get("nid") == "ci-001"
        ]
        assert latest_update_calls
        assert latest_update_calls[0]["params"]["mid"] == "CPU"
        assert latest_update_calls[0]["params"]["val"] == 42.0
        assert latest_update_calls[0]["params"]["status"] == "OK"

        observe_calls = [
            call for call in mock_logger.info.call_args_list
            if call.args and call.args[0] == "polling_observe_cycle"
        ]
        assert observe_calls
        observe_fields = observe_calls[0].kwargs["extra"]["polling"]
        assert observe_fields["metrics_processed"] == 1
        assert observe_fields["metrics_collected"] == 1
        assert observe_fields["metrics_failed"] == 0
        assert observe_fields["pipeline_observe_only"] is True

    @patch("engines.snmp_worker.logger")
    @patch("engines.snmp_worker.get_polling_pipeline_settings")
    @patch("engines.snmp_worker.bulk_insert_metrics")
    @patch("engines.snmp_worker.SessionLocal")
    def test_observe_only_logging_is_disabled_by_default(
        self, mock_session_local, mock_bulk_insert, mock_get_settings, mock_logger
    ):
        from config import PollingPipelineSettings

        mock_get_settings.return_value = PollingPipelineSettings()
        mock_session_local.return_value = MagicMock()

        mock_session = MockNeo4jSession()
        mock_session.set_response("match", [])
        mock_session.set_default_response([])

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        with patch("engines.snmp_worker.driver", mock_driver):
            from engines.snmp_worker import poll_snmp
            poll_snmp()

        mock_bulk_insert.assert_not_called()
        assert not any(
            call.args and call.args[0] == "polling_observe_cycle"
            for call in mock_logger.info.call_args_list
        )

    @patch("polling.snmp_worker.run_leased_snmp_worker_once")
    @patch("engines.snmp_worker.poll_snmp")
    @patch("engines.snmp_worker.SessionLocal")
    @patch("engines.snmp_worker.get_polling_pipeline_settings")
    def test_job_dispatches_to_leased_worker_only_when_flag_enabled(
        self, mock_get_settings, mock_session_local, mock_poll_snmp, mock_leased_once
    ):
        from config import PollingPipelineSettings
        from engines.snmp_worker import job

        db = MagicMock()
        mock_session_local.return_value = db
        mock_get_settings.return_value = PollingPipelineSettings(snmp_leased_worker_enabled=True)

        job()

        mock_poll_snmp.assert_not_called()
        mock_leased_once.assert_called_once_with(db, settings=mock_get_settings.return_value)
        db.close.assert_called_once()


class TestSNMPCollectionFailures:
    """Regression tests for SNMP no-response collection-failure lifecycle."""

    @patch("engines.snmp_worker.fetch_snmp_value")
    @patch("engines.snmp_worker.bulk_insert_metrics")
    @patch("engines.snmp_worker.SessionLocal")
    def test_snmp_no_response_creates_warning_collection_failure(
        self, mock_session_local, mock_bulk_insert, mock_fetch_snmp
    ):
        mock_fetch_snmp.return_value = None
        mock_session_local.return_value = MagicMock()

        mock_session = MockNeo4jSession()
        mock_session.set_response("match", [{
            "node_id": "ci-001",
            "metric_id": "ifInOctets",
            "protocol": "SNMP",
            "ip": "192.168.1.1",
            "community": "public",
            "oid": "1.3.6.1.2.1.2.2.1.10.1",
            "port": 161,
        }])
        mock_session.set_default_response([])

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        with patch("engines.snmp_worker.driver", mock_driver):
            from engines.snmp_worker import poll_snmp
            poll_snmp()

        mock_bulk_insert.assert_not_called()
        queries = "\n".join(q["query"] for q in mock_session.queries)
        failure_batches = [q["params"].get("failures", []) for q in mock_session.queries]
        assert "COLLECTION_FAILURE" in queries
        assert "SNMP_NO_RESPONSE" in queries
        assert any(item.get("severity") == "WARNING" for batch in failure_batches for item in batch)

    @patch("engines.snmp_worker.fetch_snmp_value")
    @patch("engines.snmp_worker.bulk_insert_metrics")
    @patch("engines.snmp_worker.SessionLocal")
    def test_valid_snmp_sample_recovers_matching_collection_failure(
        self, mock_session_local, mock_bulk_insert, mock_fetch_snmp
    ):
        mock_fetch_snmp.return_value = 42.0
        mock_session_local.return_value = MagicMock()

        mock_session = MockNeo4jSession()
        mock_session.set_response("match", [{
            "node_id": "ci-001",
            "metric_id": "ifInOctets",
            "protocol": "SNMP",
            "ip": "192.168.1.1",
            "community": "public",
            "oid": "1.3.6.1.2.1.2.2.1.10.1",
            "port": 161,
        }])
        mock_session.set_default_response([])

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        with patch("engines.snmp_worker.driver", mock_driver):
            from engines.snmp_worker import poll_snmp
            poll_snmp()

        queries = "\n".join(q["query"] for q in mock_session.queries)
        assert "RECOVERED" in queries
        assert "COLLECTION_FAILURE" in queries
        assert "Metric Collection Failed:" in queries
        assert "PROPAGATED" in queries
        assert "coalesce(m.can_propagate, true) = true" in queries

    @patch("engines.snmp_worker.fetch_snmp_value")
    @patch("engines.snmp_worker.bulk_insert_metrics")
    @patch("engines.snmp_worker.SessionLocal")
    def test_snmp_no_response_failures_are_deduplicated_before_event_write(
        self, mock_session_local, mock_bulk_insert, mock_fetch_snmp
    ):
        mock_fetch_snmp.return_value = None
        mock_session_local.return_value = MagicMock()

        mock_session = MockNeo4jSession()
        mock_session.set_response("match", [
            {
                "node_id": "ci-001",
                "metric_id": "ifInOctets",
                "protocol": "SNMP",
                "ip": "192.168.1.1",
                "community": "public",
                "oid": "1.3.6.1.2.1.2.2.1.10.1",
                "port": 161,
            },
            {
                "node_id": "ci-001",
                "metric_id": "ifInOctets",
                "protocol": "SNMP",
                "ip": "192.168.1.1",
                "community": "public",
                "oid": "1.3.6.1.2.1.2.2.1.10.1",
                "port": 161,
            },
        ])
        mock_session.set_default_response([])

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        with patch("engines.snmp_worker.driver", mock_driver):
            from engines.snmp_worker import poll_snmp
            poll_snmp()

        failure_batches = [q["params"].get("failures", []) for q in mock_session.queries]
        assert any(len(batch) == 1 for batch in failure_batches)

    @patch("engines.snmp_worker.fetch_snmp_value")
    @patch("engines.snmp_worker.bulk_insert_metrics")
    @patch("engines.snmp_worker.SessionLocal")
    def test_generic_snmp_error_does_not_create_no_response_collection_failure(
        self, mock_session_local, mock_bulk_insert, mock_fetch_snmp
    ):
        mock_fetch_snmp.return_value = (None, "ERROR", "noSuchName at 1.2.3")
        mock_session_local.return_value = MagicMock()

        mock_session = MockNeo4jSession()
        mock_session.set_response("match", [{
            "node_id": "ci-001",
            "metric_id": "ifInOctets",
            "protocol": "SNMP",
            "ip": "192.168.1.1",
            "community": "public",
            "oid": "1.3.6.1.2.1.2.2.1.10.1",
            "port": 161,
        }])
        mock_session.set_default_response([])

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        with patch("engines.snmp_worker.driver", mock_driver):
            from engines.snmp_worker import poll_snmp
            poll_snmp()

        failure_batches = [q["params"].get("failures", []) for q in mock_session.queries]
        assert not any(batch for batch in failure_batches)
        mock_bulk_insert.assert_not_called()


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
            "port": 161,
            "metric_name": "Ping availability",
            "criticality": 3,
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
        availability_queries = [
            q for q in mock_session.queries
            if "AVAILABILITY" in q["query"] or q["params"].get("availability_events")
        ]
        assert availability_queries == []
        mock_bulk_insert.assert_not_called()
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
            "port": 161,
            "metric_name": "Ping availability",
            "criticality": 3,
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

        # After 3rd failure, CRITICAL status should be set and a 0.0 sample/event is persisted.
        critical_calls = [
            q for q in mock_session.queries
            if "set n.status" in q["query"].lower() and q["params"].get("status") == "CRITICAL"
        ]
        assert len(critical_calls) >= 1, f"Expected at least 1 CRITICAL call, got {len(critical_calls)}: {mock_session.queries}"
        mock_bulk_insert.assert_called()
        saved_rows = mock_bulk_insert.call_args.args[1]
        assert any(row["node_id"] == "ci-001" and row["metric_id"] == "PING-CHECK" and row["value"] == 0.0 for row in saved_rows)
        availability_queries = [
            q for q in mock_session.queries
            if "event_type: row.event_type" in q["query"] and "AVAILABILITY" in q["query"]
        ]
        assert availability_queries, mock_session.queries
        availability_query = "\n".join(q["query"] for q in availability_queries)
        assert "source_protocol" in availability_query
        assert "MERGE (created)-[:TRIGGERED_BY]->(m)" in availability_query or "MERGE (existing)-[:TRIGGERED_BY]->(m)" in availability_query
        availability_batches = [q["params"].get("availability_events", []) for q in availability_queries]
        assert any(row["event_type"] == "AVAILABILITY" and row["source_protocol"] == "ICMP" for batch in availability_batches for row in batch)
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
            "port": 161,
            "metric_name": "Ping availability",
            "criticality": 3,
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
        recovery_queries = [
            q for q in mock_session.queries
            if "SET e.status = 'RECOVERED'" in q["query"] and "AVAILABILITY" in q["query"]
        ]
        assert recovery_queries, mock_session.queries
        recovery_query = "\n".join(q["query"] for q in recovery_queries)
        assert "e.event_type = 'AVAILABILITY'" in recovery_query
        assert "toUpper(e.source_protocol) = row.protocol" in recovery_query
        assert "pe.propagated_from = e.id" in recovery_query
        assert "COLLECTION_FAILURE" not in recovery_query
        assert _consecutive_failures.get("ci-001", 0) == 0

    @patch("engines.snmp_worker.fetch_icmp_ping")
    @patch("engines.snmp_worker.bulk_insert_metrics")
    @patch("engines.snmp_worker.SessionLocal")
    def test_debounce_threshold_bulk_insert_failure_does_not_write_event(
        self, mock_session_local, mock_bulk_insert, mock_fetch_icmp
    ):
        """ICMP availability events are not written unless durable insert succeeds."""
        from engines.snmp_worker import _consecutive_failures
        _consecutive_failures.clear()

        mock_fetch_icmp.return_value = 0.0
        mock_bulk_insert.side_effect = RuntimeError("timescale unavailable")

        mock_session = MockNeo4jSession()
        mock_session.set_response("match", [{
            "node_id": "ci-001",
            "metric_id": "PING-CHECK",
            "protocol": "ICMP",
            "ip": "192.168.1.1",
            "community": "public",
            "oid": None,
            "port": 161,
            "metric_name": "Ping availability",
            "criticality": 3,
        }])

        mock_session_local.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_local.return_value.__exit__ = MagicMock(return_value=None)

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

        with patch("engines.snmp_worker.driver", mock_driver):
            from engines.snmp_worker import poll_snmp

            for _ in range(3):
                poll_snmp()

        mock_bulk_insert.assert_called_once()
        critical_calls = [
            q for q in mock_session.queries
            if "set n.status" in q["query"].lower() and q["params"].get("status") == "CRITICAL"
        ]
        assert critical_calls == []
        availability_queries = [
            q for q in mock_session.queries
            if "event_type: row.event_type" in q["query"] and "AVAILABILITY" in q["query"]
        ]
        assert availability_queries == []
        assert _consecutive_failures.get("ci-001", 0) >= 3
