# backend/tests/test_neo4j_write_guard.py
"""Unit tests for backend/services/neo4j_write_guard.py.

Strict TDD (tasks.md §Phase 1): this file lands BEFORE the helper.
"""
from __future__ import annotations

import logging

import pytest


class _FakeClientError(Exception):
    """Real exception class standing in for neo4j.exceptions.ClientError.

    The conftest stubs ``sys.modules['neo4j.exceptions']`` with a
    MagicMock, making ``ClientError`` a MagicMock instance (not a class)
    and breaking ``isinstance(...)``. We patch the helper module's
    captured ``_CLIENT_ERROR_CLASS`` to this real class.
    """


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
    assert guard_module.is_poll_collector_id_undefined_error(
        _FakeClientError("Variable poll_collector_id not defined")
    ) is True
    # False: ClientError with unrelated message
    assert guard_module.is_poll_collector_id_undefined_error(
        _FakeClientError("Syntax error: unexpected token")
    ) is False
    # False: wrong exception type even with matching message
    assert guard_module.is_poll_collector_id_undefined_error(
        RuntimeError("Variable poll_collector_id not defined")
    ) is False


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
        fake_session, "primary query", {"poll_collector_id": "host-1"},
        "fallback query", {},
        guard_module.is_poll_collector_id_undefined_error, logger,
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
            fake_session, "primary query", {"poll_collector_id": "host-1"},
            "fallback query", {},
            guard_module.is_poll_collector_id_undefined_error, logger,
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
            fake_session, "primary query", {},
            "fallback query", {},
            guard_module.is_poll_collector_id_undefined_error, logger,
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
            fake_session, "primary query", {},
            "fallback query", {},
            guard_module.is_poll_collector_id_undefined_error, logger,
        )
    assert len(fake_session.calls) == 1