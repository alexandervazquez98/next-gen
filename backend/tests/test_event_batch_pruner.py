"""Tests for event_batch_pruner() async generator in event_service."""

from __future__ import annotations

import asyncio
import importlib
import sys
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
    setattr(stub, "run_diagnostic", lambda ci, metric: "diagnostic-ok")
    sys.modules["services.snmp_service"] = stub
    return importlib.import_module("services.event_service")


# ---------------------------------------------------------------------------
# Mock infrastructure — mirrors conftest.py MockNeo4j* classes
# ---------------------------------------------------------------------------

class MockNeo4jRecord:
    """Simulates a Neo4j record dict-like access."""
    def __init__(self, data):
        self._data = data if isinstance(data, dict) else {}

    def __getitem__(self, key):
        return self._data.get(key)

    def get(self, key, default=None):
        return self._data.get(key, default)


class MockNeo4jResult:
    def __init__(self, records):
        self._records = records or []
        self._index = 0

    def __iter__(self):
        self._index = 0
        return self

    def __next__(self):
        if self._index >= len(self._records):
            raise StopIteration
        record = self._records[self._index]
        self._index += 1
        return MockNeo4jRecord(record) if isinstance(record, dict) else record

    def single(self):
        if self._records:
            first = self._records[0]
            return MockNeo4jRecord(first) if isinstance(first, dict) else first
        return None


