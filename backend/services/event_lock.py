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

import os
import socket

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


# ---------------------------------------------------------------------------
# poll_collector_id — forensic attribution for #322 / spec §Poll collector
# identity persistence. Every Event CREATE / SET clause persists the
# hostname of the container that observed the failure so operators can
# correlate Events with the collector instance responsible. Cached at
# module load so per-row writes don't trigger repeated socket / env reads.
# ---------------------------------------------------------------------------

_CACHED_HOSTNAME: str | None = None


def get_poll_collector_id() -> str:
    """Return the hostname of the current container/pod for ``poll_collector_id``.

    Sources the value from the ``HOSTNAME`` env var (set automatically in
    Kubernetes / Docker / systemd-nspawn containers) with a fallback to
    ``socket.gethostname()`` for bare-metal deployments. The value is
    cached at module load — subsequent calls return the cached string.

    Raises
    ------
    RuntimeError
        If both the ``HOSTNAME`` env var and ``socket.gethostname()``
        return empty strings. We refuse to silently persist an empty
        ``poll_collector_id`` because that would defeat forensic
        correlation entirely.
    """
    global _CACHED_HOSTNAME
    if _CACHED_HOSTNAME is None:
        raw = (os.getenv("HOSTNAME") or "").strip() or socket.gethostname().strip()
        if not raw:
            raise RuntimeError(
                "Cannot determine poll_collector_id: HOSTNAME env var and "
                "socket.gethostname() are both empty"
            )
        _CACHED_HOSTNAME = raw
    return _CACHED_HOSTNAME


# Resolve once at import time so all three writers see the same constant
# without re-running the env / socket lookup on every Event CREATE.
POLL_COLLECTOR_ID = get_poll_collector_id()