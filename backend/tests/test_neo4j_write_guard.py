# backend/tests/test_neo4j_write_guard.py
"""Unit tests for backend/services/neo4j_write_guard.py.

Strict TDD (tasks.md §Phase 1): this file lands BEFORE the helper.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest


class _FakeClientError(Exception):
    """Real exception class standing in for neo4j.exceptions.ClientError.

    The conftest stubs ``sys.modules['neo4j.exceptions']`` with a
    MagicMock, making ``ClientError`` a MagicMock instance (not a class)
    and breaking ``isinstance(...)``. We patch the helper module's
    captured ``_CLIENT_ERROR_CLASS`` to this real class.

    The Neo4j Python driver exposes the rejection text via the ``message``
    attribute, so the fake mirrors that surface (verify-report
    CRITICAL #2 — predicate reads ``error.message``).
    """

    def __init__(self, message=""):
        super().__init__(message)
        self.message = message


@pytest.fixture
def _install_fake_client_error(monkeypatch):
    """Patch ``_CLIENT_ERROR_CLASS`` on BOTH module aliases of the helper.

    Production code uses ``from services.neo4j_write_guard import ...``
    while tests use ``from backend.services.neo4j_write_guard import ...``
    — Python loads these as two DIFFERENT module objects. The function
    reads from whichever alias imported it, so patch both.
    """
    from backend.services import neo4j_write_guard as guard_module

    monkeypatch.setattr(guard_module, "_CLIENT_ERROR_CLASS", _FakeClientError)
    try:
        from services import neo4j_write_guard as services_guard_module

        monkeypatch.setattr(services_guard_module, "_CLIENT_ERROR_CLASS", _FakeClientError)
    except ImportError:
        pass
    return guard_module


# Tests for ``is_poll_collector_id_undefined_error`` (case e) ----------------


def test_predicate_unit_cases(_install_fake_client_error):
    """True / false positives / wrong exception type — design §8 contract."""
    guard_module = _install_fake_client_error
    # True: matching ClientError
    assert (
        guard_module.is_poll_collector_id_undefined_error(
            _FakeClientError("Variable poll_collector_id not defined")
        )
        is True
    )
    # False: ClientError with unrelated message
    assert (
        guard_module.is_poll_collector_id_undefined_error(
            _FakeClientError("Syntax error: unexpected token")
        )
        is False
    )
    # False: wrong exception type even with matching message
    assert (
        guard_module.is_poll_collector_id_undefined_error(
            RuntimeError("Variable poll_collector_id not defined")
        )
        is False
    )


# Tests for ``run_with_cypher_param_fallback`` (cases a–d) -------------------


def test_primary_success_skips_fallback(_install_fake_client_error):
    """Primary success → fallback MUST NOT run."""
    guard_module = _install_fake_client_error
    logger = logging.getLogger("test_primary_success_skips_fallback")

    class _FakeSession:
        def __init__(self):
            self.calls = []

        def run(self, query, **params):
            self.calls.append((query, params))
            return "primary-result"

    fake_session = _FakeSession()
    result = guard_module.run_with_cypher_param_fallback(
        fake_session,
        "primary query",
        {"poll_collector_id": "host-1"},
        "fallback query",
        {},
        guard_module.is_poll_collector_id_undefined_error,
        logger,
    )
    assert result == "primary-result"
    assert fake_session.calls == [("primary query", {"poll_collector_id": "host-1"})]


def test_matching_client_error_triggers_fallback_and_logs(_install_fake_client_error, caplog):
    """Matching ClientError → fallback runs; ERROR log includes both queries."""
    guard_module = _install_fake_client_error
    logger = logging.getLogger("test_matching_client_error_triggers_fallback_and_logs")

    class _FakeSession:
        def __init__(self):
            self.calls = []

        def run(self, query, **params):
            self.calls.append((query, params))
            if "primary" in query:
                raise _FakeClientError("Variable poll_collector_id not defined")
            return "fallback-result"

    fake_session = _FakeSession()
    with caplog.at_level(logging.ERROR, logger=logger.name):
        result = guard_module.run_with_cypher_param_fallback(
            fake_session,
            "primary query",
            {"poll_collector_id": "host-1"},
            "fallback query",
            {},
            guard_module.is_poll_collector_id_undefined_error,
            logger,
        )
    assert result == "fallback-result"
    assert fake_session.calls[0][0] == "primary query"
    assert fake_session.calls[1][0] == "fallback query"
    assert "poll_collector_id" not in fake_session.calls[1][1]
    # Log contract (design §10): ERROR with marker + both query strings.
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records, "expected at least one ERROR log entry"
    combined = " ".join(r.getMessage() for r in error_records)
    assert "cypher-param-fallback" in combined
    assert "primary query" in combined
    assert "fallback query" in combined


def test_non_matching_client_error_reraises_without_fallback(_install_fake_client_error):
    """Non-matching ClientError → re-raises; fallback MUST NOT run."""
    guard_module = _install_fake_client_error
    logger = logging.getLogger("test_non_matching_client_error_reraises_without_fallback")

    class _FakeSession:
        def __init__(self):
            self.calls = []

        def run(self, query, **params):
            self.calls.append((query, params))
            raise _FakeClientError("Some unrelated syntax issue")

    fake_session = _FakeSession()
    with pytest.raises(_FakeClientError, match="unrelated"):
        guard_module.run_with_cypher_param_fallback(
            fake_session,
            "primary query",
            {},
            "fallback query",
            {},
            guard_module.is_poll_collector_id_undefined_error,
            logger,
        )
    assert len(fake_session.calls) == 1


def test_non_client_error_reraises_unchanged(_install_fake_client_error):
    """Non-ClientError exception → re-raises unchanged; fallback MUST NOT run."""
    guard_module = _install_fake_client_error
    logger = logging.getLogger("test_non_client_error_reraises_unchanged")

    class _FakeSession:
        def __init__(self):
            self.calls = []

        def run(self, query, **params):
            self.calls.append((query, params))
            raise RuntimeError("boom")

    fake_session = _FakeSession()
    with pytest.raises(RuntimeError, match="boom"):
        guard_module.run_with_cypher_param_fallback(
            fake_session,
            "primary query",
            {},
            "fallback query",
            {},
            guard_module.is_poll_collector_id_undefined_error,
            logger,
        )
    assert len(fake_session.calls) == 1


# CRITICAL #2 — Predicate must read ``error.message``, not ``str(error) -------


class _FakeClientErrorWithMessageError(_FakeClientError):
    """Real-exception-class stand-in for ``neo4j.exceptions.ClientError``
    with a ``message`` attribute that DIFFERS from ``str(error)``.

    The Neo4j Python driver exposes the rejection text via the
    ``message`` attribute on ``ClientError``. The production spec (design
    §8) requires the predicate to read ``error.message``, not
    ``str(error)`` (verify-report CRITICAL #2).
    """

    def __init__(self, message):
        # The super().__init__ value becomes the result of str(error).
        # We deliberately make it unrelated to ``message`` so a str-based
        # predicate can be told apart from a .message-based one.
        super().__init__("__unrelated__str__repr__")
        self.message = message


def test_predicate_uses_error_message_attribute(_install_fake_client_error):
    """CRITICAL #2 fix — predicate reads ``error.message``, not ``str(error)``.

    Three discriminating cases:

    1. ``message`` matches AND ``str(error)`` does NOT contain the substrings.
       Old predicate returns False; new predicate returns True.
    2. ``message`` is missing ``"not defined"``.
       Predicate MUST reject (False).
    3. ``message`` is missing ``"poll_collector_id"``.
       Predicate MUST reject (False).
    """
    guard_module = _install_fake_client_error

    # Case 1 — production-shaped message, str() deliberately unrelated.
    err_match = _FakeClientErrorWithMessageError(
        message="Variable poll_collector_id not defined",
    )
    assert guard_module.is_poll_collector_id_undefined_error(err_match) is True, (
        "predicate MUST accept ClientError whose .message matches the spec, "
        "even when str(error) returns unrelated text — design §8"
    )

    # Case 2 — message missing 'not defined'.
    err_no_not_defined = _FakeClientErrorWithMessageError(
        message="Variable poll_collector_id something_else_completely",
    )
    assert (
        guard_module.is_poll_collector_id_undefined_error(err_no_not_defined) is False
    ), "predicate MUST reject ClientError whose .message lacks 'not defined'"

    # Case 3 — message missing 'poll_collector_id'.
    err_no_param = _FakeClientErrorWithMessageError(
        message="Variable other_param not defined",
    )
    assert (
        guard_module.is_poll_collector_id_undefined_error(err_no_param) is False
    ), "predicate MUST reject ClientError whose .message lacks 'poll_collector_id'"


# CRITICAL #1 — fallback queries must not leave dangling commas -----------------


def test_fallback_query_has_no_dangling_commas(_install_fake_client_error):
    """CRITICAL #1 fix — every protected writer's fallback Cypher MUST have no
    dangling commas before ``}``, ``MERGE``, ``WITH``, or query end.

    Strategy: drive each writer with a representative input that triggers
    the matching ``ClientError`` so the fallback query is the SECOND
    ``session.run`` call's query string. Then assert the query has no
    ``,\\s*}``, ``,\\s*MERGE``, ``,\\s*WITH``, or ``,\\s*\\n\"\"\"`` —
    any of those patterns indicates the fallback removal left an invalid
    Cypher tail.
    """
    from unittest.mock import MagicMock

    # Sample rows — minimal inputs the writers accept.
    failure_row = {
        "node_id": "CI-1",
        "metric_id": "m",
        "event_type": "COLLECTION_FAILURE",
        "severity": "CRITICAL",
        "message": "x",
        "failure_family": "SNMP_NO_RESPONSE",
        "source_protocol": "SNMP",
        "correlation_type": "ROOT",
        "propagated_from": None,
        "root_cause_ci_id": "CI-1",
    }
    availability_row = {
        "node_id": "CI-1",
        "metric_id": "icmp_avail",
        "event_type": "AVAILABILITY",
        "protocol": "ICMP",
        "availability_source": "PING",
        "value": 0.0,
        "severity": "CRITICAL",
        "message": "down",
        "source_protocol": "ICMP",
        "correlation_type": "ROOT",
        "propagated_from": None,
        "root_cause_ci_id": "CI-1",
    }
    latency_row = {
        "node_id": "CI-1",
        "metric_id": "icmp_latency_ms",
        "event_type": "THRESHOLD_BREACH",
        "protocol": "ICMP",
        "status": "CRITICAL",
        "message": "breach",
        "source_protocol": "ICMP",
        "correlation_type": "ROOT",
        "propagated_from": None,
        "root_cause_ci_id": "CI-1",
    }

    import re

    bad_patterns = [
        (re.compile(r",\s*}"), "trailing comma before }"),
        (re.compile(r",\s*MERGE\b"), "trailing comma before MERGE"),
        (re.compile(r",\s*WITH\b"), "trailing comma before WITH"),
        # Trailing comma right before the closing """ of the query string.
        # The query is indented, so the literal "\n                    \"\"\"" appears.
        (re.compile(r",\s*\n\s*\"\"\""), "trailing comma before query end"),
    ]

    def _make_session():
        raised = {"done": False}

        def run(query, **params):
            if not raised["done"]:
                raised["done"] = True
                raise _FakeClientError("Variable poll_collector_id not defined")
            return "fallback-ok"

        fake = MagicMock()
        fake.run.side_effect = run
        return fake

    def _check(query):
        for pattern, desc in bad_patterns:
            assert not pattern.search(
                query
            ), f"Fallback Cypher has {desc}: matched {pattern.pattern!r}\n--- query ---\n{query}"

    # 1) _refresh_snmp_collection_failures -----------------------------------
    from backend.engines import snmp_worker

    session = _make_session()
    snmp_worker._refresh_snmp_collection_failures(
        session,
        [failure_row],
        lock_db=MagicMock(),
    )
    fallback_query = session.run.call_args_list[1].args[0]
    _check(fallback_query)

    # 2) _refresh_icmp_availability_events ------------------------------------
    session = _make_session()
    snmp_worker._refresh_icmp_availability_events(
        session,
        [availability_row],
        lock_db=MagicMock(),
    )
    fallback_query = session.run.call_args_list[1].args[0]
    _check(fallback_query)

    # 3) _refresh_icmp_latency_events -----------------------------------------
    session = _make_session()
    snmp_worker._refresh_icmp_latency_events(
        session,
        [latency_row],
        lock_db=MagicMock(),
    )
    fallback_query = session.run.call_args_list[1].args[0]
    _check(fallback_query)


