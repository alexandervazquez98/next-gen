# backend/tests/test_writer_advisory_lock.py
"""
Tests for the cross-writer event advisory-lock helper and its real-Postgres
concurrency semantics.

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

This file owns the two bottom-of-the-stack tests:

* ``test_acquire_event_triplet_lock_helper`` — MagicMock smoke test verifying
  the helper calls ``pg_advisory_xact_lock(hashtext(:key))`` with the correct
  key format. (Design §6 "Secondary test".)
* ``test_concurrent_writers_block_on_lock`` — real Postgres concurrency proof
  using ``testcontainers[postgres]`` and ``concurrent.futures``. This is the
  ONLY test that actually proves lock semantics block concurrent writers.
  (Design §6 "Primary test".)

Per-writer integration tests against ``snmp_worker.py`` /
``snmp_service.py`` / ``polling/event_writer.py`` land in PR2.
"""

from __future__ import annotations

import concurrent.futures
import sys
import threading
import time
from unittest.mock import MagicMock

import pytest


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


def test_get_poll_collector_id_returns_non_empty_string():
    """#322 / spec §Poll collector identity persistence — helper returns a
    non-empty hostname string sourced from ``HOSTNAME`` env var with
    ``socket.gethostname()`` fallback. Cached at module load so per-row
    Event writes don't trigger repeated system calls.
    """
    import os
    import socket

    from backend.services.event_lock import get_poll_collector_id

    value = get_poll_collector_id()
    assert isinstance(value, str)
    assert value.strip(), f"poll_collector_id must be non-empty; got {value!r}"

    # The value MUST match the HOSTNAME env var OR socket.gethostname()
    # — whichever is non-empty (HOSTNAME takes precedence per design §4).
    expected = (os.getenv("HOSTNAME") or socket.gethostname()).strip()
    assert value == expected, (
        f"poll_collector_id must match HOSTNAME-or-gethostname; "
        f"got {value!r}, expected {expected!r}"
    )


def test_get_poll_collector_id_is_cached_at_module_load(monkeypatch):
    """Hostname MUST be read once at module load (design §4 / task 7).
    Subsequent calls return the SAME object even if socket.gethostname()
    is patched to return something different — proves the cache.
    """
    import socket

    from backend.services import event_lock as event_lock_module

    # Reset the cache to force re-evaluation against the patched hostname.
    monkeypatch.setattr(event_lock_module, "_CACHED_HOSTNAME", None)
    monkeypatch.setattr(socket, "gethostname", lambda: "sentinel-host")
    monkeypatch.delenv("HOSTNAME", raising=False)

    first = event_lock_module.get_poll_collector_id()
    assert first == "sentinel-host", f"first call should use the patched hostname; got {first!r}"

    # Mutate the source — second call MUST still return the cached value.
    monkeypatch.setattr(socket, "gethostname", lambda: "different-host")
    second = event_lock_module.get_poll_collector_id()
    assert second == "sentinel-host", (
        f"second call MUST return cached value (got {second!r}); "
        f"hostname was not cached at module load"
    )


def test_get_poll_collector_id_raises_when_hostname_unavailable(monkeypatch):
    """If both HOSTNAME env var AND socket.gethostname() are empty,
    ``get_poll_collector_id`` MUST raise ``RuntimeError`` rather than
    silently writing an empty string to the database.
    """
    import socket

    from backend.services import event_lock as event_lock_module

    monkeypatch.setattr(event_lock_module, "_CACHED_HOSTNAME", None)
    monkeypatch.setenv("HOSTNAME", "")
    monkeypatch.setattr(socket, "gethostname", lambda: "")

    with pytest.raises(RuntimeError, match="Cannot determine poll_collector_id"):
        event_lock_module.get_poll_collector_id()


# ---------------------------------------------------------------------------
# Task 2 — primary real-Postgres concurrency proof (design §6 "Primary test").
# PR1 ships this in PASSING state because the test exercises the lock
# primitive INDEPENDENTLY of any writer code — that proves the chosen
# primitive (``pg_advisory_xact_lock(hashtext(...))``) actually blocks.
# Per-writer integration tests are PR2's scope.
# ---------------------------------------------------------------------------


