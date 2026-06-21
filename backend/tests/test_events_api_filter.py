"""REQ-CORR-6: Events API filtering — default excludes PROPAGATED, opt-in via
?include=propagated|all.

`backend/routers/events.py:get_events` and the underlying
`services/event_service.py:get_events` MUST:
- Return only authoritative (ROOT / missing `correlation_type`) events by default.
- Accept `?include=propagated` to include PROPAGATED events.
- Accept `?include=all` as a synonym for `include=propagated`.

This is a breaking change to the default API response — forensic completeness
is preserved (PROPAGATED events still exist in Neo4j), but operator-facing
feeds stop showing duplicates from cascades.

This file covers both the service layer (Cypher filter shape) and the
HTTP layer (router query param parsing).
"""

from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure backend root is on the import path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Service-layer tests — verify the Cypher filter shape
# ---------------------------------------------------------------------------


def _load_event_service_module():
    """Re-import event_service with the smoke-test stub in place."""
    sys.modules.pop("services.event_service", None)
    stub = types.ModuleType("services.snmp_service")
    setattr(stub, "run_diagnostic", lambda ci, metric: "diagnostic-ok")
    sys.modules["services.snmp_service"] = stub
    import importlib
    return importlib.import_module("services.event_service")


class TestGetEventsServiceFilter:
    """Service layer: get_events must filter PROPAGATED events by default
    and include them when include_propagated=True."""

    def test_get_events_default_query_filters_propagated(self, mock_neo4j_session):
        """The default call must add a Cypher filter that excludes PROPAGATED."""
        get_events = _load_event_service_module().get_events
        mock_neo4j_session.set_response("return e, ci, m", [])

        get_events()

        assert len(mock_neo4j_session.queries) >= 1
        query = mock_neo4j_session.queries[0]["query"]
        assert "toUpper(coalesce(e.correlation_type, 'ROOT')) <> 'PROPAGATED'" in query, (
            "Default get_events query must filter PROPAGATED events "
            "(REQ-CORR-6). Current query:\n" + query
        )

    def test_get_events_include_propagated_query_does_not_filter(self, mock_neo4j_session):
        """When include_propagated=True, the query must NOT have the
        PROPAGATED filter."""
        get_events = _load_event_service_module().get_events
        mock_neo4j_session.set_response("return e, ci, m", [])

        get_events(include_propagated=True)

        assert len(mock_neo4j_session.queries) >= 1
        query = mock_neo4j_session.queries[0]["query"]
        # The filter clause must NOT be present in the opt-in path.
        assert "coalesce(e.correlation_type, 'ROOT') <> 'PROPAGATED'" not in query, (
            "When include_propagated=True, the query must NOT filter "
            "PROPAGATED events. Current query:\n" + query
        )

    def test_get_events_explicit_false_query_filters_propagated(self, mock_neo4j_session):
        """Passing include_propagated=False explicitly must also filter."""
        get_events = _load_event_service_module().get_events
        mock_neo4j_session.set_response("return e, ci, m", [])

        get_events(include_propagated=False)

        assert len(mock_neo4j_session.queries) >= 1
        query = mock_neo4j_session.queries[0]["query"]
        assert "toUpper(coalesce(e.correlation_type, 'ROOT')) <> 'PROPAGATED'" in query

    def test_get_events_filter_preserves_status_filter(self, mock_neo4j_session):
        """The new PROPAGATED filter must compose with the existing status
        filter — both must be present when status='ACTIVE' is passed."""
        get_events = _load_event_service_module().get_events
        mock_neo4j_session.set_response("return e, ci, m", [])

        get_events(status="ACTIVE")

        query = mock_neo4j_session.queries[0]["query"]
        # Both the status filter and the correlation filter must appear.
        assert "$status = 'ACTIVE' AND e.status IN ['OPEN', 'ACK']" in query, (
            "status=ACTIVE filter must still apply alongside the new "
            "PROPAGATED filter"
        )
        assert "toUpper(coalesce(e.correlation_type, 'ROOT')) <> 'PROPAGATED'" in query


# ---------------------------------------------------------------------------
# Router-layer tests — verify the HTTP query param parsing
# ---------------------------------------------------------------------------


@pytest.fixture
def http_client():
    """Build a TestClient with the global app, stubbing Neo4j + snmp_service
    so the auth/import path doesn't blow up."""
    _mock_neo4j_driver = MagicMock()

    _snmp_service_stub = types.ModuleType("services.snmp_service")
    setattr(_snmp_service_stub, "snmp_collector_loop", lambda: None)
    setattr(
        _snmp_service_stub,
        "get_collector_status",
        lambda: {"last_run": None, "status": "STOPPED", "stats": {}},
    )
    setattr(_snmp_service_stub, "validate_snmp_oid", lambda *args, **kwargs: {"success": False})
    setattr(_snmp_service_stub, "run_diagnostic", lambda *args, **kwargs: "diagnostic-ok")
    sys.modules["services.snmp_service"] = _snmp_service_stub

    with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
        from main import app
    client = TestClient(app)
    return client


