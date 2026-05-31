"""Focused service tests for event detail shaping and event snapshots."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
import sys
import types

import pytest
from fastapi import HTTPException


def _load_event_service_module():
    sys.modules.pop("services.event_service", None)
    stub = types.ModuleType("services.snmp_service")
    setattr(stub, "run_diagnostic", lambda ci, metric: "diagnostic-ok")
    sys.modules["services.snmp_service"] = stub
    return importlib.import_module("services.event_service")


class TestEventServiceImports:
    """Verify that event_service can be imported and its functions exist."""

    def test_event_service_imports(self):
        """The module should import without errors."""
        event_service = _load_event_service_module()

        assert hasattr(event_service, "get_events")
        assert hasattr(event_service, "get_event_detail")
        assert hasattr(event_service, "get_related_events")
        assert hasattr(event_service, "ack_event")
        assert hasattr(event_service, "close_event")
        assert hasattr(event_service, "add_event_comment")
        assert hasattr(event_service, "prune_recovered_events")
        assert hasattr(event_service, "run_event_diagnostic")
        assert hasattr(event_service, "get_availability_report")


class TestEventServiceSmoke:
    """Minimal smoke tests with mocked DB to verify the mocking infrastructure."""

    def test_get_events_returns_empty_with_mock(self, mock_neo4j_session):
        """get_events should return empty list when no events exist."""
        mock_neo4j_session.set_response("event", [])

        get_events = _load_event_service_module().get_events

        result = get_events()

        assert result == []

    def test_get_events_filters_by_status(self, mock_neo4j_session):
        """get_events should pass status filter to the query."""
        get_events = _load_event_service_module().get_events

        get_events(status="OPEN")

        assert len(mock_neo4j_session.queries) >= 1
        query = mock_neo4j_session.queries[0]["query"].lower()
        assert "status" in query

    def test_get_events_active_filter_excludes_recovered(self, mock_neo4j_session):
        """ACTIVE should mean unresolved alarms only: OPEN/ACK, not RECOVERED."""
        get_events = _load_event_service_module().get_events

        get_events(status="ACTIVE")

        query = mock_neo4j_session.queries[0]["query"]
        assert "$status = 'ACTIVE' AND e.status IN ['OPEN', 'ACK']" in query
        assert "$status = 'CONSOLE' AND e.status IN ['OPEN', 'ACK', 'RECOVERED']" in query
        assert "$status <> 'ACTIVE' AND $status <> 'CONSOLE' AND e.status = $status" in query
        assert query.index("WHERE (\n                $status IS NULL") < query.index("OPTIONAL MATCH")

    def test_get_events_console_filter_includes_recovered(self, mock_neo4j_session):
        """CONSOLE feed should keep recovered events visible until close/prune logic runs."""
        get_events = _load_event_service_module().get_events

        get_events(status="CONSOLE")

        query = mock_neo4j_session.queries[0]["query"]
        assert "$status = 'CONSOLE' AND e.status IN ['OPEN', 'ACK', 'RECOVERED']" in query

    def test_get_events_uses_optional_metric_match(self, mock_neo4j_session):
        """Legacy active events without TRIGGERED_BY should not be filtered out."""
        get_events = _load_event_service_module().get_events

        get_events(status="ACTIVE")

        query = mock_neo4j_session.queries[0]["query"].lower()
        assert "optional match (e)-[:triggered_by]->(m:metricdef)" in query

    def test_get_availability_report_aggregates_mttr_mtbf_and_active_downtime(
        self, mock_neo4j_session
    ):
        get_availability_report = _load_event_service_module().get_availability_report
        start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, 5, 0, tzinfo=timezone.utc)
        mock_neo4j_session.set_response(
            "not e.status in ['open', 'ack']",
            [
                {
                    "e": {
                        "id": "evt-1",
                        "ci_id": "ci-1",
                        "status": "RECOVERED",
                        "event_type": "AVAILABILITY",
                        "availability_source": "ICMP",
                        "created_at": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                        "recovered_at": datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-1", "name": "Router-01"},
                },
                {
                    "e": {
                        "id": "evt-2",
                        "ci_id": "ci-1",
                        "status": "CLOSED",
                        "event_type": "AVAILABILITY",
                        "availability_source": "ICMP",
                        "created_at": datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc),
                        "recovered_at": datetime(2026, 1, 1, 2, 20, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-1", "name": "Router-01"},
                },
                {
                    "e": {
                        "id": "evt-incomplete",
                        "ci_id": "ci-1",
                        "status": "RECOVERED",
                        "event_type": "AVAILABILITY",
                        "availability_source": "ICMP",
                        "created_at": datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc),
                        "recovered_at": None,
                    },
                    "ci": {"id": "ci-1", "name": "Router-01"},
                },
            ],
        )
        mock_neo4j_session.set_response(
            "e.status in ['open', 'ack']",
            [
                {
                    "e": {
                        "id": "evt-active",
                        "ci_id": "ci-1",
                        "status": "OPEN",
                        "event_type": "AVAILABILITY",
                        "availability_source": "ICMP",
                        "created_at": datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-1", "name": "Router-01"},
                }
            ],
        )

        report = get_availability_report(start=start, end=end, now=end)

        assert report["window_start"] == start.isoformat()
        assert report["window_end"] == end.isoformat()
        assert report["total_groups"] == 1
        row = report["rows"][0]
        assert row["ci_id"] == "ci-1"
        assert row["ci_name"] == "Router-01"
        assert row["event_type"] == "AVAILABILITY"
        assert row["recovered_incidents"] == 2
        assert row["mttr_seconds"] == 900
        assert row["mtbf_seconds"] == 7200
        assert row["downtime_seconds"] == 1800
        assert row["active_events"] == 1
        assert row["active_downtime_seconds"] == 3600
        assert row["availability_percentage"] == 70.0

    def test_get_availability_report_includes_active_failure_starts_in_mtbf(
        self, mock_neo4j_session
    ):
        get_availability_report = _load_event_service_module().get_availability_report
        start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, 5, 0, tzinfo=timezone.utc)
        mock_neo4j_session.set_response(
            "not e.status in ['open', 'ack']",
            [
                {
                    "e": {
                        "id": "evt-recovered",
                        "ci_id": "ci-1",
                        "status": "RECOVERED",
                        "event_type": "AVAILABILITY",
                        "availability_source": "ICMP",
                        "created_at": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                        "recovered_at": datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-1", "name": "Router-01"},
                },
            ],
        )
        mock_neo4j_session.set_response(
            "e.status in ['open', 'ack']",
            [
                {
                    "e": {
                        "id": "evt-active",
                        "ci_id": "ci-1",
                        "status": "ACK",
                        "event_type": "AVAILABILITY",
                        "availability_source": "ICMP",
                        "created_at": datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-1", "name": "Router-01"},
                },
            ],
        )

        report = get_availability_report(start=start, end=end, now=end)

        row = report["rows"][0]
        assert row["recovered_incidents"] == 1
        assert row["mttr_seconds"] == 600
        assert row["mtbf_seconds"] == 10800
        assert row["active_events"] == 1

    def test_get_availability_report_enriches_rows_with_sanitized_ci_metadata(
        self, mock_neo4j_session
    ):
        get_availability_report = _load_event_service_module().get_availability_report
        start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
        mock_neo4j_session.set_response(
            "not e.status in ['open', 'ack']",
            [
                {
                    "e": {
                        "id": "evt-1",
                        "ci_id": "ci-1",
                        "status": "RECOVERED",
                        "event_type": "AVAILABILITY",
                        "availability_source": "ICMP",
                        "created_at": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                        "recovered_at": datetime(2026, 1, 1, 0, 15, tzinfo=timezone.utc),
                    },
                    "ci": {
                        "id": "ci-1",
                        "name": "Router-01",
                        "layer": "NETWORK",
                        "status": "ONLINE",
                        "ip": "10.0.0.1",
                        "location_name": "Madrid HQ",
                        "owner": "NOC",
                        "brand": "Cisco",
                        "model": "ISR4331",
                        "serialNumber": "FTX1234",
                        "firmwareVersion": "17.9",
                        "pollingInterval": 60,
                        "rack": "R1",
                        "username": "admin",
                        "login": "router-admin",
                        "user": "operator",
                        "passwd": "legacy-password",
                        "pwd": "short-password",
                        "passphrase": "phrase-value",
                        "support_contact": {"username": "support", "phone": "+34123456789"},
                        "snmp_community": "public",
                        "credentials": {"username": "admin", "password": "secret"},
                        "api_token": "token-value",
                        "installed_at": datetime(2025, 12, 1, 10, 0, tzinfo=timezone.utc),
                        "location": object(),
                    },
                    "category": "Routers",
                }
            ],
        )
        mock_neo4j_session.set_response("e.status in ['open', 'ack']", [])

        report = get_availability_report(start=start, end=end, now=end)

        row = report["rows"][0]
        assert row["mttr_seconds"] == 900
        assert row["downtime_seconds"] == 900
        assert row["ci"] == {
            "id": "ci-1",
            "label": "Router-01",
            "category": "Routers",
            "type": "Routers",
            "status": "ONLINE",
            "ip": "10.0.0.1",
            "location_name": "Madrid HQ",
            "owner": "NOC",
            "brand": "Cisco",
            "model": "ISR4331",
            "serialNumber": "FTX1234",
            "firmwareVersion": "17.9",
            "pollingInterval": 60,
            "metadata": {
                "rack": "R1",
                "support_contact": {"phone": "+34123456789"},
                "installed_at": "2025-12-01T10:00:00+00:00",
            },
        }
        assert "credentials" not in row["ci"]["metadata"]
        assert "username" not in row["ci"]["metadata"]
        assert "login" not in row["ci"]["metadata"]
        assert "user" not in row["ci"]["metadata"]
        assert "passwd" not in row["ci"]["metadata"]
        assert "pwd" not in row["ci"]["metadata"]
        assert "passphrase" not in row["ci"]["metadata"]
        assert "username" not in row["ci"]["metadata"]["support_contact"]
        assert "snmp_community" not in row["ci"]["metadata"]
        assert "api_token" not in row["ci"]["metadata"]
        assert "location" not in row["ci"]["metadata"]

    def test_get_availability_report_aggregates_categories_before_metric_rows(
        self, mock_neo4j_session
    ):
        get_availability_report = _load_event_service_module().get_availability_report
        start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)

        get_availability_report(start=start, end=end, now=end)

        recovered_query = next(
            query
            for query in mock_neo4j_session.queries
            if "NOT e.status IN ['OPEN', 'ACK']" in query["query"]
        )["query"]
        active_query = next(
            query
            for query in mock_neo4j_session.queries
            if "WHERE e.status IN ['OPEN', 'ACK']" in query["query"]
        )["query"]

        assert "head(collect(DISTINCT cat.name)) AS category" in recovered_query
        assert "head(collect(DISTINCT cat.name)) AS category" in active_query
        assert "RETURN e, ci, category" in recovered_query
        assert "RETURN e, ci, category" in active_query

    def test_get_availability_report_queries_scope_to_availability_events(
        self, mock_neo4j_session
    ):
        get_availability_report = _load_event_service_module().get_availability_report
        start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)

        get_availability_report(start=start, end=end, now=end)

        recovered_query = next(
            query
            for query in mock_neo4j_session.queries
            if "NOT e.status IN ['OPEN', 'ACK']" in query["query"]
        )["query"]
        active_query = next(
            query
            for query in mock_neo4j_session.queries
            if "WHERE e.status IN ['OPEN', 'ACK']" in query["query"]
        )["query"]

        assert "e.event_type = 'AVAILABILITY'" in recovered_query
        assert "e.event_type = 'AVAILABILITY'" in active_query
        assert "e.availability_source IN ['PING', 'ICMP']" in recovered_query
        assert "e.availability_source IN ['PING', 'ICMP']" in active_query

    def test_get_availability_report_excludes_non_availability_event_types(
        self, mock_neo4j_session
    ):
        """Only availability incidents should drive MTTR/MTBF/availability rows."""
        get_availability_report = _load_event_service_module().get_availability_report
        start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc)
        mock_neo4j_session.set_response(
            "not e.status in ['open', 'ack']",
            [
                {
                    "e": {
                        "id": "evt-availability-recovered",
                        "ci_id": "ci-1",
                        "status": "RECOVERED",
                        "event_type": "AVAILABILITY",
                        "availability_source": "ICMP",
                        "created_at": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                        "recovered_at": datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-1", "name": "Router-01", "status": "OK"},
                },
                {
                    "e": {
                        "id": "evt-threshold-recovered",
                        "ci_id": "ci-1",
                        "status": "RECOVERED",
                        "event_type": "THRESHOLD_BREACH",
                        "created_at": datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                        "recovered_at": datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-1", "name": "Router-01", "status": "DEGRADED"},
                },
                {
                    "e": {
                        "id": "evt-collection-closed",
                        "ci_id": "ci-2",
                        "status": "CLOSED",
                        "event_type": "COLLECTION_FAILURE",
                        "created_at": datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                        "recovered_at": datetime(2026, 1, 1, 1, 15, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-2", "name": "Switch-01", "status": "OK"},
                },
            ],
        )
        mock_neo4j_session.set_response(
            "e.status in ['open', 'ack']",
            [
                {
                    "e": {
                        "id": "evt-availability-active",
                        "ci_id": "ci-1",
                        "status": "ACK",
                        "event_type": "AVAILABILITY",
                        "availability_source": "ICMP",
                        "created_at": datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-1", "name": "Router-01", "status": "DOWN"},
                },
                {
                    "e": {
                        "id": "evt-snmp-active",
                        "ci_id": "ci-1",
                        "status": "OPEN",
                        "event_type": "COLLECTION_FAILURE",
                        "created_at": datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-1", "name": "Router-01", "status": "UNKNOWN"},
                },
            ],
        )

        report = get_availability_report(start=start, end=end, now=end)

        assert report["total_groups"] == 1
        row = report["rows"][0]
        assert row["ci_id"] == "ci-1"
        assert row["event_type"] == "AVAILABILITY"
        assert row["recovered_incidents"] == 1
        assert row["active_events"] == 1
        assert row["downtime_seconds"] == 1800
        assert row["active_downtime_seconds"] == 3600
        assert row["availability_percentage"] == 62.5

    def test_get_availability_report_excludes_untagged_availability_events(
        self, mock_neo4j_session
    ):
        get_availability_report = _load_event_service_module().get_availability_report
        start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
        mock_neo4j_session.set_response(
            "not e.status in ['open', 'ack']",
            [
                {
                    "e": {
                        "id": "evt-tagged-ping",
                        "ci_id": "ci-1",
                        "status": "RECOVERED",
                        "event_type": "AVAILABILITY",
                        "availability_source": "PING",
                        "metric_id": "PING-CHECK",
                        "created_at": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                        "recovered_at": datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-1", "name": "Router-01", "status": "OK"},
                },
                {
                    "e": {
                        "id": "evt-untagged-icmp",
                        "ci_id": "ci-2",
                        "status": "RECOVERED",
                        "event_type": "AVAILABILITY",
                        "source_protocol": "ICMP",
                        "metric_id": "PING-CHECK",
                        "created_at": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                        "recovered_at": datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-2", "name": "Legacy Ping", "status": "OK"},
                },
                {
                    "e": {
                        "id": "evt-mariadb",
                        "ci_id": "ci-3",
                        "status": "RECOVERED",
                        "event_type": "AVAILABILITY",
                        "metric_id": "mariadb-GS",
                        "created_at": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                        "recovered_at": datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-3", "name": "MariaDB", "status": "OK"},
                },
            ],
        )

        report = get_availability_report(start=start, end=end, now=end)

        assert report["total_groups"] == 1
        assert report["rows"][0]["ci_id"] == "ci-1"

    def test_get_availability_report_handles_ci_status_variants_for_availability_events(
        self, mock_neo4j_session
    ):
        """CI state at event time should not change event-status availability math."""
        get_availability_report = _load_event_service_module().get_availability_report
        start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
        mock_neo4j_session.set_response(
            "not e.status in ['open', 'ack']",
            [
                {
                    "e": {
                        "id": "evt-online-recovered",
                        "ci_id": "ci-online",
                        "status": "RECOVERED",
                        "event_type": "AVAILABILITY",
                        "availability_source": "ICMP",
                        "created_at": datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                        "recovered_at": datetime(2026, 1, 1, 1, 20, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-online", "name": "Router Online", "status": "OK"},
                },
                {
                    "e": {
                        "id": "evt-maint-recovered",
                        "ci_id": "ci-maint",
                        "status": "CLOSED",
                        "event_type": "AVAILABILITY",
                        "availability_source": "ICMP",
                        "created_at": datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc),
                        "recovered_at": datetime(2026, 1, 1, 2, 45, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-maint", "name": "Router Maintenance", "status": "MAINTENANCE"},
                },
            ],
        )
        mock_neo4j_session.set_response(
            "e.status in ['open', 'ack']",
            [
                {
                    "e": {
                        "id": "evt-down-active",
                        "ci_id": "ci-down",
                        "status": "OPEN",
                        "event_type": "AVAILABILITY",
                        "availability_source": "ICMP",
                        "created_at": datetime(2026, 1, 1, 5, 0, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-down", "name": "Router Down", "status": "DOWN"},
                }
            ],
        )

        report = get_availability_report(start=start, end=end, now=end)

        rows = {row["ci_id"]: row for row in report["rows"]}
        assert rows["ci-online"]["ci"]["status"] == "OK"
        assert rows["ci-online"]["recovered_incidents"] == 1
        assert rows["ci-online"]["downtime_seconds"] == 1200
        assert rows["ci-online"]["availability_percentage"] == 94.4444
        assert rows["ci-maint"]["ci"]["status"] == "MAINTENANCE"
        assert rows["ci-maint"]["recovered_incidents"] == 1
        assert rows["ci-maint"]["downtime_seconds"] == 2700
        assert rows["ci-maint"]["availability_percentage"] == 87.5
        assert rows["ci-down"]["ci"]["status"] == "DOWN"
        assert rows["ci-down"]["active_events"] == 1
        assert rows["ci-down"]["active_downtime_seconds"] == 3600
        assert rows["ci-down"]["availability_percentage"] == 83.3333

    def test_get_availability_report_queries_filter_window_in_cypher(
        self, mock_neo4j_session
    ):
        get_availability_report = _load_event_service_module().get_availability_report
        start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)

        get_availability_report(start=start, end=end, now=end)

        recovered_query = next(
            query
            for query in mock_neo4j_session.queries
            if "NOT e.status IN ['OPEN', 'ACK']" in query["query"]
        )
        active_query = next(
            query
            for query in mock_neo4j_session.queries
            if "WHERE e.status IN ['OPEN', 'ACK']" in query["query"]
        )

        assert recovered_query["params"] == {
            "window_start": start,
            "window_end": end,
        }
        assert "e.created_at >= $window_start" in recovered_query["query"]
        assert "e.created_at <= $window_end" in recovered_query["query"]
        assert "e.recovered_at <= $window_end" in recovered_query["query"]

        assert active_query["params"] == {"window_end": end}
        assert "e.created_at <= $window_end" in active_query["query"]
        assert "e.created_at >= $window_start" not in active_query["query"]

    def test_get_availability_report_active_before_window_counts_downtime_not_mtbf(
        self, mock_neo4j_session
    ):
        get_availability_report = _load_event_service_module().get_availability_report
        start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
        mock_neo4j_session.set_response("not e.status in ['open', 'ack']", [])
        mock_neo4j_session.set_response(
            "e.status in ['open', 'ack']",
            [
                {
                    "e": {
                        "id": "evt-active-before-window",
                        "ci_id": "ci-1",
                        "status": "OPEN",
                        "event_type": "AVAILABILITY",
                        "availability_source": "ICMP",
                        "created_at": datetime(2025, 12, 31, 23, 0, tzinfo=timezone.utc),
                    },
                    "ci": {"id": "ci-1", "name": "Router-01"},
                }
            ],
        )

        report = get_availability_report(start=start, end=end, now=end)

        row = report["rows"][0]
        assert row["active_events"] == 1
        assert row["active_downtime_seconds"] == 7200
        assert row["mtbf_seconds"] is None
        assert row["first_failure_at"] is None
        assert row["last_failure_at"] is None
        assert row["availability_percentage"] == 0.0

    def test_get_availability_report_defaults_to_last_30_days(self, mock_neo4j_session):
        get_availability_report = _load_event_service_module().get_availability_report
        now = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)

        report = get_availability_report(now=now)

        assert report["window_end"] == now.isoformat()
        assert report["window_start"] == (now - timedelta(days=30)).isoformat()
        assert report["window_days"] == 30

    def test_get_events_returns_legacy_event_without_metric_relationship(
        self, mock_neo4j_session
    ):
        get_events = _load_event_service_module().get_events
        now = datetime.now(timezone.utc)
        mock_neo4j_session.set_response(
            "return e, ci, m",
            [
                {
                    "e": {
                        "id": "evt-icmp-down",
                        "ci_id": "ci-001",
                        "metric_id": "PING-CHECK",
                        "metric_name": "Ping availability",
                        "status": "OPEN",
                        "severity": "CRITICAL",
                        "message": "Service/Host Down: Ping availability",
                        "event_type": "AVAILABILITY",
                        "source_protocol": "ICMP",
                        "created_at": now,
                        "last_seen": now,
                        "ack": False,
                    },
                    "ci": {"id": "ci-001", "name": "Router-01", "ip": "10.0.0.1"},
                    "m": None,
                }
            ],
        )

        result = get_events(status="ACTIVE")

        assert result == [
            {
                "id": "evt-icmp-down",
                "ci_id": "ci-001",
                "metric_id": "PING-CHECK",
                "status": "OPEN",
                "severity": "CRITICAL",
                "message": "Service/Host Down: Ping availability",
                "created_at": now.isoformat(),
                "last_seen": now.isoformat(),
                "ack": False,
                "ci_name": "Router-01",
                "ci_node_id": "ci-001",
                "ci_hostname": "10.0.0.1",
                "metric_name": "Ping availability",
                "metric_protocol": "ICMP",
                "event_type": "AVAILABILITY",
                "source_protocol": "ICMP",
            }
        ]

    def test_get_events_returns_sparse_legacy_event_without_fabricated_metric(
        self, mock_neo4j_session
    ):
        get_events = _load_event_service_module().get_events
        mock_neo4j_session.set_response(
            "return e, ci, m",
            [
                {
                    "e": {
                        "id": "evt-sparse",
                        "ci_id": "ci-002",
                        "status": "OPEN",
                        "severity": "WARNING",
                        "message": "Legacy event",
                    },
                    "ci": {"id": "ci-002", "name": "Legacy-CI"},
                    "m": None,
                }
            ],
        )

        result = get_events(status="ACTIVE")

        assert result[0]["id"] == "evt-sparse"
        assert result[0]["ci_node_id"] == "ci-002"
        assert result[0]["status"] == "OPEN"
        assert "metric_name" not in result[0]
        assert "metric_protocol" not in result[0]

    def test_get_events_strips_audit_heavy_fields_from_public_summary(
        self, mock_neo4j_session
    ):
        get_events = _load_event_service_module().get_events
        now = datetime.now(timezone.utc)
        mock_neo4j_session.set_response(
            "return e, ci, m",
            [
                {
                    "e": {
                        "id": "evt-001",
                        "ci_id": "ci-001",
                        "metric_id": "cpu",
                        "status": "ACK",
                        "severity": "CRITICAL",
                        "message": "CPU high",
                        "created_at": now,
                        "last_seen": now,
                        "ack": True,
                        "ack_by": "operator-1",
                        "closed_by": "operator-2",
                        "comments": ["internal audit"],
                    },
                    "ci": {"id": "ci-001", "name": "Router-01", "ip": "10.0.0.1"},
                    "m": {"id": "cpu", "name": "CPU", "protocol": "SNMP"},
                }
            ],
        )

        result = get_events()

        assert len(result) == 1
        assert "comments" not in result[0]
        assert "ack_by" not in result[0]
        assert "closed_by" not in result[0]

    def test_ack_event_sets_ack_status(self, mock_neo4j_session):
        """ack_event should set status to ACK."""
        ack_event = _load_event_service_module().ack_event
        mock_neo4j_session.set_response(
            "return e.id as event_id", [{"event_id": "evt-001"}]
        )

        ack_event("evt-001", "testuser")

        assert len(mock_neo4j_session.queries) >= 1
        query = mock_neo4j_session.queries[0]["query"].upper()
        assert "ACK" in query
        assert "evt-001" in mock_neo4j_session.queries[0]["params"]["eid"]

    def test_close_event_sets_closed_status(self, mock_neo4j_session):
        """close_event should set status to CLOSED."""
        close_event = _load_event_service_module().close_event
        # 1. State check query
        mock_neo4j_session.set_response(
            "match (e:event {id: $eid}) return e.status", [{"status": "OPEN"}]
        )
        # 2. Update query
        mock_neo4j_session.set_response(
            "set e.status = 'closed'", [{"event_id": "evt-001"}]
        )

        close_event(
            "evt-001",
            "testuser",
            comment_message="Causa raíz: Falla de hardware\nNota: Se reemplazó el módulo principal averiado",
        )

        # Should now have 2 queries
        assert len(mock_neo4j_session.queries) == 2
        query = mock_neo4j_session.queries[1]["query"].upper()
        assert "CLOSED" in query

    def test_add_event_comment_appends_comment(self, mock_neo4j_session):
        """add_event_comment should append to comments array."""
        add_event_comment = _load_event_service_module().add_event_comment
        mock_neo4j_session.set_response(
            "return e.id as event_id", [{"event_id": "evt-001"}]
        )

        add_event_comment("evt-001", "testuser", "Investigating...")

        assert len(mock_neo4j_session.queries) >= 1
        query = mock_neo4j_session.queries[0]["query"].lower()
        assert "comments" in query
        assert "testuser" in mock_neo4j_session.queries[0]["params"]["user"]
        assert "Investigating..." in mock_neo4j_session.queries[0]["params"]["msg"]

    def test_prune_recovered_events_cleans_up(self, mock_neo4j_session):
        """prune_recovered_events should close RECOVERED events without ack."""
        prune_recovered_events = _load_event_service_module().prune_recovered_events

        mock_neo4j_session.set_response("recovered", [{"closed_count": 3}])

        result = prune_recovered_events("system")

        assert result["count"] == 3
        assert "Cleaned up" in result["message"]

    def test_build_event_detail_prefers_snapshot_values_and_sla_math(self):
        event_service = _load_event_service_module()
        now = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)
        created_at = now - timedelta(minutes=35)

        detail = event_service.build_event_detail_response(
            {
                "e": {
                    "id": "evt-001",
                    "ci_id": "ci-001",
                    "metric_id": "cpu-load",
                    "status": "OPEN",
                    "severity": "CRITICAL",
                    "message": "CPU over threshold",
                    "created_at": created_at,
                    "last_seen": created_at,
                    "ack": False,
                    "business_service_id": "svc-snapshot",
                    "business_service_name": "Corp-WAN Snapshot",
                    "owner_t1": "Mesa N1",
                    "owner_t2": "NetOps",
                    "owner_t3": "Arquitectura",
                    "impacted_users": 350,
                    "site": "Madrid HQ",
                    "service_catalog_id": "sla-snapshot",
                    "service_category": "NETWORK",
                    "service_tier": "Gold",
                    "sla_minutes": 60,
                },
                "ci": {
                    "id": "ci-001",
                    "name": "Router-01",
                    "ip": "10.0.0.1",
                    "location_name": "Sede Central",
                },

                "m": {"id": "cpu-load", "protocol": "SNMP"},
                "bs": {
                    "id": "svc-live",
                    "name": "Corp-WAN Live",
                    "owner_t1": "Live T1",
                    "owner_t2": "Live T2",
                    "owner_t3": "Live T3",
                    "impacted_users_count": 900,
                },
                "sc": {
                    "id": "sla-live",
                    "category": "NETWORK",
                    "service_tier": "Silver",
                    "sla_minutes": 120,
                },
            },
            now=now,
        )

        assert detail["event"]["ci_ref"]["id"] == "ci-001"
        assert detail["business_context"]["source"] == "snapshot"
        assert (
            detail["business_context"]["business_service"]["name"]
            == "Corp-WAN Snapshot"
        )
        assert "tier" not in detail["business_context"]["business_service"]
        assert detail["business_context"]["service_catalog"]["id"] == "sla-snapshot"
        assert detail["business_context"]["service_catalog"]["service_tier"] == "Gold"
        assert detail["business_context"]["impacted_users"] == 350
        assert detail["business_context"]["sla_remaining_minutes"] == 25
        assert detail["itsm_context"]["assignment_state"] == "unassigned"

    def test_build_event_detail_falls_back_to_resolved_context_when_snapshot_missing(
        self,
    ):
        event_service = _load_event_service_module()
        now = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)
        created_at = now - timedelta(minutes=5)

        detail = event_service.build_event_detail_response(
            {
                "e": {
                    "id": "evt-002",
                    "ci_id": "ci-002",
                    "metric_id": "ping",
                    "status": "ACK",
                    "severity": "WARNING",
                    "message": "Ping jitter",
                    "created_at": created_at,
                    "last_seen": created_at,
                    "ack": True,
                    "ack_by": "operator-1",
                },
                "ci": {
                    "id": "ci-001",
                    "name": "Router-01",
                    "ip": "10.0.0.1",
                    "location_name": "Sede Central",
                },

                "m": {"id": "ping", "protocol": "ICMP"},
                "bs": {
                    "id": "svc-live",
                    "name": "Payments",
                    "owner_t1": "Mesa N1",
                    "owner_t2": "Network Core",
                    "owner_t3": "Platform SRE",
                    "tier": "T2",
                    "impacted_users_count": 1200,
                },
                "sc": {
                    "id": "sla-live",
                    "category": "NETWORK",
                    "service_tier": "Platinum",
                    "sla_minutes": 30,
                },
            },
            now=now,
        )

        assert detail["business_context"]["source"] == "resolved"
        assert detail["business_context"]["business_service"]["name"] == "Payments"
        assert detail["business_context"]["business_service"]["tier"] == "T2"
        assert (
            detail["business_context"]["service_catalog"]["service_tier"] == "Platinum"
        )
        assert detail["business_context"]["service_catalog"]["sla_minutes"] == 30
        assert detail["business_context"]["sla_remaining_minutes"] == 25
        assert detail["itsm_context"]["assignment_state"] == "assigned"
        assert detail["itsm_context"]["assigned_to"] == "operator-1"

    def test_build_event_detail_marks_mixed_source_for_partial_snapshot(self):
        event_service = _load_event_service_module()
        now = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)
        created_at = now - timedelta(minutes=10)

        detail = event_service.build_event_detail_response(
            {
                "e": {
                    "id": "evt-003",
                    "ci_id": "ci-003",
                    "metric_id": "latency",
                    "status": "OPEN",
                    "severity": "CRITICAL",
                    "message": "Latency spike",
                    "created_at": created_at,
                    "last_seen": created_at,
                    "ack": False,
                    "business_service_name": "Inventory",
                },
                "ci": {
                    "id": "ci-001",
                    "name": "Router-01",
                    "ip": "10.0.0.1",
                    "location_name": "Sede Central",
                },

                "m": {"id": "latency", "protocol": "HTTP"},
                "bs": {
                    "id": "svc-live",
                    "name": "Inventory",
                    "owner_t1": "Service Desk",
                    "owner_t2": "AppOps",
                    "owner_t3": "SRE",
                    "impacted_users_count": 75,
                },
                "sc": {
                    "id": "sla-live",
                    "category": "APPLICATION",
                    "service_tier": "Gold",
                    "sla_minutes": 45,
                },
            },
            now=now,
        )

        assert detail["business_context"]["source"] == "mixed"
        assert detail["business_context"]["business_service"]["name"] == "Inventory"
        assert detail["business_context"]["impacted_users"] == 75
        assert detail["business_context"]["sla_remaining_minutes"] == 35

    def test_build_event_detail_returns_degraded_payload_when_context_missing_or_invalid(
        self,
    ):
        event_service = _load_event_service_module()

        detail = event_service.build_event_detail_response(
            {
                "e": {
                    "id": "evt-004",
                    "ci_id": "ci-004",
                    "metric_id": "availability",
                    "status": "OPEN",
                    "severity": "WARNING",
                    "message": "Legacy event without snapshot",
                    "created_at": "not-a-datetime",
                    "last_seen": "not-a-datetime",
                    "ack": False,
                },
                "ci": {"id": "ci-004", "name": "Legacy-CI", "ip": None},
                "m": {"id": "availability", "protocol": "ICMP"},
                "bs": None,
                "sc": None,
            }
        )

        assert detail["event"]["ci_ref"]["id"] == "ci-004"
        assert detail["business_context"]["source"] == "unavailable"
        assert detail["business_context"]["business_service"] is None
        assert detail["business_context"]["service_catalog"] is None
        assert detail["business_context"]["sla_remaining_minutes"] is None
        assert detail["itsm_context"]["escalation_tier"] is None

    def test_build_event_detail_omits_partial_external_ticket_contract(self):
        event_service = _load_event_service_module()

        detail = event_service.build_event_detail_response(
            {
                "e": {
                    "id": "evt-005",
                    "ci_id": "ci-005",
                    "metric_id": "availability",
                    "status": "OPEN",
                    "severity": "WARNING",
                    "message": "Ticket sync degraded",
                    "created_at": datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc),
                    "last_seen": datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc),
                    "ack": False,
                    "external_ticket_status": "Open",
                },
                "ci": {"id": "ci-005", "name": "Router-05", "ip": "10.0.0.5"},
                "m": {"id": "availability", "protocol": "ICMP"},
                "bs": None,
                "sc": None,
            }
        )

        assert detail["itsm_context"]["external_ticket"] is None

    def test_ack_event_raises_404_when_event_is_missing(self, mock_neo4j_session):
        ack_event = _load_event_service_module().ack_event

        with pytest.raises(HTTPException) as exc_info:
            ack_event("missing-event", "testuser")

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Event not found: missing-event"

    def test_close_event_raises_404_when_event_is_missing(self, mock_neo4j_session):
        close_event = _load_event_service_module().close_event

        with pytest.raises(HTTPException) as exc_info:
            close_event(
                "missing-event",
                "testuser",
                comment_message="Causa raíz: Falla de hardware\nNota: Se reemplazó el módulo principal averiado",
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Event not found: missing-event"

    def test_close_event_rejects_normal_close_without_root_cause_and_note(
        self, mock_neo4j_session
    ):
        close_event = _load_event_service_module().close_event
        mock_neo4j_session.set_response(
            "return e.id as event_id", [{"event_id": "evt-001"}]
        )

        with pytest.raises(HTTPException) as exc_info:
            close_event(
                "evt-001", "testuser", forced=False, comment_message="Nota: corto"
            )

        assert exc_info.value.status_code == 400
        assert "Causa raíz" in exc_info.value.detail

    def test_close_event_rejects_normal_close_with_short_note(self, mock_neo4j_session):
        close_event = _load_event_service_module().close_event
        mock_neo4j_session.set_response(
            "return e.id as event_id", [{"event_id": "evt-001"}]
        )

        with pytest.raises(HTTPException) as exc_info:
            close_event(
                "evt-001",
                "testuser",
                forced=False,
                comment_message="Causa raíz: Error de configuración\nNota: breve",
            )

        assert exc_info.value.status_code == 400
        assert "at least 20 characters" in exc_info.value.detail

    def test_close_event_rejects_forced_close_without_reason(self, mock_neo4j_session):
        close_event = _load_event_service_module().close_event
        mock_neo4j_session.set_response(
            "return e.id as event_id", [{"event_id": "evt-001"}]
        )

        with pytest.raises(HTTPException) as exc_info:
            close_event("evt-001", "testuser", forced=True, comment_message="   ")

        assert exc_info.value.status_code == 400
        assert "Forced close requires a reason" in exc_info.value.detail

    def test_add_event_comment_raises_404_when_event_is_missing(
        self, mock_neo4j_session
    ):
        add_event_comment = _load_event_service_module().add_event_comment

        with pytest.raises(HTTPException) as exc_info:
            add_event_comment("missing-event", "testuser", "Investigating...")

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Event not found: missing-event"

    def test_ack_event_writes_ownership_comment_atomically(self, mock_neo4j_session):
        ack_event = _load_event_service_module().ack_event
        mock_neo4j_session.set_response(
            "return e.id as event_id", [{"event_id": "evt-001"}]
        )

        ack_event(
            "evt-001",
            "testuser",
            comment_message="[OWNERSHIP] Caso tomado por testuser - Tier T2",
        )

        params = mock_neo4j_session.queries[0]["params"]
        assert params["audit_message"] == "[AUDIT][OWNERSHIP] Caso tomado por testuser"
        assert params["note_message"] is None

    def test_close_event_writes_closure_comment_atomically(self, mock_neo4j_session):
        close_event = _load_event_service_module().close_event
        # 1. State check
        mock_neo4j_session.set_response(
            "match (e:event {id: $eid}) return e.status", [{"status": "OPEN"}]
        )
        # 2. Update
        mock_neo4j_session.set_response(
            "set e.status = 'closed'", [{"event_id": "evt-001"}]
        )

        close_event(
            "evt-001",
            "testuser",
            forced=False,
            comment_message="[CIERRE] Causa raíz: Falla de hardware\nNota: Se reemplazó el módulo principal",
        )

        params = mock_neo4j_session.queries[1]["params"]
        assert params["audit_message"] == (
            "[AUDIT][CLOSE] Evento cerrado por testuser\n"
            "Causa raíz: Falla de hardware\n"
            "Nota: Se reemplazó el módulo principal"
        )

    def test_close_event_forced_writes_single_canonical_audit_entry(
        self, mock_neo4j_session
    ):
        close_event = _load_event_service_module().close_event
        # 1. State check
        mock_neo4j_session.set_response(
            "match (e:event {id: $eid}) return e.status", [{"status": "OPEN"}]
        )
        # 2. Update
        mock_neo4j_session.set_response(
            "set e.status = 'closed'", [{"event_id": "evt-002"}]
        )

        close_event(
            "evt-002",
            "testuser",
            forced=True,
            comment_message="[CIERRE FORZADO - T2] Motivo: Ventana de mantenimiento",
        )

        params = mock_neo4j_session.queries[1]["params"]
        assert params["audit_message"] == (
            "[AUDIT][FORCED_CLOSE] Cierre forzado por testuser\n"
            "Motivo: Ventana de mantenimiento"
        )
        assert "forced" not in params

    def test_get_event_detail_query_collapses_multiple_sla_matches(
        self, mock_neo4j_session
    ):
        mock_neo4j_session.set_response(
            "return e, ci, m, bs, sc",
            [
                {
                    "e": {
                        "id": "evt-010",
                        "ci_id": "ci-010",
                        "status": "OPEN",
                        "severity": "WARNING",
                        "message": "Latency spike",
                        "created_at": datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc),
                        "ack": False,
                    },
                    "ci": {"id": "ci-010", "name": "Router-10", "ip": "10.0.0.10"},
                    "m": {"id": "latency", "protocol": "SNMP"},
                    "bs": {"id": "svc-010", "name": "WAN"},
                    "sc": {"id": "sla-010", "category": "NETWORK", "sla_minutes": 60},
                }
            ],
        )

        get_event_detail = _load_event_service_module().get_event_detail

        detail = get_event_detail("evt-010")

        assert detail["business_context"]["service_catalog"]["id"] == "sla-010"
        query = mock_neo4j_session.queries[0]["query"]
        assert (
            "head([item in collect(sc) where item is not null]) as sc" in query.lower()
        )

    def test_get_event_detail_raises_404_when_event_is_missing(
        self, mock_neo4j_session
    ):
        mock_neo4j_session.set_response("match (e:event {id: $event_id})", [])

        get_event_detail = _load_event_service_module().get_event_detail

        with pytest.raises(HTTPException) as exc_info:
            get_event_detail("missing-event")

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Event not found"
