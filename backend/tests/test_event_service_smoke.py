"""Smoke tests for event_service — verify the import path and basic structure.

These are intentionally minimal to confirm the test infrastructure works.
Full event lifecycle tests should go in test_event_lifecycle.py.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from models.core import MetricDef


class TestEventServiceImports:
    """Verify that event_service can be imported and its functions exist."""

    def test_event_service_imports(self):
        """The module should import without errors."""
        from services import event_service

        assert hasattr(event_service, "get_events")
        assert hasattr(event_service, "get_related_events")
        assert hasattr(event_service, "ack_event")
        assert hasattr(event_service, "close_event")
        assert hasattr(event_service, "add_event_comment")
        assert hasattr(event_service, "prune_recovered_events")
        assert hasattr(event_service, "run_event_diagnostic")


class TestEventServiceSmoke:
    """Minimal smoke tests with mocked DB to verify the mocking infrastructure."""

    def test_get_events_returns_empty_with_mock(self, mock_neo4j_session):
        """get_events should return empty list when no events exist."""
        mock_neo4j_session.set_response("event", [])

        from services.event_service import get_events

        result = get_events()

        assert result == []

    def test_get_events_filters_by_status(self, mock_neo4j_session):
        """get_events should pass status filter to the query."""
        from services.event_service import get_events

        get_events(status="OPEN")

        assert len(mock_neo4j_session.queries) >= 1
        query = mock_neo4j_session.queries[0]["query"].lower()
        assert "status" in query

    def test_ack_event_sets_ack_status(self, mock_neo4j_session):
        """ack_event should set status to ACK."""
        from services.event_service import ack_event

        ack_event("evt-001", "testuser")

        assert len(mock_neo4j_session.queries) >= 1
        query = mock_neo4j_session.queries[0]["query"].upper()
        assert "ACK" in query
        assert "evt-001" in mock_neo4j_session.queries[0]["params"]["eid"]

    def test_close_event_sets_closed_status(self, mock_neo4j_session):
        """close_event should set status to CLOSED."""
        from services.event_service import close_event

        close_event("evt-001", "testuser")

        assert len(mock_neo4j_session.queries) >= 1
        query = mock_neo4j_session.queries[0]["query"].upper()
        assert "CLOSED" in query

    def test_add_event_comment_appends_comment(self, mock_neo4j_session):
        """add_event_comment should append to comments array."""
        from services.event_service import add_event_comment

        add_event_comment("evt-001", "testuser", "Investigating...")

        assert len(mock_neo4j_session.queries) >= 1
        query = mock_neo4j_session.queries[0]["query"].lower()
        assert "comments" in query
        assert "testuser" in mock_neo4j_session.queries[0]["params"]["user"]
        assert "Investigating..." in mock_neo4j_session.queries[0]["params"]["msg"]

    def test_prune_recovered_events_cleans_up(self, mock_neo4j_session):
        """prune_recovered_events should close RECOVERED events without ack."""
        from services.event_service import prune_recovered_events

        mock_neo4j_session.set_response("recovered", [{"closed_count": 3}])

        result = prune_recovered_events("system")

        assert result["count"] == 3
        assert "Cleaned up" in result["message"]
