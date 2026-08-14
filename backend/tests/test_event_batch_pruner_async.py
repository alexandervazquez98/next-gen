"""Async non-blocking proof for event_batch_pruner.

This test is the RED pin of ``fix-sse-pruner-streaming-blocking``. It installs
a driver whose SYNC ``__enter__`` blocks the event loop for 5 seconds with
``time.sleep`` (mimicking the original bug), then drives the generator
inside an ``asyncio.wait_for(..., timeout=1.0)`` deadline.

Behaviour:
  * Against the current SYNC production code the body enters the SYNC
    ``with driver.session() as session:``, the SYNC ``__enter__`` calls
    ``time.sleep(5)``, the asyncio thread is fully blocked for the
    duration of the sleep (the timer for ``wait_for`` cannot preempt
    ``time.sleep`` on CPython). Once the sleep returns the body issues
    ``session.run(...).single()`` against an ``async def run`` (which the
    mock advertises) and Python raises ``AttributeError`` on
    ``coroutine.single``. Either way, the deadline is missed — the test
    fails with a non-empty ``>1s`` runtime and a clean error pointing at
    the sync ``with`` / sync ``.run`` antipattern.
  * After the ``AsyncSession`` refactor the body uses
    ``async with driver.session() as session:`` (calls ``__aenter__``,
    no sleep) and ``await session.run(...)`` (the async mock honours
    ``await``). The first chunk is yielded inside the deadline and the
    test passes.

The TDD contract is: this test fails against the current sync code and
passes against the refactor. Whether the failure surfaces as
``asyncio.TimeoutError`` or ``AttributeError`` is an implementation
detail of the asyncio timer + ``time.sleep`` interaction; what matters is
that the body must not block the event loop.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import time
import types
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stubs — must match conftest.py pattern so event_service imports cleanly
# ---------------------------------------------------------------------------

for mod in ["neo4j", "neo4j.exceptions", "psycopg2", "psycopg2.extensions"]:
    sys.modules[mod] = MagicMock()


def _load_event_service_module():
    """Reload event_service with stub snmp_service (same pattern as conftest)."""
    sys.modules.pop("services.event_service", None)
    sys.modules.pop("services.snmp_service", None)
    stub = types.ModuleType("services.snmp_service")
    stub.run_diagnostic = lambda ci, metric: "diagnostic-ok"
    sys.modules["services.snmp_service"] = stub
    return importlib.import_module("services.event_service")


@pytest.fixture(autouse=True)
def restore_snmp_service_stub():
    previous = sys.modules.get("services.snmp_service", None)
    yield
    if previous is None:
        sys.modules.pop("services.snmp_service", None)
    else:
        sys.modules["services.snmp_service"] = previous


# ---------------------------------------------------------------------------
# Mock infrastructure — driver that BLOCKS if used synchronously
# ---------------------------------------------------------------------------


class _BlockingResult:
    """Async-iterable cursor.

    Production code that is properly async will ``await result.single()``
    or iterate via ``async for``. Both paths yield immediately here.
    """

    def __init__(self, total: int = 0):
        self._total = total

    async def single(self):
        await asyncio.sleep(0)  # cooperative yield
        return {"total": self._total}

    def __aiter__(self):
        return self._aiter_impl()

    async def _aiter_impl(self):
        if False:  # pragma: no cover — placeholder async generator
            yield {"event_id": "noop"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _BlockingSession:
    """Session mock whose SYNC ``__enter__`` blocks the event loop.

    Design contract (used by ``test_event_batch_pruner_first_chunk_does_not_block_event_loop``):

      * ``__enter__`` blocks for ``block_seconds`` to mimic a sync Neo4j
        call performed from an ``async def`` (the original bug).
      * ``__aenter__`` is fully non-blocking — production should use
        ``async with driver.session() as session:`` after the refactor.
      * ``run`` is ``async def`` — the proper way for refactored
        production to issue a query.

    When the existing sync production code calls ``session.run(...)``
    without ``await`` it gets a coroutine and then crashes with
    ``AttributeError: 'coroutine' object has no attribute 'single'``,
    which proves the sync body is broken.
    """

    def __init__(self, block_seconds: float = 5.0):
        self.queries: list[dict] = []
        self._block_seconds = block_seconds
        self._count_total = 0

    def set_total(self, total: int) -> None:
        self._count_total = total

    # SYNC context manager — blocks the loop if production code uses `with`
    def __enter__(self):
        if self._block_seconds > 0:
            time.sleep(self._block_seconds)
        return self

    def __exit__(self, *args):
        return False

    # ASYNC context manager — never blocks
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    # ASYNC run — proper API for refactored production
    async def run(self, query: str, **params):
        self.queries.append({"query": query, "params": params})
        # Cooperative yield so other tasks may run.
        await asyncio.sleep(0)
        if "return count(e) as total" in query.lower():
            return _BlockingResult(total=self._count_total)
        return _BlockingResult(total=0)


class _BlockingDriver:
    """Always returns the same blocking session instance (like MockDriver)."""

    _session: _BlockingSession | None = None
    block_seconds: float = 5.0
    count_total: int = 0

    def session(self):
        if _BlockingDriver._session is None:
            _BlockingDriver._session = _BlockingSession(block_seconds=_BlockingDriver.block_seconds)
            _BlockingDriver._session.set_total(_BlockingDriver.count_total)
        return _BlockingDriver._session


@pytest.fixture(autouse=True)
def reset_blocking_driver():
    _BlockingDriver._session = None
    _BlockingDriver.block_seconds = 5.0
    _BlockingDriver.count_total = 0
    yield
    _BlockingDriver._session = None


@pytest.fixture
def blocking_driver():
    _BlockingDriver.block_seconds = 5.0
    _BlockingDriver.count_total = 3
    return _BlockingDriver()


@pytest.fixture
def patched_event_service(blocking_driver):
    event_service = _load_event_service_module()
    original_get_db = event_service.get_db
    event_service.get_db = lambda: blocking_driver
    try:
        yield event_service
    finally:
        event_service.get_db = original_get_db


# ---------------------------------------------------------------------------
# Strict-TDD RED pin
# ---------------------------------------------------------------------------


def test_event_batch_pruner_first_chunk_does_not_block_event_loop(patched_event_service):
    """The first chunk of ``event_batch_pruner`` MUST reach the consumer
    within a 1-second budget, proving the body never blocks the event loop
    on a synchronous Neo4j call.

    Against the current sync code the body issues a sync
    ``with driver.session() as session:`` whose ``__enter__`` sleeps 5 s,
    so the deadline is missed and the test fails. After the
    ``AsyncSession`` refactor the body uses ``async with ...`` and the
    deadline is met.
    """
    agen = patched_event_service.event_batch_pruner(user="system", batch_delay_ms=0)

    async def _drive():
        try:
            return await asyncio.wait_for(agen.__anext__(), timeout=1.0)
        finally:
            await agen.aclose()

    first_chunk = asyncio.run(_drive())

    # Belt-and-suspenders shape verification so a green asyncio.TimeoutError
    # or AttributeError outcome is distinguishable from a "yielded wrong
    # shape" outcome.
    assert isinstance(first_chunk, dict)
    assert first_chunk.get("batch") == 0
    assert first_chunk.get("total") == 3
    assert first_chunk.get("processed") == 0
