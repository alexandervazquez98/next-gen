# backend/services/neo4j_write_guard.py
"""
Narrow fallback for ``session.run(...)`` calls rejected by Neo4j with
``Variable poll_collector_id not defined``.

Background
----------
Production rejects Event-write Cypher that references ``$poll_collector_id``
with ``Neo.ClientError.Statement.SyntaxError: Variable poll_collector_id
not defined`` (issue #340). The value is passed by Python, so the cause
is unresolved, but Event emission MUST NOT silently drop while RCA is
open. This module exposes a tiny wrapper that runs the primary query;
if Neo4j rejects it with the specific undefined-parameter
``ClientError``, logs ``ERROR cypher-param-fallback`` with the original
query + params + stack trace and runs a matching fallback query without
``poll_collector_id``. Any other error (including unrelated ``ClientError``s
and non-``ClientError`` exceptions) re-raises unchanged so unrelated
Cypher defects keep surfacing.

Design constraints
------------------
* The wrapper is intentionally NOT a decorator or context manager — every
  call site needs explicit primary / fallback query pairs because the
  fallback omits the ``poll_collector_id`` references in *that* primary
  query. A decorator would hide which fallback applies to which writer.
* The fallback query is built at the call site (string substitution),
  not here. This module knows nothing about which Cypher clauses use
  the parameter; it just runs whichever fallback it is given.
* The lock that serializes writers (``acquire_event_triplet_lock``)
  stays in scope: the fallback runs inside the same writer call as the
  primary, so it does not re-acquire a lock.

Logging contract
----------------
On fallback, we emit ``logger.exception(...)`` so the stack trace is
included alongside the message. The message includes the literal marker
``cypher-param-fallback`` so operators can grep
``docker logs <container> | grep cypher-param-fallback`` for incidents.
"""

from __future__ import annotations

import neo4j.exceptions


# Capture the exception class at module load so test code can reliably
# monkeypatch ``_CLIENT_ERROR_CLASS`` instead of fighting with the
# ``neo4j.exceptions.ClientError`` namespace (which is replaced by
# ``MagicMock`` stubs at module load time by the conftest and other
# test fixtures). Production code path uses the same captured reference.
_CLIENT_ERROR_CLASS = neo4j.exceptions.ClientError


def is_poll_collector_id_undefined_error(error: Exception) -> bool:
    """Return ``True`` iff ``error`` is the specific undefined-``poll_collector_id``
    ``ClientError`` that triggers the fallback path.

    The predicate is strict on three axes (design §8, verify-report
    CRITICAL #2):

    1. The exception MUST be a ``neo4j.exceptions.ClientError`` (not a
       ``ServerError``, ``DriverError``, or generic Python exception).
       The Neo4j Python driver wraps statement-syntax failures under
       ``ClientError``; the test is on the driver's exception class, not
       on Python's ``SyntaxError``.
    2. The error ``message`` attribute MUST contain the literal
       ``poll_collector_id``.
    3. The error ``message`` attribute MUST contain the literal
       ``not defined``.

    Note: the predicate reads ``error.message`` (the canonical rejection
    text exposed by the Neo4j Python driver), NOT ``str(error)``.
    ``str(error)`` is broader — the driver formats ``ClientError`` with
    extra context like the code prefix and bolt URL — and reading
    ``str(error)`` would accept unrelated ``ClientError`` whose formatted
    representation happens to mention the parameter. ``error.message`` is
    the authoritative rejection text the server returns.

    Returning ``True`` lets the caller enter the fallback path.
    """
    return (
        isinstance(error, _CLIENT_ERROR_CLASS)
        and "poll_collector_id" in error.message
        and "not defined" in error.message
    )


def run_with_cypher_param_fallback(
    session,
    primary_query: str,
    primary_params: dict,
    fallback_query: str,
    fallback_params: dict,
    error_filter,
    logger,
):
    """Run ``primary_query``; on a matching error, log and run ``fallback_query``.

    Parameters
    ----------
    session:
        A Neo4j session (or any object exposing ``.run(query, **params)``).
    primary_query, primary_params:
        The collector-attributed query and its params (typically includes
        ``poll_collector_id=POLL_COLLECTOR_ID``).
    fallback_query, fallback_params:
        The matching fallback with ``poll_collector_id`` references
        removed (both the ``poll_collector_id: $poll_collector_id``
        CREATE-row-dict form and the ``poll_collector_id = $poll_collector_id``
        SET-clause form) and the ``poll_collector_id`` param dropped.
    error_filter:
        Callable taking the exception and returning ``True`` when fallback
        should run. Defaults to ``is_poll_collector_id_undefined_error``
        but exposed for callers that want a narrower predicate.
    logger:
        Logger used for the ``ERROR cypher-param-fallback`` entry on
        fallback. ``logger.exception`` is used so the stack trace is
        captured.

    Returns
    -------
    Whatever ``session.run(...)`` returns — either the primary result
    (if it succeeded or failed with a non-matching error) or the
    fallback result (if it succeeded).

    Raises
    ------
    Whatever ``session.run(...)`` raises — including the original
    ``ClientError`` if the predicate does not match, and any exception
    the fallback query raises.
    """
    try:
        return session.run(primary_query, **primary_params)
    except Exception as exc:
        if not error_filter(exc):
            raise
        logger.exception(
            "cypher-param-fallback primary_query=%r primary_params=%r "
            "fallback_query=%r fallback_params=%r",
            primary_query, primary_params, fallback_query, fallback_params,
        )
        return session.run(fallback_query, **fallback_params)