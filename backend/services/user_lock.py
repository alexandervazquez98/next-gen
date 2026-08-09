# backend/services/user_lock.py
"""Per-user PostgreSQL advisory lock helpers (PR 3 — WU3).

Cross-store serialization for ticket assignment vs. user deactivation.
The lock is transaction-scoped (``pg_advisory_xact_lock``) so it is released
automatically on commit, rollback, or session close — no manual cleanup.

Lock key derivation
-------------------
``pg_advisory_xact_lock`` accepts a single 32-bit integer. We feed it
``hashtext('user:' || lower(username))`` so the lock key is normalized to
case-insensitive form and isolated from any other advisory-lock namespace
already used in the project (e.g. event triplet locks).

The caller MUST hold an open PostgreSQL session/transaction for the entire
Neo4j write that follows; the lock is released only when the session
transaction ends.

Lock ordering
-------------
For batch paths (PR 4 import), callers MUST acquire per-user locks in
``sorted(set(lower(u) for u in usernames))`` order to prevent deadlock
cycles. ``acquire_user_locks_in_order`` enforces this contract.
"""

from __future__ import annotations

from sqlalchemy import text


def _normalize(username: str) -> str:
    return (username or "").strip().lower()


def _is_blank(username: str | None) -> bool:
    return not (username and str(username).strip())


def acquire_user_lock(pg_db, username: str) -> None:
    """Acquire a transaction-scoped per-user PostgreSQL advisory lock.

    Parameters
    ----------
    pg_db:
        Open SQLAlchemy ``Session`` (or any object exposing
        ``.execute(statement, params)``). MUST stay open for the duration
        of the Neo4j write that follows.
    username:
        The assignee username. Normalized via ``lower().strip()`` so
        ``Op1`` and ``op1`` share the same lock.
    """
    if _is_blank(username):
        raise ValueError("acquire_user_lock requires a non-empty username")

    pg_db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"user:{_normalize(username)}"},
    )


def acquire_user_locks_in_order(pg_db, usernames) -> list[str]:
    """Acquire per-user locks for every distinct normalized username, in order.

    Returns the canonical (first-seen case) usernames in the order the locks
    were acquired. Blank/None inputs are skipped without raising.
    """
    if not usernames:
        return []

    seen: set[str] = set()
    normalized: list[str] = []
    for raw in usernames:
        if _is_blank(raw):
            continue
        key = _normalize(raw)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(key)

    normalized.sort()
    for username in normalized:
        acquire_user_lock(pg_db, username)
    return normalized