def _swap_in_real_psycopg2():
    """Pop the conftest's ``psycopg2`` MagicMock stub and return the real driver.

    The project's ``backend/tests/conftest.py`` installs a ``psycopg2`` MagicMock
    in ``sys.modules`` so service modules can be imported without a live DB.
    This test needs the real driver to talk to the testcontainers Postgres;
    we swap, run, then restore so downstream tests still see the stub.

    IMPORTANT: ``pytest.importorskip`` would just return the MagicMock because
    it's already in ``sys.modules``. We MUST pop first, then import fresh.
    """
    saved = sys.modules.pop("psycopg2", None)
    saved_ext = sys.modules.pop("psycopg2.extensions", None)
    import psycopg2 as real_psycopg2  # fresh import — now genuinely real
    sys.modules["psycopg2"] = real_psycopg2
    sys.modules["psycopg2.extensions"] = real_psycopg2.extensions

    def restore() -> None:
        if saved is not None:
            sys.modules["psycopg2"] = saved
        else:
            sys.modules.pop("psycopg2", None)
        if saved_ext is not None:
            sys.modules["psycopg2.extensions"] = saved_ext
        else:
            sys.modules.pop("psycopg2.extensions", None)

    return real_psycopg2, restore


@pytest.mark.integration
def test_concurrent_writers_block_on_lock():
    """Two real Postgres writers for the same triplet MUST serialize.

    Design §6 "Primary test". Spins up a real ``postgres:15-alpine`` container
    via ``testcontainers[postgres]``; two threads each open a real
    ``psycopg2`` connection and acquire ``pg_advisory_xact_lock`` for the same
    ``(ci, metric, event_type)`` triplet.

    Coordination pattern (deterministic, no race on thread startup):

    1. The "holder" thread acquires the lock and signals ``got_lock``.
    2. The "waiter" thread is started; it MUST block because the holder holds
       the lock. We assert the waiter is still blocked after 1 second.
    3. The holder is released; the waiter MUST then acquire the lock
       promptly.

    The assertion that matters: the waiter's wall-clock duration from
    ``pg_advisory_xact_lock`` call to lock acquisition is approximately
    the holder's hold duration (≥ the time between holder.got_lock and
    holder_release).

    Container startup cost: ~2-3 seconds. Acceptable for the only test that
    proves blocking semantics in real Postgres.
    """
    psycopg2, restore_psycopg2 = _swap_in_real_psycopg2()
    try:
        # Imported lazily so the swap above is in effect.
        from testcontainers.postgres import PostgresContainer

        with PostgresContainer("postgres:15-alpine") as pg:
            conn_url = pg.get_connection_url().replace(
                "postgresql+psycopg2://", "postgresql://"
            )
            triplet_key = "ci-001|icmp_latency_ms|THRESHOLD_BREACH"
            hold_seconds = 3.0  # >> check timeout; proves waiter is provably blocked during the check
            check_window = 0.5  # how long main waits before declaring "waiter is blocked"

            got_lock = threading.Event()
            release = threading.Event()
            waiter_finished = threading.Event()
            waiter_result: dict = {}

            def holder() -> None:
                conn = psycopg2.connect(conn_url)
                try:
                    conn.autocommit = False
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (triplet_key,),
                    )
                    got_lock.set()
                    release.wait(timeout=15)
                    conn.commit()
                    cur.close()
                finally:
                    conn.close()

            def waiter() -> None:
                conn = psycopg2.connect(conn_url)
                try:
                    conn.autocommit = False
                    cur = conn.cursor()
                    t_try = time.monotonic()
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (triplet_key,),
                    )
                    t_acquired = time.monotonic()
                    waiter_result["blocked_for"] = t_acquired - t_try
                    conn.commit()
                    cur.close()
                finally:
                    conn.close()
                    waiter_finished.set()

            holder_thread = threading.Thread(target=holder, name="holder")
            holder_thread.start()
            assert got_lock.wait(timeout=10), "holder never acquired the lock"

            waiter_thread = threading.Thread(target=waiter, name="waiter")
            waiter_thread.start()

            # If the lock is honored, the waiter must still be blocked here.
            # Check window (0.5s) is much smaller than hold_seconds (3.0s) so a
            # passing assertion here is genuine proof of blocking.
            assert not waiter_finished.wait(timeout=0.5), (
                "waiter acquired the lock while holder still held it — "
                "pg_advisory_xact_lock is NOT serializing writers!"
            )

            # Release the holder; the waiter should now acquire promptly.
            release.set()
            holder_thread.join(timeout=15)

            assert waiter_finished.wait(timeout=10), (
                "waiter never acquired the lock after release"
            )
            waiter_thread.join(timeout=10)

            # The waiter MUST have been blocked for at least the check window.
            # Why? The holder is set to release AFTER main waits `check_window`
            # seconds proving the waiter is still blocked. So the waiter's
            # blocked_for ≥ check_window (minus tiny slack for thread
            # scheduling). If it returned in microseconds, the lock did NOT
            # block it.
            blocked_for = waiter_result["blocked_for"]
            assert blocked_for >= check_window - 0.2, (
                f"waiter blocked for only {blocked_for:.3f}s (expected ≥ "
                f"{check_window - 0.2:.3f}s) — lock did not serialize"
            )
    finally:
        restore_psycopg2()