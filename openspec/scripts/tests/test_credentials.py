"""Strict-TDD tests for Neo4j URI and credential handling (WU-7)."""

from __future__ import annotations

import sys
import types

import pytest


@pytest.mark.parametrize(
    ("argv_uri", "env", "expected"),
    [
        ("bolt://arg-host:7687", {}, "bolt://arg-host:7687"),
        (None, {"NEO4J_URI": "bolt://env-host:7687"}, "bolt://env-host:7687"),
        (
            "bolt://arg-host:7687",
            {"NEO4J_URI": "bolt://env-host:7687"},
            "bolt://arg-host:7687",
        ),
    ],
)
def test_resolve_uri_precedence(argv_uri, env, expected):
    from openspec.scripts.cmdb_backfill_orphans import _resolve_neo4j_uri

    assert _resolve_neo4j_uri(argv_uri, env) == expected


def test_resolve_uri_missing_has_safe_error(capsys):
    from openspec.scripts.cmdb_backfill_orphans import (
        MissingURLError,
        _resolve_neo4j_uri,
    )

    with pytest.raises(MissingURLError) as exc_info:
        _resolve_neo4j_uri(None, {})

    assert str(exc_info.value) == "error: --neo4j-uri (or $NEO4J_URI) required"
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert "test-password" not in str(exc_info.value)


def test_open_driver_uses_auth_without_exposing_credentials(monkeypatch):
    from openspec.scripts.cmdb_backfill_orphans import _open_neo4j_driver

    calls = []
    sentinel = object()

    class GraphDatabase:
        @staticmethod
        def driver(uri, auth):
            calls.append((uri, auth))
            return sentinel

    module = types.ModuleType("neo4j")
    module.GraphDatabase = GraphDatabase
    monkeypatch.setitem(sys.modules, "neo4j", module)

    assert _open_neo4j_driver(
        "bolt://db-host:7687", "test-user", "test-password"
    ) is sentinel
    assert calls == [("bolt://db-host:7687", ("test-user", "test-password"))]


def test_open_driver_redacts_driver_exception(monkeypatch):
    from openspec.scripts.cmdb_backfill_orphans import _open_neo4j_driver

    class GraphDatabase:
        @staticmethod
        def driver(uri, auth):
            raise RuntimeError(f"connection rejected: {auth[1]}")

    module = types.ModuleType("neo4j")
    module.GraphDatabase = GraphDatabase
    monkeypatch.setitem(sys.modules, "neo4j", module)

    with pytest.raises(RuntimeError) as exc_info:
        _open_neo4j_driver(
            "bolt://db-user:test-password@db-host:7687",
            "db-user",
            "test-password",
        )

    assert "test-password" not in str(exc_info.value)


def test_format_credential_redacted_removes_uri_password():
    from openspec.scripts.cmdb_backfill_orphans import _format_credential_redacted

    redacted = _format_credential_redacted(
        "bolt://db-user:test-password@db-host:7687"
    )

    assert redacted == "bolt://db-user@db-host:7687"
    assert "test-password" not in redacted
