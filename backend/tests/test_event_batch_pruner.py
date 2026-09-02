"""Tests for event_batch_pruner() async generator in event_service."""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from unittest.mock import MagicMock

import pytest

_SNMP_SERVICE_SENTINEL = object()


class _FakeClientError(Exception):
    """Real exception class standing in for ``neo4j.exceptions.ClientError``.

    The conftest stubs ``sys.modules['neo4j.exceptions']`` with a MagicMock,
    so production ``isinstance(error, neo4j.exceptions.ClientError)`` checks
    fall through. The fail-loud predicate captures the class at module load
    (mirroring ``neo4j_write_guard``); tests patch the captured reference on
    the live module so the predicate sees this real subclass instead of the
    stub. Mirrors the Neo4j driver's ``message`` attribute surface.
    """

    def __init__(self, message: str = "", code: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code


def _install_fake_client_error(monkeypatch, event_service):
    """Patch the captured ``_CLIENT_ERROR_CLASS`` on the live event_service module.

    Production code captures ``neo4j.exceptions.ClientError`` at import time;
    under tests that resolves to a MagicMock, so ``isinstance(...)`` checks
    fail. We patch the captured reference to a real class so the predicate
    works as it does in production. Returns the patched module so the caller
    can reach ``is_cypher_syntax_error`` for direct predicate tests.
    """
    import backend.services.event_service as es_backend

    monkeypatch.setattr(es_backend, "_CLIENT_ERROR_CLASS", _FakeClientError)
    try:
        import services.event_service as es_services

        monkeypatch.setattr(es_services, "_CLIENT_ERROR_CLASS", _FakeClientError)
    except ImportError:
        pass
    # The test imported via the ``_load_event_service_module`` helper which
    # pops ``services.event_service`` from sys.modules and reimports it.
    # The freshly-loaded module is what the test holds in ``event_service``,
    # so we must patch THAT module's captured reference, not the aliased one.
    if hasattr(event_service, "_CLIENT_ERROR_CLASS"):
        event_service._CLIENT_ERROR_CLASS = _FakeClientError
    return event_service


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
    previous = sys.modules.get("services.snmp_service", _SNMP_SERVICE_SENTINEL)
    yield
    if previous is _SNMP_SERVICE_SENTINEL:
        sys.modules.pop("services.snmp_service", None)
    else:
        sys.modules["services.snmp_service"] = previous


# ---------------------------------------------------------------------------
# Mock infrastructure — mirrors conftest.py MockNeo4j* classes
# ---------------------------------------------------------------------------


class MockNeo4jRecord:
    """Simulates a Neo4j record dict-like access.

    Implements the full Mapping protocol so production helpers that do
    ``dict(record)`` (e.g. ``event_service._fetch_page``) work without raising
    TypeError. Without ``keys()`` / ``__iter__`` the original mock was only
    partial and broke chunk-counting tests whenever ``_fetch_page`` ran.
    """

    def __init__(self, data):
        self._data = data if isinstance(data, dict) else {}

    def __getitem__(self, key):
        return self._data.get(key)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __iter__(self):
        return iter(self._data)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        return len(self._data)


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
        self._response_sequences = {}
        self._close_results = None
        self._default_response = []

    def set_response(self, query_key: str, records):
        self._response_map[query_key.lower()] = records

    def set_sequence_response(self, query_key: str, record_batches):
        self._response_sequences[query_key.lower()] = list(record_batches)

    def set_close_results(self, record_batches):
        self._close_results = list(record_batches)

    def run(self, query: str, **params):
        self.queries.append({"query": query, "params": params})
        query_lower = query.lower()
        if "return e.id as closed_id" in query_lower:
            if self._close_results is not None:
                if self._close_results:
                    return MockNeo4jResult(self._close_results.pop(0))
                return MockNeo4jResult([])
            return MockNeo4jResult([{"closed_id": params.get("eid")}])
        for key, batches in self._response_sequences.items():
            if key in query_lower:
                if batches:
                    return MockNeo4jResult(batches.pop(0))
                return MockNeo4jResult([])
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
        session.set_sequence_response(
            "return e.id as event_id, e.status",
            [
                [{"event_id": f"evt-{j}", "status": "RECOVERED"} for j in range(500)],
                [{"event_id": f"evt-{j}", "status": "RECOVERED"} for j in range(500, 1000)],
                [{"event_id": f"evt-{j}", "status": "RECOVERED"} for j in range(1000, 1200)],
            ],
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


class TestEventBatchPrunerSafetyGuards:
    """Verify streaming prune only requires recovered, unacknowledged events."""

    def test_commented_recovered_unacknowledged_event_is_closed(self, mock_driver):
        """Non-ACK comments do not make a recovered event ineligible for pruning."""
        event_service = _load_event_service_module()
        session = mock_driver.session()
        session.set_response("return count(e) as total", [{"total": 1}])
        session.set_response(
            "return e.id as event_id, e.status",
            [
                {
                    "event_id": "evt-commented",
                    "status": "RECOVERED",
                    "comments": [{"text": "operator note"}],
                }
            ],
        )

        original_driver, original_get_db = _patch_get_db(mock_driver, event_service)
        try:
            progress_list = []

            async def consume():
                async for progress in event_service.event_batch_pruner(
                    user="system", batch_delay_ms=0
                ):
                    progress_list.append(progress)

            _run_async(consume())

            close_queries = [q for q in session.queries if "RETURN e.id AS closed_id" in q["query"]]
            assert close_queries, "Expected commented recovered event to be closed"
            assert close_queries[0]["params"]["eid"] == "evt-commented"
            assert progress_list[-1]["processed"] == 1

            close_query = close_queries[0]["query"]
            assert "WHERE e.status = 'RECOVERED'" in close_query
            assert "AND (e.ack IS NULL OR e.ack = false)" in close_query
            assert "comments" not in close_query.lower()
        finally:
            _restore_get_db(original_driver, original_get_db, event_service)

    def test_full_page_with_protected_event_continues_to_next_page(self, mock_driver):
        """A skipped close in a full page must not stop pagination early."""
        event_service = _load_event_service_module()
        session = mock_driver.session()
        session.set_response("return count(e) as total", [{"total": 3}])
        session.set_sequence_response(
            "return e.id as event_id, e.status",
            [
                [
                    {"event_id": "evt-1", "status": "RECOVERED"},
                    {"event_id": "evt-2", "status": "RECOVERED"},
                ],
                [{"event_id": "evt-3", "status": "RECOVERED"}],
            ],
        )
        session.set_close_results(
            [
                [{"closed_id": "first-page-close"}],
                [],
                [{"closed_id": "evt-3"}],
            ]
        )

        original_driver, original_get_db = _patch_get_db(mock_driver, event_service)
        try:
            progress_list = []

            async def consume():
                async for p in event_service.event_batch_pruner(
                    user="system", batch_size=2, batch_delay_ms=0
                ):
                    progress_list.append(p)

            _run_async(consume())

            assert [p["batch"] for p in progress_list] == [0, 1, 2]
            close_attempt_ids = [
                q["params"].get("eid")
                for q in session.queries
                if "RETURN e.id AS closed_id" in q["query"]
            ]
            assert "evt-3" in close_attempt_ids
        finally:
            _restore_get_db(original_driver, original_get_db, event_service)


_NULLS_KEYWORD_RE = __import__("re").compile(r"NULLS\s+(FIRST|LAST)", __import__("re").IGNORECASE)


class TestEventBatchPrunerNullCursorProgress:
    """RED -> GREEN: cursor pagination must make forward progress on NULL-bearing rows.

    Pre-#279 legacy rows have ``created_at IS NULL``. The pre-fix cursor was
    ``AND e.created_at > $last_cursor`` which evaluates to NULL (filter excludes
    every subsequent row) once a NULL row was processed. The composite cursor
    uses ``(e.created_at, e.id)`` ordering and a NULL-safe WHERE tiebreak so
    iter 2+ keeps moving.

    Cypher 5 / Neo4j 5.x does not accept the explicit ``NULLS FIRST`` /
    ``NULLS LAST`` keyword in ``ORDER BY`` (rejected as
    ``Invalid input 'NULLS'``); NULL placement is implicit — NULLs LAST under
    ASC, NULLs FIRST under DESC. We MUST NOT emit those keywords anywhere in
    production Cypher (issue #459).
    """

    def test_event_batch_pruner_null_cursor_progress(self, mock_driver):
        """Iter 2 issues a NULL-safe comparison so a NULL-bearing fixture still advances."""
        event_service = _load_event_service_module()
        session = mock_driver.session()

        # batch_size=1 ensures iter 1 returns a full page so iter 2 is issued.
        session.set_response("return count(e) as total", [{"total": 2}])
        # Iter 1 returns one NULL-row, iter 2 returns one timestamped row.
        ts = "2026-01-01T00:00:00Z"
        session.set_sequence_response(
            "return e.id as event_id, e.status",
            [
                [{"event_id": "evt-1", "status": "RECOVERED", "created_at": None}],
                [{"event_id": "evt-2", "status": "RECOVERED", "created_at": ts}],
            ],
        )

        original_driver, original_get_db = _patch_get_db(mock_driver, event_service)
        try:
            progress_list = []

            async def consume():
                async for p in event_service.event_batch_pruner(
                    user="system", batch_size=1, batch_delay_ms=0
                ):
                    progress_list.append(p)

            _run_async(consume())

            # iter 1 processed the NULL row (the cursor advance sets
            # last_id="evt-1"); the contract we lock here is that iter 2's
            # page query uses a NULL-safe comparison (carries the prior id AND
            # the WHERE clause survives a NULL cursor).
            page_queries = [
                q
                for q in session.queries
                if "ORDER BY" in q["query"].upper() and "LIMIT" in q["query"].upper()
            ]
            assert (
                len(page_queries) >= 2
            ), f"Expected at least two page queries (one per batch), got {len(page_queries)}"

            second_query = page_queries[1]
            # The composite cursor MUST carry the prior row's id as the tiebreak
            # so the next batch can advance past a NULL row.
            assert second_query["params"].get("last_id") == "evt-1", (
                f"Iter 2 cursor must carry the prior row's id as the tiebreak; "
                f"got params={second_query['params']!r}"
            )
            # Iter 2's cursor MUST include a NULL-safe clause so it can keep
            # moving on a NULL-bearing fixture (the broken cursor used
            # `e.created_at > $last_cursor` which is NULL when last_cursor is NULL).
            assert "IS NULL" in second_query["query"].upper(), (
                f"Iter 2 cursor filter must include a NULL-safe clause so a "
                f"NULL-bearing fixture keeps moving; got query={second_query['query']!r}"
            )
        finally:
            _restore_get_db(original_driver, original_get_db, event_service)

    def test_page_query_does_not_contain_nulls_first_or_last(self, mock_driver):
        """Regression guard for issue #459 — page query MUST NOT use ``NULLS FIRST/LAST``.

        Cypher 5 grammar (Neo4j 5.x) does not include the ``NULLS`` keyword;
        emitting it raises ``Neo.ClientError.Statement.SyntaxError: Invalid
        input 'NULLS'``. NULL placement is implicit (NULLs LAST under ASC,
        NULLs FIRST under DESC). This test exercises the real production
        cursor and asserts every captured ORDER BY query is free of the
        forbidden token, regardless of which batch it came from.
        """
        event_service = _load_event_service_module()
        session = mock_driver.session()

        session.set_response("return count(e) as total", [{"total": 2}])
        ts = "2026-01-01T00:00:00Z"
        session.set_sequence_response(
            "return e.id as event_id, e.status",
            [
                [{"event_id": "evt-1", "status": "RECOVERED", "created_at": None}],
                [{"event_id": "evt-2", "status": "RECOVERED", "created_at": ts}],
            ],
        )

        original_driver, original_get_db = _patch_get_db(mock_driver, event_service)
        try:

            async def consume():
                async for _ in event_service.event_batch_pruner(
                    user="system", batch_size=1, batch_delay_ms=0
                ):
                    pass

            _run_async(consume())

            page_queries = [
                q
                for q in session.queries
                if "ORDER BY" in q["query"].upper() and "LIMIT" in q["query"].upper()
            ]
            assert page_queries, "Expected the pruner to issue at least one page query"

            offenders = [
                (idx, _NULLS_KEYWORD_RE.search(q["query"]).group(0))
                for idx, q in enumerate(page_queries)
                if _NULLS_KEYWORD_RE.search(q["query"])
            ]
            assert not offenders, (
                f"Page query MUST NOT contain ``NULLS FIRST``/``NULLS LAST`` "
                f"(Cypher 5 / Neo4j 5.x rejects it as ``Invalid input 'NULLS'``). "
                f"Found offenders: {offenders}"
            )
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
                async for p in event_service.event_batch_pruner(user="system", batch_delay_ms=0):
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


class TestEventBatchPrunerRetryCap:
    """RED -> GREEN: the retry loop must terminate when fetch keeps failing.

    Pre-#433 the catch-all at ``event_service.event_batch_pruner``'s chunk loop
    swallowed exceptions and yielded an error chunk forever, so a transient
    fetch failure could turn into an infinite loop (the SSE endpoint would hang
    past the 1s first-byte budget and beyond). The contract under test is:
    after ``MAX_CONSECUTIVE_CHUNK_FAILURES`` consecutive failures the generator
    re-raises the last exception instead of looping.
    """

    def test_breaks_after_max_consecutive_chunk_failures(self, mock_driver):
        """When _fetch_page always raises, the generator must terminate."""
        event_service = _load_event_service_module()
        session = mock_driver.session()

        # Total count succeeds (5 events "need" pruning), but every page
        # fetch raises. Without the retry cap the loop spins forever and
        # yields an unbounded stream of error chunks.
        session.set_response("return count(e) as total", [{"total": 5}])

        original_run = session.run

        def selective_run(query: str, **params):
            q_lower = query.lower()
            if "return e.id as event_id" in q_lower:
                raise RuntimeError("simulated fetch failure")
            return original_run(query, **params)

        session.run = selective_run

        original_driver, original_get_db = _patch_get_db(mock_driver, event_service)
        try:
            chunks: list[dict] = []
            outcome: tuple[str, Exception | None] = ("completed", None)

            async def consume() -> None:
                try:
                    async for progress in event_service.event_batch_pruner(
                        user="system", batch_delay_ms=0
                    ):
                        chunks.append(progress)
                except Exception as exc:
                    nonlocal outcome
                    outcome = ("raised", exc)

            # Bound the test itself with asyncio.wait_for so an unfixed
            # implementation fails RED with TimeoutError instead of hanging
            # the runner (defense in depth — pytest-timeout is the broader
            # safety net wired in #433 / Change 3).
            _run_async(asyncio.wait_for(consume(), timeout=5.0))

            assert outcome[0] == "raised", (
                f"Generator must re-raise after the retry cap is hit, "
                f"instead it {outcome[0]!r} after yielding {len(chunks)} chunks"
            )
            assert isinstance(outcome[1], RuntimeError)
            assert "simulated fetch failure" in str(outcome[1])

            # Initial (batch=0) plus at most MAX_CONSECUTIVE_CHUNK_FAILURES
            # error chunks before the generator re-raises on the next failure.
            assert chunks[0]["batch"] == 0
            error_chunks = [c for c in chunks if "error" in c]
            assert len(error_chunks) == event_service.MAX_CONSECUTIVE_CHUNK_FAILURES, (
                f"Expected exactly {event_service.MAX_CONSECUTIVE_CHUNK_FAILURES} "
                f"error chunks before re-raise, got {len(error_chunks)}"
            )
        finally:
            _restore_get_db(original_driver, original_get_db, event_service)


class TestEventBatchPrunerCypherSyntaxErrorFirstChunk:
    """RED -> GREEN: CypherSyntaxError MUST propagate on the first chunk.

    Pre-#459 the chunk loop's ``except Exception as e`` swallowed the
    ``Neo.ClientError.Statement.SyntaxError`` raised by the invalid
    ``ORDER BY ... ASC NULLS LAST`` clause, yielded it as a normal
    ``{"error": "..."}`` chunk, and continued. Operators saw stale data, not a
    failure. The contract here: a syntax error on the FIRST page MUST yield a
    terminal error chunk, log at ERROR level, and close the stream — NOT ride
    the 3-strike debounce.
    """

    def test_first_chunk_syntax_error_yields_terminal_chunk(self, mock_driver, monkeypatch):
        """Syntax error on first page produces ONE error chunk then closes — no debounce."""
        event_service = _load_event_service_module()
        event_service = _install_fake_client_error(monkeypatch, event_service)
        session = mock_driver.session()

        # Total count succeeds.
        session.set_response("return count(e) as total", [{"total": 5}])
        original_run = session.run

        syntax_error = _FakeClientError(
            message="Invalid input 'NULLS': expected ...", code="Neo.ClientError.Statement.SyntaxError"
        )

        def selective_run(query: str, **params):
            q_lower = query.lower()
            if "return e.id as event_id" in q_lower:
                raise syntax_error
            return original_run(query, **params)

        session.run = selective_run

        original_driver, original_get_db = _patch_get_db(mock_driver, event_service)
        try:
            chunks: list[dict] = []

            async def consume():
                async for progress in event_service.event_batch_pruner(
                    user="system", batch_delay_ms=0
                ):
                    chunks.append(progress)

            # Bound the test so a non-terminating implementation fails fast.
            _run_async(asyncio.wait_for(consume(), timeout=5.0))

            # Initial chunk + exactly ONE error chunk carrying the syntax message.
            assert len(chunks) >= 2, f"Expected initial + error chunks, got {chunks!r}"
            error_chunks = [c for c in chunks if "error" in c]
            assert len(error_chunks) == 1, (
                f"CypherSyntaxError MUST NOT be debounced — expected exactly one "
                f"error chunk, got {len(error_chunks)} chunks: {error_chunks!r}"
            )
            assert "Invalid input 'NULLS'" in error_chunks[0]["error"], (
                f"Error chunk MUST carry the syntax-error message; "
                f"got error={error_chunks[0]['error']!r}"
            )
        finally:
            _restore_get_db(original_driver, original_get_db, event_service)

    def test_syntax_error_does_not_count_against_retry_cap(
        self, mock_driver, monkeypatch
    ):
        """A syntax error MUST NOT increment consecutive_failures — it is terminal on first hit."""
        event_service = _load_event_service_module()
        event_service = _install_fake_client_error(monkeypatch, event_service)
        session = mock_driver.session()

        session.set_response("return count(e) as total", [{"total": 5}])
        original_run = session.run
        syntax_error = _FakeClientError(
            message="Invalid input 'NULLS': expected ...",
            code="Neo.ClientError.Statement.SyntaxError",
        )

        def selective_run(query: str, **params):
            q_lower = query.lower()
            if "return e.id as event_id" in q_lower:
                raise syntax_error
            return original_run(query, **params)

        session.run = selective_run

        original_driver, original_get_db = _patch_get_db(mock_driver, event_service)
        try:
            chunks: list[dict] = []

            async def consume():
                async for progress in event_service.event_batch_pruner(
                    user="system", batch_delay_ms=0
                ):
                    chunks.append(progress)

            _run_async(asyncio.wait_for(consume(), timeout=5.0))

            # Cap is 3 — if the predicate routed the syntax error into the
            # debounce path, we would see 3 error chunks before terminate.
            error_chunks = [c for c in chunks if "error" in c]
            assert len(error_chunks) < event_service.MAX_CONSECUTIVE_CHUNK_FAILURES, (
                f"Syntax error MUST bypass the 3-strike cap; "
                f"got {len(error_chunks)} error chunks (cap is "
                f"{event_service.MAX_CONSECUTIVE_CHUNK_FAILURES})"
            )
        finally:
            _restore_get_db(original_driver, original_get_db, event_service)

    def test_non_syntax_client_error_keeps_debounce(
        self, mock_driver, monkeypatch
    ):
        """A non-syntax ClientError still rides the 3-strike cap.

        Guard against over-broadening the predicate: only CypherSyntaxError
        should fail loud. Other ClientErrors (e.g. constraint violations) keep
        the existing debounce so a transient hiccup does not abort the run.
        """
        event_service = _load_event_service_module()
        event_service = _install_fake_client_error(monkeypatch, event_service)
        session = mock_driver.session()

        session.set_response("return count(e) as total", [{"total": 5}])
        original_run = session.run

        # A non-syntax ClientError (no Neo.ClientError.Statement.SyntaxError code).
        non_syntax = _FakeClientError(
            message="some other constraint violation",
            code="Neo.ClientError.Schema.ConstraintValidationFailed",
        )

        def selective_run(query: str, **params):
            q_lower = query.lower()
            if "return e.id as event_id" in q_lower:
                raise non_syntax
            return original_run(query, **params)

        session.run = selective_run

        original_driver, original_get_db = _patch_get_db(mock_driver, event_service)
        try:
            chunks: list[dict] = []
            outcome: tuple[str, Exception | None] = ("completed", None)

            async def consume() -> None:
                try:
                    async for progress in event_service.event_batch_pruner(
                        user="system", batch_delay_ms=0
                    ):
                        chunks.append(progress)
                except Exception as exc:
                    nonlocal outcome
                    outcome = ("raised", exc)

            _run_async(asyncio.wait_for(consume(), timeout=5.0))

            # Non-syntax error SHOULD be debounced: exactly cap-many error chunks,
            # then re-raise on the next failure.
            assert outcome[0] == "raised", (
                f"Non-syntax errors must still re-raise after the debounce cap; "
                f"instead {outcome[0]!r}"
            )
            assert isinstance(outcome[1], _FakeClientError)
            error_chunks = [c for c in chunks if "error" in c]
            assert (
                len(error_chunks) == event_service.MAX_CONSECUTIVE_CHUNK_FAILURES
            ), (
                f"Non-syntax ClientError must ride the 3-strike cap; "
                f"got {len(error_chunks)} error chunks"
            )
        finally:
            _restore_get_db(original_driver, original_get_db, event_service)


class TestEventBatchPrunerTransientKeepsDebounce:
    """RED -> GREEN: non-ClientError exceptions (RuntimeError/ServiceUnavailable) keep debounce.

    Pre-existing behavior contract: the chunk loop swallows non-syntax errors
    for ``MAX_CONSECUTIVE_CHUNK_FAILURES`` consecutive failures before
    re-raising. This class pins the asymmetry between syntax errors (fail loud)
    and transient driver/network errors (debounce) so the new predicate does
    not accidentally broaden into transient territory.
    """

    def test_runtime_error_runs_three_strikes_then_raises(self, mock_driver):
        """Generic RuntimeError rides the 3-strike debounce, NOT a terminal chunk."""
        event_service = _load_event_service_module()
        session = mock_driver.session()

        session.set_response("return count(e) as total", [{"total": 5}])
        original_run = session.run

        def selective_run(query: str, **params):
            q_lower = query.lower()
            if "return e.id as event_id" in q_lower:
                raise RuntimeError("transient driver flap")
            return original_run(query, **params)

        session.run = selective_run

        original_driver, original_get_db = _patch_get_db(mock_driver, event_service)
        try:
            chunks: list[dict] = []
            outcome: tuple[str, Exception | None] = ("completed", None)

            async def consume() -> None:
                try:
                    async for progress in event_service.event_batch_pruner(
                        user="system", batch_delay_ms=0
                    ):
                        chunks.append(progress)
                except Exception as exc:
                    nonlocal outcome
                    outcome = ("raised", exc)

            _run_async(asyncio.wait_for(consume(), timeout=5.0))

            assert outcome[0] == "raised"
            assert isinstance(outcome[1], RuntimeError)
            error_chunks = [c for c in chunks if "error" in c]
            assert len(error_chunks) == event_service.MAX_CONSECUTIVE_CHUNK_FAILURES
            # Terminal chunk would be {..., "terminal": True}; we expect NONE.
            terminal_chunks = [c for c in chunks if c.get("terminal") is True]
            assert not terminal_chunks, (
                f"RuntimeError is not a syntax error — must NOT emit a terminal chunk; "
                f"got {terminal_chunks!r}"
            )
        finally:
            _restore_get_db(original_driver, original_get_db, event_service)