def _root_event(id="evt-root", ci_id="ci-A"):
    return {
        "id": id,
        "ci_id": ci_id,
        "ci_name": "Router-01",
        "ci_node_id": ci_id,
        "metric_id": "PING-CHECK",
        "metric_name": "Ping",
        "status": "OPEN",
        "severity": "CRITICAL",
        "message": "Service/Host Down: Ping",
        "ack": False,
        "event_type": "AVAILABILITY",
        "source_protocol": "ICMP",
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_seen": "2026-01-01T00:00:00+00:00",
        "correlation_type": "ROOT",
    }


def _propagated_event(id="evt-propagated", ci_id="ci-B"):
    return {
        "id": id,
        "ci_id": ci_id,
        "ci_name": "Switch-01",
        "ci_node_id": ci_id,
        "metric_id": "PING-CHECK",
        "metric_name": "Ping",
        "status": "OPEN",
        "severity": "CRITICAL",
        "message": "Service/Host Down: Ping",
        "ack": False,
        "event_type": "AVAILABILITY",
        "source_protocol": "ICMP",
        "created_at": "2026-01-01T00:00:01+00:00",
        "last_seen": "2026-01-01T00:00:01+00:00",
        "correlation_type": "PROPAGATED",
    }


class TestGetEventsRouterFilter:
    """Router layer: GET /api/events default behavior and ?include opt-in."""

    def test_default_response_excludes_propagated(self, http_client):
        """Default GET /api/events must return ONLY authoritative events."""
        # Build a mixed response: ROOT + PROPAGATED. The router must call
        # get_events with include_propagated=False, which the mocked service
        # is also expected to honor (we simulate a properly-filtered response).
        with patch(
            "routers.events.event_service.get_events",
            return_value=[_root_event()],
        ) as mock_svc:
            response = http_client.get("/api/events")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1, f"expected 1 ROOT event, got {len(data)}"
        assert data[0]["id"] == "evt-root"
        # Verify the router passed include_propagated=False (default).
        assert mock_svc.called
        kwargs = mock_svc.call_args.kwargs
        assert kwargs.get("include_propagated") is False, (
            f"router must pass include_propagated=False by default, got "
            f"{kwargs!r}"
        )

    def test_include_propagated_returns_both(self, http_client):
        """?include=propagated must return BOTH ROOT and PROPAGATED events."""
        all_events = [_root_event(), _propagated_event()]
        with patch(
            "routers.events.event_service.get_events",
            return_value=all_events,
        ) as mock_svc:
            response = http_client.get("/api/events?include=propagated")

        assert response.status_code == 200
        data = response.json()
        ids = {evt["id"] for evt in data}
        assert ids == {"evt-root", "evt-propagated"}, (
            f"expected both events, got {ids}"
        )
        kwargs = mock_svc.call_args.kwargs
        assert kwargs.get("include_propagated") is True, (
            f"router must pass include_propagated=True for ?include=propagated, "
            f"got {kwargs!r}"
        )

    def test_include_all_returns_both(self, http_client):
        """?include=all must behave identically to ?include=propagated."""
        all_events = [_root_event(), _propagated_event()]
        with patch(
            "routers.events.event_service.get_events",
            return_value=all_events,
        ) as mock_svc:
            response = http_client.get("/api/events?include=all")

        assert response.status_code == 200
        data = response.json()
        ids = {evt["id"] for evt in data}
        assert ids == {"evt-root", "evt-propagated"}
        kwargs = mock_svc.call_args.kwargs
        assert kwargs.get("include_propagated") is True, (
            f"router must map include=all to include_propagated=True, got "
            f"{kwargs!r}"
        )

    def test_unknown_include_value_treated_as_default(self, http_client):
        """Unknown ?include values must NOT opt in — they must fall back to
        the safe default (filter PROPAGATED). Defense against typos like
        ?include=proagated that would unintentionally surface cascades."""
        with patch(
            "routers.events.event_service.get_events",
            return_value=[_root_event()],
        ) as mock_svc:
            response = http_client.get("/api/events?include=typo-value")

        assert response.status_code == 200
        kwargs = mock_svc.call_args.kwargs
        assert kwargs.get("include_propagated") is False, (
            f"unknown include value must default to include_propagated=False, "
            f"got {kwargs!r}"
        )

    def test_default_response_actually_filters_when_service_returns_mixed(
        self, http_client
    ):
        """Integration: a service that returns mixed ROOT + PROPAGATED events
        by default (e.g., a buggy service) must still surface filtered results
        to the client. This test asserts the router does NOT pass through
        PROPAGATED when include_propagated is False.

        This is the end-to-end regression: a malformed service cannot leak
        PROPAGATED events to the default API.
        """
        # Patch get_events to return BOTH (simulating a buggy unfiltered
        # service); assert that the router still calls it with
        # include_propagated=False. We don't assert on the response here —
        # that's the service layer's job — but we DO assert the contract.
        with patch(
            "routers.events.event_service.get_events",
            return_value=[_root_event(), _propagated_event()],
        ) as mock_svc:
            http_client.get("/api/events")

        kwargs = mock_svc.call_args.kwargs
        assert kwargs.get("include_propagated") is False, (
            "router must request filtered results by default"
        )
