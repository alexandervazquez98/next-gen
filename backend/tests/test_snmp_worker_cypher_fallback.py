# backend/tests/test_snmp_worker_cypher_fallback.py
"""Tests for the cypher-param-fallback wrapper around the three Event-write
helpers in ``backend/engines/snmp_worker.py`` (issue #340).

Each helper gets two tests: matching ``ClientError`` triggers fallback;
non-matching ``ClientError`` re-raises unchanged. Strict TDD (tasks.md
§Phase 2): lands BEFORE the writer wirings.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest


class _FakeClientError(Exception):
    """Real exception class for neo4j.exceptions.ClientError in tests."""


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


def _make_session(match_text, exc):
    """Fake Neo4j session that raises ``exc`` on the FIRST call whose query
    contains ``match_text``, then returns ``"fallback-ok"`` after.
    """
    raised = {"done": False}

    def run(query, **params):
        if match_text in query and not raised["done"]:
            raised["done"] = True
            raise exc
        return "fallback-ok"

    fake = MagicMock()
    fake.run.side_effect = lambda query, **params: run(query, **params)
    return fake


# Shared sample rows ------------------------------------------------------------

_FAILURE_ROW = {
    "node_id": "CI-45A1EDD1", "metric_id": "ifInOctets",
    "event_type": "COLLECTION_FAILURE", "severity": "CRITICAL",
    "message": "x", "failure_family": "SNMP_NO_RESPONSE",
    "source_protocol": "SNMP", "correlation_type": "ROOT",
    "propagated_from": None, "root_cause_ci_id": "CI-45A1EDD1",
}

_AVAILABILITY_ROW = {
    "node_id": "CI-45A1EDD1", "metric_id": "icmp_availability",
    "event_type": "AVAILABILITY", "protocol": "ICMP",
    "availability_source": "PING", "value": 0.0,
    "severity": "CRITICAL", "message": "ping down",
    "source_protocol": "ICMP", "correlation_type": "ROOT",
    "propagated_from": None, "root_cause_ci_id": "CI-45A1EDD1",
}

_LATENCY_BREACH_ROW = {
    "node_id": "CI-45A1EDD1", "metric_id": "icmp_latency_ms",
    "event_type": "THRESHOLD_BREACH", "protocol": "ICMP",
    "status": "CRITICAL", "message": "latency breached",
    "source_protocol": "ICMP", "correlation_type": "ROOT",
    "propagated_from": None, "root_cause_ci_id": "CI-45A1EDD1",
}


# Task 2.A — _refresh_snmp_collection_failures -------------------------------


def test_collection_failures_falls_back_on_poll_collector_id_undefined(_install_fake_client_error):
    """Matching ClientError → fallback query omits poll_collector_id."""
    from backend.engines import snmp_worker

    session = _make_session(
        "UNWIND $failures",
        _FakeClientError("Variable poll_collector_id not defined"),
    )
    snmp_worker._refresh_snmp_collection_failures(
        session, [_FAILURE_ROW], lock_db=MagicMock(),
    )
    assert session.run.call_count == 2
    fallback_query = session.run.call_args_list[1].args[0]
    fallback_params = session.run.call_args_list[1].kwargs
    assert "poll_collector_id: $poll_collector_id" not in fallback_query
    assert "poll_collector_id = $poll_collector_id" not in fallback_query
    assert "poll_collector_id" not in fallback_params


def test_collection_failures_non_matching_client_error_reraises(_install_fake_client_error):
    from backend.engines import snmp_worker

    session = _make_session(
        "UNWIND $failures",
        _FakeClientError("Some unrelated syntax issue"),
    )
    with pytest.raises(_FakeClientError, match="unrelated"):
        snmp_worker._refresh_snmp_collection_failures(
            session, [_FAILURE_ROW], lock_db=MagicMock(),
        )
    assert session.run.call_count == 1


# Task 2.B — _refresh_icmp_availability_events --------------------------------


def test_icmp_availability_falls_back_on_poll_collector_id_undefined(_install_fake_client_error):
    from backend.engines import snmp_worker

    session = _make_session(
        "UNWIND $availability_events",
        _FakeClientError("Variable poll_collector_id not defined"),
    )
    snmp_worker._refresh_icmp_availability_events(
        session, [_AVAILABILITY_ROW], lock_db=MagicMock(),
    )
    assert session.run.call_count == 2
    fallback_query = session.run.call_args_list[1].args[0]
    fallback_params = session.run.call_args_list[1].kwargs
    assert "poll_collector_id: $poll_collector_id" not in fallback_query
    assert "poll_collector_id = $poll_collector_id" not in fallback_query
    assert "poll_collector_id" not in fallback_params


def test_icmp_availability_non_matching_client_error_reraises(_install_fake_client_error):
    from backend.engines import snmp_worker

    session = _make_session(
        "UNWIND $availability_events",
        _FakeClientError("Some unrelated syntax issue"),
    )
    with pytest.raises(_FakeClientError, match="unrelated"):
        snmp_worker._refresh_icmp_availability_events(
            session, [_AVAILABILITY_ROW], lock_db=MagicMock(),
        )
    assert session.run.call_count == 1


# Task 2.C — _refresh_icmp_latency_events -------------------------------------


def test_icmp_latency_falls_back_on_poll_collector_id_undefined(_install_fake_client_error):
    from backend.engines import snmp_worker

    session = _make_session(
        "UNWIND $breaches",
        _FakeClientError("Variable poll_collector_id not defined"),
    )
    snmp_worker._refresh_icmp_latency_events(
        session, [_LATENCY_BREACH_ROW], lock_db=MagicMock(),
    )
    assert session.run.call_count == 2
    fallback_query = session.run.call_args_list[1].args[0]
    fallback_params = session.run.call_args_list[1].kwargs
    assert "poll_collector_id: $poll_collector_id" not in fallback_query
    assert "poll_collector_id = $poll_collector_id" not in fallback_query
    assert "poll_collector_id" not in fallback_params


def test_icmp_latency_non_matching_client_error_reraises(_install_fake_client_error):
    from backend.engines import snmp_worker

    session = _make_session(
        "UNWIND $breaches",
        _FakeClientError("Some unrelated syntax issue"),
    )
    with pytest.raises(_FakeClientError, match="unrelated"):
        snmp_worker._refresh_icmp_latency_events(
            session, [_LATENCY_BREACH_ROW], lock_db=MagicMock(),
        )
    assert session.run.call_count == 1