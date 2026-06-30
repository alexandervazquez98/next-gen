# backend/tests/test_snmp_service_cypher_fallback.py
"""Tests for the cypher-param-fallback wrapper around the two
``backend/services/snmp_service.py::store_metric_result`` Event-write
sites (issue #340 — defense-in-depth per proposal §Scope).

Strict TDD (tasks.md §Phase 3): lands BEFORE the wirings.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class _FakeClientError(Exception):
    """Real exception class for neo4j.exceptions.ClientError in tests.

    Mirrors the Neo4j Python driver surface: ``.message`` attribute carries
    the rejection text (verify-report CRITICAL #2 — predicate reads
    ``error.message``).
    """

    def __init__(self, message=""):
        super().__init__(message)
        self.message = message


@pytest.fixture
def _install_fake_client_error(monkeypatch):
    """Patch ``_CLIENT_ERROR_CLASS`` on both module aliases of the helper.

    Production code uses ``from services.neo4j_write_guard import ...``
    while tests use ``from backend.services.neo4j_write_guard import ...`` —
    Python loads these as two different module objects, both must be patched.
    """
    from backend.services import neo4j_write_guard as guard_module

    monkeypatch.setattr(guard_module, "_CLIENT_ERROR_CLASS", _FakeClientError)
    try:
        from services import neo4j_write_guard as services_guard_module
        monkeypatch.setattr(services_guard_module, "_CLIENT_ERROR_CLASS", _FakeClientError)
    except ImportError:
        pass
    return guard_module


def _make_context_mock():
    """MagicMock supporting ``with`` that returns itself from __enter__."""
    fake = MagicMock()
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False
    return fake


# Task 3.A — existing-Event SET path (~line 530) ----------------------------


def test_store_metric_result_existing_event_path_falls_back(
    _install_fake_client_error, mock_neo4j_driver
):
    """Existing-Event SET triggers fallback when Neo4j rejects $poll_collector_id."""
    import importlib
    import sys

    sys.modules.pop("services.snmp_service", None)
    snmp_service = importlib.import_module("services.snmp_service")

    session = mock_neo4j_driver.mock_session
    # Seed existing-Event lookup → exercises SET path, not CREATE path.
    session.set_response(
        "MATCH (existing:Event)",
        [{"existing_element_id": "element-123", "existing_status": "OPEN"}],
    )

    original_run = session.run
    raised = {"done": False}

    def selective_run(query, **params):
        # Record the call BEFORE raising so the primary attempt shows up in
        # session.queries alongside the fallback.
        result = original_run(query, **params)
        if "elementId(existing) = $existing_element_id" in query and not raised["done"]:
            raised["done"] = True
            raise _FakeClientError("Variable poll_collector_id not defined")
        return result

    session.run = selective_run
    fake_pg = _make_context_mock()

    with patch("services.snmp_service.SessionLocal", return_value=fake_pg):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {"id": "cpu", "name": "cpu", "protocol": "SNMP",
             "criticality": 3, "critical": 90},
            "97", "OK", None, mock_neo4j_driver,
        )

    set_path_queries = [
        q for q in session.queries
        if "elementId(existing) = $existing_element_id" in q["query"]
    ]
    assert len(set_path_queries) >= 2
    fallback = set_path_queries[1]
    assert "poll_collector_id" not in fallback["query"]
    assert "poll_collector_id" not in fallback["params"]


# Task 3.B — new-Event CREATE path (~line 575) -------------------------------


def test_store_metric_result_create_event_path_falls_back(
    _install_fake_client_error, mock_neo4j_driver
):
    """New-Event CREATE triggers fallback when Neo4j rejects $poll_collector_id."""
    import importlib
    import sys

    sys.modules.pop("services.snmp_service", None)
    snmp_service = importlib.import_module("services.snmp_service")

    session = mock_neo4j_driver.mock_session
    # Seed existing-Event lookup EMPTY → exercises CREATE path.
    session.set_response("MATCH (existing:Event)", [])

    original_run = session.run
    raised = {"done": False}

    def selective_run(query, **params):
        result = original_run(query, **params)
        if "CREATE (e:Event" in query and not raised["done"]:
            raised["done"] = True
            raise _FakeClientError("Variable poll_collector_id not defined")
        return result

    session.run = selective_run
    fake_pg = _make_context_mock()

    with patch("services.snmp_service.SessionLocal", return_value=fake_pg):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {"id": "cpu", "name": "cpu", "protocol": "SNMP",
             "criticality": 3, "critical": 90},
            "97", "OK", None, mock_neo4j_driver,
        )

    create_path_queries = [
        q for q in session.queries if "CREATE (e:Event" in q["query"]
    ]
    assert len(create_path_queries) >= 2
    fallback = create_path_queries[1]
    assert "poll_collector_id" not in fallback["query"]
    assert "poll_collector_id" not in fallback["params"]