# WARNING follow-up — concurrent writers serialize around fallback -----------


def test_lock_acquired_before_session_run_in_fallback_path(_install_fake_client_error):
    """Verify-report WARNING: ``acquire_event_triplet_lock`` is called BEFORE
    the FIRST ``session.run`` (primary) AND remains in scope across the
    fallback ``session.run`` (re-raise path). If the lock were re-acquired
    after a fallback, two writers could deadlock or duplicate Events.

    This is a structural ordering test: capture the call order between
    ``acquire_event_triplet_lock`` and ``session.run``, then assert the
    lock precedes the first run, and no second lock acquisition happens
    between the primary and fallback ``session.run`` calls.
    """
    from unittest.mock import MagicMock, patch

    failure_row = {
        "node_id": "CI-1",
        "metric_id": "m",
        "event_type": "COLLECTION_FAILURE",
        "severity": "CRITICAL",
        "message": "x",
        "failure_family": "SNMP_NO_RESPONSE",
        "source_protocol": "SNMP",
        "correlation_type": "ROOT",
        "propagated_from": None,
        "root_cause_ci_id": "CI-1",
    }

    events = []  # ordered log: ("lock", triplet) or ("run", query_marker)

    def spy_acquire(pg_db, ci_id, metric_id, event_type, **_kwargs):
        events.append(("lock", (ci_id, metric_id, event_type)))

    raised = {"done": False}

    def spy_run(query, **params):
        events.append(("run", "PRIMARY" if "UNWIND $failures" in query else "FALLBACK"))
        if not raised["done"]:
            raised["done"] = True
            raise _FakeClientError("Variable poll_collector_id not defined")
        return "fallback-ok"

    session = MagicMock()
    session.run.side_effect = spy_run

    with patch(
        "backend.engines.snmp_worker.acquire_event_triplet_lock",
        side_effect=spy_acquire,
    ):
        from backend.engines import snmp_worker

        snmp_worker._refresh_snmp_collection_failures(
            session,
            [failure_row],
            lock_db=MagicMock(),
        )

    lock_count = sum(1 for e in events if e[0] == "lock")
    run_count = sum(1 for e in events if e[0] == "run")

    # Exactly ONE lock acquisition for this triplet (not 2 — the fallback
    # must NOT re-acquire).
    assert lock_count == 1, f"expected exactly 1 lock acquisition, got {lock_count}: {events}"
    # Two session.run calls (primary + fallback).
    assert run_count == 2, f"expected 2 session.run calls (primary + fallback), got {run_count}"

    # The lock event MUST appear before the first run event.
    first_lock = next(i for i, e in enumerate(events) if e[0] == "lock")
    first_run = next(i for i, e in enumerate(events) if e[0] == "run")
    assert first_lock < first_run, f"lock must precede first session.run: {events}"


def _make_context_mock():
    """Context-manager mock that returns itself from __enter__."""
    fake = MagicMock()
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False
    return fake