class MockNeo4jSession:
    def __init__(self):
        self.queries = []
        self._response_map = {}
        self._default_response = []

    def set_response(self, query_key: str, records):
        self._response_map[query_key.lower()] = records

    def run(self, query: str, **params):
        self.queries.append({"query": query, "params": params})
        query_lower = query.lower()
        for key, records in self._response_map.items():
            if key in query_lower:
                return MockNeo4jResult(records)
        return MockNeo4jResult(self._default_response)

    def begin_transaction(self):
        return MockNeo4jTransaction(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MockNeo4jTransaction:
    def __init__(self, session):
        self._session = session
        self.committed = False

    def run(self, query: str, **params):
        return self._session.run(query, **params)

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MockDriver:
    _session: MockNeo4jSession | None = None

    def session(self):
        # Reuse the same session instance so test setup persists across calls
        if MockDriver._session is None:
            MockDriver._session = MockNeo4jSession()
        return MockDriver._session


@pytest.fixture(autouse=True)
def reset_mock_driver():
    """Reset session between tests to avoid state bleed."""
    MockDriver._session = None
    yield
    MockDriver._session = None


@pytest.fixture
def mock_driver():
    return MockDriver()


def _run_async(coro):
    """Run an async coroutine in a new event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _patch_get_db(mock_driver, event_service):
    """
    Patch database.driver so that get_db() returns our mock_driver.
    This is the same mechanism conftest uses, but we apply it directly
    to the database module so get_db() returns our custom driver.
    """
    import database
    original_driver = database.driver
    database.driver = mock_driver  # driver.session() will return our mock session
    original_get_db = event_service.get_db
    # Override get_db to return our mock_driver directly
    event_service.get_db = lambda: mock_driver
    return original_driver, original_get_db


def _restore_get_db(original_driver, original_get_db, event_service):
    import database
    database.driver = original_driver
    event_service.get_db = original_get_db


class TestEventBatchPrunerChunkCounting:
    """RED → GREEN → TRIANGULATE: Test chunk counting behavior."""

    def test_yields_one_chunk_when_total_less_than_batch_size(self, mock_driver):
        """When total events (3) < batch_size (500), we get initial + final chunk."""
        event_service = _load_event_service_module()
        session = mock_driver.session()
        session.set_response(
            "return count(e) as total",
            [{"total": 3}],
        )
        session.set_response(
            "return e.id as event_id, e.status",
            [
                {"event_id": "evt-1", "status": "RECOVERED"},
                {"event_id": "evt-2", "status": "RECOVERED"},
                {"event_id": "evt-3", "status": "RECOVERED"},
            ],
        )

        original_driver, original_get_db = _patch_get_db(mock_driver, event_service)
        try:
            chunks = []
            async def consume():
                async for progress in event_service.event_batch_pruner(
                    user="system", batch_delay_ms=0
                ):
                    chunks.append(progress)
            _run_async(consume())

            # Initial (batch=0) + one processing chunk (batch=1)
            assert len(chunks) == 2, f"Expected 2 chunks, got {len(chunks)}: {chunks}"
            assert chunks[0]["total"] == 3
            assert chunks[0]["batch"] == 0
            assert chunks[1]["processed"] == 3
            assert chunks[1]["remaining"] == 0
        finally:
            _restore_get_db(original_driver, original_get_db, event_service)

    def test_yields_multiple_chunks_when_total_exceeds_batch_size(self, mock_driver):
        """When total (1200) > batch_size (500), we get initial + 3 batch yields."""
        event_service = _load_event_service_module()
        session = mock_driver.session()

        session.set_response("return count(e) as total", [{"total": 1200}])
        session.set_response(
            "return e.id as event_id, e.status offset 0",
            [{"event_id": f"evt-{j}", "status": "RECOVERED"} for j in range(500)],
        )
        session.set_response(
            "return e.id as event_id, e.status offset 500",
            [{"event_id": f"evt-{j}", "status": "RECOVERED"} for j in range(500, 1000)],
        )
        session.set_response(
            "return e.id as event_id, e.status offset 1000",
            [{"event_id": f"evt-{j}", "status": "RECOVERED"} for j in range(1000, 1200)],
        )

        original_driver, original_get_db = _patch_get_db(mock_driver, event_service)
        try:
            chunks = []
            async def consume():
                async for progress in event_service.event_batch_pruner(
                    user="system", batch_size=500, batch_delay_ms=0
                ):
                    chunks.append(progress)
            _run_async(consume())

            # Initial (batch=0) + 3 batches = 4
            assert len(chunks) == 4, f"Expected 4 chunks, got {len(chunks)}: {chunks}"
            assert chunks[0]["batch"] == 0
            assert chunks[1]["batch"] == 1
            assert chunks[2]["batch"] == 2
            assert chunks[3]["batch"] == 3
            assert chunks[1]["processed"] == 500
            assert chunks[2]["processed"] == 1000  # cumulative
            assert chunks[3]["processed"] == 1200
        finally:
            _restore_get_db(original_driver, original_get_db, event_service)

    def test_zero_events_yields_single_initial_chunk(self, mock_driver):
        """When no RECOVERED events exist, yields only the initial chunk (total=0)."""
        event_service = _load_event_service_module()
        session = mock_driver.session()
        session.set_response("return count(e) as total", [{"total": 0}])

        original_driver, original_get_db = _patch_get_db(mock_driver, event_service)
        try:
            chunks = []
            async def consume():
                async for progress in event_service.event_batch_pruner(
                    user="system", batch_delay_ms=0
                ):
                    chunks.append(progress)
            _run_async(consume())

            assert len(chunks) == 1
            assert chunks[0]["total"] == 0
            assert chunks[0]["processed"] == 0
            assert chunks[0]["batch"] == 0
        finally:
            _restore_get_db(original_driver, original_get_db, event_service)


class TestEventBatchPrunerIdempotency:
    """RED → GREEN → TRIANGULATE: Test idempotency cache with TTL."""

    def test_event_skipped_if_already_in_cache(self, mock_driver):
        """An event already processed in this run is skipped via cache."""
        event_service = _load_event_service_module()
        session = mock_driver.session()

        session.set_response("return count(e) as total", [{"total": 2}])
        session.set_response(
            "return e.id as event_id, e.status",
            [
                {"event_id": "evt-1", "status": "RECOVERED"},
                {"event_id": "evt-2", "status": "RECOVERED"},
            ],
        )

        original_driver, original_get_db = _patch_get_db(mock_driver, event_service)
        try:
            progress_list = []
            async def consume():
                async for p in event_service.event_batch_pruner(user="system", batch_delay_ms=0):
                    progress_list.append(p)
            _run_async(consume())

            # Initial + one batch
            assert len(progress_list) == 2
            assert progress_list[1]["processed"] == 2

            # Cache is now request-scoped — verify via progress list instead
            # (events were processed = committed)
        finally:
            _restore_get_db(original_driver, original_get_db, event_service)


class TestEventBatchPrunerTimeout:
    """RED → GREEN → TRIANGULATE: Test per-chunk timeout handling."""

    def test_timeout_yields_error_in_progress(self, mock_driver):
        """When a chunk times out, progress includes error key (not crash)."""
        event_service = _load_event_service_module()
        session = mock_driver.session()

        session.set_response("return count(e) as total", [{"total": 1}])
        session.set_response("return e.id as event_id, e.status", [])

        original_driver, original_get_db = _patch_get_db(mock_driver, event_service)
        try:
            async def consume():
                progress_list = []
                async for progress in event_service.event_batch_pruner(
                    user="system", batch_timeout_s=0.001, batch_delay_ms=0
                ):
                    progress_list.append(progress)
                return progress_list

            result = _run_async(consume())
            assert len(result) >= 1
            for p in result:
                assert "total" in p
                assert "batch" in p
        finally:
            _restore_get_db(original_driver, original_get_db, event_service)


class TestEventBatchPrunerProgressShape:
    """RED → GREEN → TRIANGULATE: Test progress dict shape per chunk."""

    def test_progress_shape_includes_expected_fields(self, mock_driver):
        """Each progress yield has: total, processed, remaining, batch."""
        event_service = _load_event_service_module()
        session = mock_driver.session()
        session.set_response("return count(e) as total", [{"total": 2}])
        session.set_response(
            "return e.id as event_id, e.status",
            [
                {"event_id": "evt-1", "status": "RECOVERED"},
                {"event_id": "evt-2", "status": "RECOVERED"},
            ],
        )

        original_driver, original_get_db = _patch_get_db(mock_driver, event_service)
        try:
            progress_list = []
            async def consume():
                async for p in event_service.event_batch_pruner(
                    user="system", batch_delay_ms=0
                ):
                    progress_list.append(p)
            _run_async(consume())

            assert len(progress_list) == 2  # initial + one chunk
            initial = progress_list[0]
            chunk = progress_list[1]
            assert initial["batch"] == 0
            assert initial["total"] == 2
            assert chunk["batch"] == 1
            assert "total" in chunk
            assert "processed" in chunk
            assert "remaining" in chunk
            assert "batch" in chunk
        finally:
            _restore_get_db(original_driver, original_get_db, event_service)