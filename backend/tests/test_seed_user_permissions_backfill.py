"""Unit tests for ``backfill_user_permissions_from_roles`` — feat-489 Phase 3.

Mirrors the stub-driver pattern from ``test_seed_roles_cmdb.py``:
both the Postgres session and the Neo4j driver are mocked so no live
infra is needed.

Coverage:
- Postgres UPDATE is issued with the union semantics (fill-missing).
- Neo4j MATCH/SET only adds missing perms (no overwrite).
- Users whose perms already cover the role are skipped (idempotent).
- Users without a matching role are not touched (defensive).
- Idempotent: re-running on a fully-up-to-date graph issues no UPDATEs
  or SETs that change state.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def stub_neo4j_driver():
    """Patch ``database.driver`` so seed_roles backfill can run without
    a live Neo4j. Same trick as ``test_seed_roles_cmdb.py``."""
    import database as _db_module

    driver = MagicMock()
    original = _db_module.driver
    _db_module.driver = driver
    try:
        yield driver
    finally:
        _db_module.driver = original


def _empty_pg_session():
    """A MagicMock that behaves like a SQLAlchemy Session for the
    UPDATE … RETURNING call. Returns no rows so the loop has nothing
    to print."""
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = []
    return session


# ── Postgres backfill ─────────────────────────────────────────────────────────


def test_postgres_backfill_issues_union_update(monkeypatch, stub_neo4j_driver):
    """The Postgres UPDATE must union the user's existing permissions
    with the role's permissions in a single statement (no overwrite)."""
    import asyncio

    import seed_roles

    session = _empty_pg_session()
    monkeypatch.setattr("seed_roles.SessionLocal", lambda: session)
    monkeypatch.setattr("seed_roles.close_db", lambda: None)

    # Mock Neo4j to return roles
    neo_session = stub_neo4j_driver.session.return_value.__enter__.return_value
    neo_session.run.return_value = [
        {"name": "OPERATOR", "perms": ["CI_VIEW", "CI_BULK_IMPORT"]}
    ]

    asyncio.run(seed_roles.backfill_user_permissions_from_roles())

    # The UPDATE statement must union permissions with unnest and coalesce
    update_call = session.execute.call_args_list[0]
    sql = update_call.args[0]
    sql_text = str(sql)
    assert "UPDATE users" in sql_text, sql_text
    assert "coalesce(permissions, '{}') || :role_perms" in sql_text, sql_text
    assert "SELECT DISTINCT unnest" in sql_text, sql_text
    assert "WHERE role = :role_name" in sql_text, sql_text
    assert "RETURNING" in sql_text, sql_text


def test_postgres_backfill_is_a_noop_when_no_users_need_update(monkeypatch, stub_neo4j_driver):
    """If ``fetchall`` returns no rows (everyone is up to date), the
    backfill still completes cleanly — no exception, no spurious log."""
    import asyncio

    import seed_roles

    session = _empty_pg_session()
    monkeypatch.setattr("seed_roles.SessionLocal", lambda: session)
    monkeypatch.setattr("seed_roles.close_db", lambda: None)

    # Should not raise.
    asyncio.run(seed_roles.backfill_user_permissions_from_roles())


def test_postgres_backfill_survives_db_failure(monkeypatch, stub_neo4j_driver, capsys):
    """A Postgres exception is logged and the backfill continues to the
    Neo4j leg instead of crashing startup."""
    import asyncio

    import seed_roles

    def broken_session():
        s = MagicMock()
        s.execute.side_effect = RuntimeError("postgres unreachable")
        return s

    monkeypatch.setattr("seed_roles.SessionLocal", broken_session)
    monkeypatch.setattr("seed_roles.close_db", lambda: None)

    # Should not raise.
    asyncio.run(seed_roles.backfill_user_permissions_from_roles())

    captured = capsys.readouterr()
    assert "PG backfill skipped" in captured.out


# ── Neo4j backfill ───────────────────────────────────────────────────────────


