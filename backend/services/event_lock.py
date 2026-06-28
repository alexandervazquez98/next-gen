# backend/services/event_lock.py
"""
Shared advisory-lock helpers for cross-writer event coordination.

Background
----------
Issue #322: when multiple poll collectors (see ``backend/engines/snmp_worker.py``,
``backend/services/snmp_service.py``, ``backend/polling/event_writer.py``)
observe the same failure concurrently, each can create a separate OPEN
Neo4j Event for the same ``(ci_id, metric_id, event_type)`` triplet because
the read-then-create path is atomic inside one Neo4j transaction but NOT
across transactions.

Fix (see ``openspec/changes/fix-event-duplication-cross-writer/``):
every writer MUST acquire a PostgreSQL transaction-scoped advisory lock
on the triplet BEFORE running the Neo4j OPTIONAL MATCH + head(collect) +
FOREACH(CREATE) block. PostgreSQL serializes writers for the same triplet
and releases the lock on transaction end (commit, rollback, or session close).

This module exposes the single helper all three writers call. Keep it tiny —
no session management, no Neo4j concerns, just one well-named primitive.
"""

from __future__ import annotations

from sqlalchemy import text


def acquire_event_triplet_lock(pg_db, ci_id: str, metric_id: str, event_type: str) -> None:
    """Acquire a transaction-scoped PostgreSQL advisory lock for one triplet.

    The lock key is ``"{ci_id}|{metric_id}|{event_type}"``; ``hashtext`` collapses
    it to a 32-bit integer that ``pg_advisory_xact_lock`` accepts.

    The lock is held until ``pg_db``'s transaction commits, rolls back, or the
    session closes. Concurrent calls for the same triplet block until the
    holder's transaction ends; concurrent calls for different triplets run
    in parallel.

    Parameters
    ----------
    pg_db:
        An open SQLAlchemy ``Session`` (or any object exposing
        ``.execute(statement, params)``). MUST stay open for the duration of
        the Neo4j Event write that follows.
    ci_id, metric_id, event_type:
        The triplet identifying the Event being created/updated.
    """
    key = f"{ci_id}|{metric_id}|{event_type}"
    pg_db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": key},
    )