# backend/tests/test_writer_advisory_lock.py
"""
Tests for the cross-writer event advisory-lock helper.

Background
----------
Issue #322: when multiple poll collectors observe the same failure,
``backend/engines/snmp_worker.py``, ``backend/services/snmp_service.py``, and
``backend/polling/event_writer.py`` can each create a separate OPEN Event for
the same ``(ci_id, metric_id, event_type)`` triplet because the read-then-create
path in Neo4j is atomic inside one transaction but NOT across transactions.

Fix (see ``openspec/changes/fix-event-duplication-cross-writer/design.md``):
every writer MUST acquire a PostgreSQL transaction-scoped advisory lock
``pg_advisory_xact_lock(hashtext(:key))`` with
``key = "{ci_id}|{metric_id}|{event_type}"`` BEFORE running the Neo4j
OPTIONAL MATCH + head(collect) + FOREACH(CREATE) block.

This file owns the bottom-of-the-stack smoke test for the helper. The
real-Postgres concurrency proof (design §6 "Primary test") and the
per-writer integration tests land in later PRs.
"""

from __future__ import annotations

from unittest.mock import MagicMock


def _normalize_sql_for_lookup(sql_obj):
    """Return a plain string we can grep for ``pg_advisory_xact_lock`` and ``hashtext``.

    The helper under test calls ``pg_db.execute(text(...), {...})``. We accept
    either a ``sqlalchemy.sql.elements.TextClause`` or a raw string.
    """
    if hasattr(sql_obj, "text"):
        return sql_obj.text
    return str(sql_obj)


def test_acquire_event_triplet_lock_helper():
    """``acquire_event_triplet_lock`` issues ``pg_advisory_xact_lock(hashtext(:key))``.

    MagicMock-based smoke test per design §6 "Secondary test". The test does
    NOT prove that two real Postgres transactions block each other; that
    concurrency proof lands in a later PR's dedicated testcontainers test.
    """
    from backend.services.event_lock import acquire_event_triplet_lock

    pg_db = MagicMock()
    acquire_event_triplet_lock(pg_db, "ci-001", "icmp_latency_ms", "THRESHOLD_BREACH")

    expected_key = "ci-001|icmp_latency_ms|THRESHOLD_BREACH"

    pg_db.execute.assert_called_once()
    call = pg_db.execute.call_args
    args, kwargs = call.args, call.kwargs

    # SQL is the first positional arg.
    sql_obj = args[0] if args else kwargs.get("text")
    sql_text = _normalize_sql_for_lookup(sql_obj)
    assert "pg_advisory_xact_lock" in sql_text, (
        f"expected pg_advisory_xact_lock in SQL, got: {sql_text!r}"
    )
    assert "hashtext" in sql_text, (
        f"expected hashtext in SQL, got: {sql_text!r}"
    )

    # The key parameter must match the "ci|metric|type" format exactly.
    params = args[1] if len(args) > 1 else kwargs.get("params") or kwargs
    # ``text("… :key")`` plus a dict binding ``{"key": …}`` is the canonical
    # pattern; we accept both binding styles for forward-compat.
    flat_values = params.values() if isinstance(params, dict) else (params,)
    assert expected_key in flat_values, (
        f"expected key {expected_key!r} in bind params, got {params!r}"
    )