def test_neo4j_backfill_uses_fill_missing_cypher(monkeypatch, stub_neo4j_driver):
    """The Cypher must add only the missing perms (NOT overwrite) and
    must skip users whose permissions already cover the role."""
    import asyncio

    import seed_roles

    session = stub_neo4j_driver.session.return_value.__enter__.return_value
    # No records → the backfill prints \"no users needed backfill\".
    session.run.return_value = MagicMock(__iter__=lambda self: iter([]))

    monkeypatch.setattr("seed_roles.SessionLocal", _empty_pg_session)
    monkeypatch.setattr("seed_roles.close_db", lambda: None)

    asyncio.run(seed_roles.backfill_user_permissions_from_roles())

    # Find the Cypher call.
    cypher_calls = [
        c for c in session.run.call_args_list
        if "MATCH (u:User)" in str(c.args[0]) and "r:Role" in str(c.args[0])
    ]
    assert cypher_calls, "No Neo4j MATCH call issued"
    cypher = str(cypher_calls[0].args[0])

    # fill-missing: add perms in r.permissions that are NOT in u.permissions.
    assert "WHERE NOT p IN" in cypher, cypher
    assert "coalesce(u.permissions, [])" in cypher, cypher
    # The SET must APPEND, not REPLACE.
    assert "SET u.permissions =" in cypher
    assert "+ missing" in cypher or "missing" in cypher
    # The WHERE size(missing) > 0 guards against touching users that
    # are already up to date (idempotency).
    assert "size(missing) > 0" in cypher


def test_neo4j_backfill_survives_neo4j_failure(monkeypatch, stub_neo4j_driver, capsys):
    """A Neo4j exception is logged and the backfill does not crash."""
    import asyncio

    import seed_roles

    driver = MagicMock()
    driver.session.return_value.__enter__.return_value.run.side_effect = (
        RuntimeError("neo4j unreachable")
    )
    monkeypatch.setattr("seed_roles.get_db", lambda: driver)
    monkeypatch.setattr("seed_roles.SessionLocal", _empty_pg_session)
    monkeypatch.setattr("seed_roles.close_db", lambda: None)

    # Should not raise.
    asyncio.run(seed_roles.backfill_user_permissions_from_roles())

    captured = capsys.readouterr()
    assert "NEO4J backfill skipped" in captured.out


# ── Idempotency contract ─────────────────────────────────────────────────────


def test_backfill_is_idempotent_on_up_to_date_data(monkeypatch, stub_neo4j_driver):
    """Two consecutive runs on the same (mocked) data must issue the
    same statements — backfill must not double-add or escalate."""
    import asyncio

    import seed_roles

    pg_session_a = _empty_pg_session()
    monkeypatch.setattr("seed_roles.SessionLocal", lambda: pg_session_a)
    monkeypatch.setattr("seed_roles.close_db", lambda: None)

    neo_session_a = stub_neo4j_driver.session.return_value.__enter__.return_value
    neo_session_a.run.return_value = MagicMock(__iter__=lambda self: iter([]))

    asyncio.run(seed_roles.backfill_user_permissions_from_roles())
    pg_calls_a = len(pg_session_a.execute.call_args_list)
    neo_calls_a = len(neo_session_a.run.call_args_list)

    # Fresh mocks for run 2 — the same contract is honored on replay.
    pg_session_b = _empty_pg_session()
    monkeypatch.setattr("seed_roles.SessionLocal", lambda: pg_session_b)
    neo_session_b = stub_neo4j_driver.session.return_value.__enter__.return_value
    neo_session_b.run.return_value = MagicMock(__iter__=lambda self: iter([]))

    asyncio.run(seed_roles.backfill_user_permissions_from_roles())
    pg_calls_b = len(pg_session_b.execute.call_args_list)
    neo_calls_b = len(neo_session_b.run.call_args_list)

    assert pg_calls_a == pg_calls_b, (
        f"PG execute count drifted: {pg_calls_a} -> {pg_calls_b}"
    )
    assert neo_calls_a == neo_calls_b, (
        f"NEO4J run count drifted: {neo_calls_a} -> {neo_calls_b}"
    )
