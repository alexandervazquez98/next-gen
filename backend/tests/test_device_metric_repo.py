"""Unit tests for DeviceMetricRepo \u2014 generic Device+Metric persistence.

Uses the `mock_neo4j_driver` fixture (tests/conftest.py) which patches
`database.driver` so DeviceMetricRepo can use `get_db()` without a live Neo4j.

Cypher contracts under test (per design \u00a74):
- upsert_device: MERGE on Device.id, ON CREATE sets all fields, ON MATCH updates last_seen
- upsert_metric: MERGE on Metric.id, MERGE on (Device)-[:HAS_METRIC]->(Metric), updates last_value
- get_device: MATCH by id, return dict or None
- list_metrics: MATCH via HAS_METRIC, return list (empty if device unknown)
- extra is serialized as JSON string to avoid Neo4j property cardinality bloat
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_device_record(
    device_id: str = "dev-1",
    name: str = "Test Device",
    location_id: str | None = "loc-1",
    source_topic: str = "rtu/loc-1/dev-1/telemetry",
    parser_name: str = "bliiot_s475e",
    first_seen: str = "2026-06-23T10:00:00Z",
    last_seen: str = "2026-06-23T10:00:00Z",
    extra_json: str = "{}",
) -> dict:
    """Build a Device record dict in the shape returned by Neo4j."""
    return {
        "d": {
            "id": device_id,
            "name": name,
            "location_id": location_id,
            "source_topic": source_topic,
            "parser_name": parser_name,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "extra": extra_json,
        }
    }


def _make_metric_record(
    metric_id: str = "dev-1:temp",
    device_id: str = "dev-1",
    name: str = "temp",
    last_value: float = 23.5,
    unit: str | None = "C",
    last_ts: str = "2026-06-23T10:00:00Z",
    tags_json: str = "{}",
) -> dict:
    """Build a Metric record dict in the shape returned by Neo4j."""
    return {
        "m": {
            "id": metric_id,
            "device_id": device_id,
            "name": name,
            "last_value": last_value,
            "unit": unit,
            "last_ts": last_ts,
            "tags": tags_json,
        }
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(mock_neo4j_driver):
    """Return a DeviceMetricRepo bound to the mocked Neo4j driver."""
    from repositories.device_metric_repo import DeviceMetricRepo

    return DeviceMetricRepo(mock_neo4j_driver)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset module-level singleton between tests (defensive isolation)."""
    from repositories import device_metric_repo as mod

    mod._device_metric_repo = None
    yield
    mod._device_metric_repo = None


# ---------------------------------------------------------------------------
# upsert_device
# ---------------------------------------------------------------------------


class TestUpsertDevice:
    """DeviceMetricRepo.upsert_device \u2014 idempotent MERGE on Device.id."""

    def test_upsert_device_creates_node(self, repo, mock_neo4j_driver):
        """First call issues a MERGE on (d:Device {id: $device_id}) with all params."""
        record = _make_device_record()
        mock_neo4j_driver.mock_session.set_response(
            "merge (d:device",  # case-insensitive match in mock
            [record],
        )

        result = repo.upsert_device(
            device_id="dev-1",
            name="Test Device",
            location_id="loc-1",
            source_topic="rtu/loc-1/dev-1/telemetry",
            parser_name="bliiot_s475e",
            extra={"firmware": "1.2.3"},
        )

        # One query issued
        assert len(mock_neo4j_driver.mock_session.queries) == 1
        query = mock_neo4j_driver.mock_session.queries[0]["query"].lower()
        assert "merge" in query
        assert "device" in query
        params = mock_neo4j_driver.mock_session.queries[0]["params"]
        assert params["device_id"] == "dev-1"
        assert params["name"] == "Test Device"
        assert params["location_id"] == "loc-1"
        assert params["source_topic"] == "rtu/loc-1/dev-1/telemetry"
        assert params["parser_name"] == "bliiot_s475e"
        # extra was serialized to JSON string
        assert isinstance(params["extra_json"], str)
        assert json.loads(params["extra_json"]) == {"firmware": "1.2.3"}

        # Returned dict has all expected fields
        assert result["id"] == "dev-1"
        assert result["name"] == "Test Device"
        assert result["location_id"] == "loc-1"
        assert result["source_topic"] == "rtu/loc-1/dev-1/telemetry"
        assert result["parser_name"] == "bliiot_s475e"

    def test_upsert_device_idempotent_100x(self, repo, mock_neo4j_driver):
        """Calling upsert_device 100 times with the same id issues 100 MERGEs
        but conceptually produces a single Device node."""
        mock_neo4j_driver.mock_session.set_response(
            "merge (d:device",
            [_make_device_record()],
        )

        for _ in range(100):
            repo.upsert_device(
                device_id="dev-stable",
                name="Stable Device",
                location_id="loc-1",
                source_topic="rtu/loc-1/dev-stable/telemetry",
                parser_name="bliiot_s475e",
            )

        assert len(mock_neo4j_driver.mock_session.queries) == 100
        for q in mock_neo4j_driver.mock_session.queries:
            assert q["params"]["device_id"] == "dev-stable"

    def test_upsert_device_stores_extra_as_json(self, repo, mock_neo4j_driver):
        """extra dict is serialized to JSON string for Neo4j property safety."""
        mock_neo4j_driver.mock_session.set_response(
            "merge (d:device", [_make_device_record()]
        )

        repo.upsert_device(
            device_id="dev-1",
            name="d",
            location_id=None,
            source_topic="t",
            parser_name="p",
            extra={"key1": "v1", "nested": {"a": 1}},
        )

        params = mock_neo4j_driver.mock_session.queries[0]["params"]
        assert isinstance(params["extra_json"], str)
        assert json.loads(params["extra_json"]) == {"key1": "v1", "nested": {"a": 1}}

    def test_upsert_device_no_extra_stores_empty_json(self, repo, mock_neo4j_driver):
        """When extra is None, store the JSON literal '{}' (not None)."""
        mock_neo4j_driver.mock_session.set_response(
            "merge (d:device", [_make_device_record()]
        )

        repo.upsert_device(
            device_id="dev-1",
            name="d",
            location_id=None,
            source_topic="t",
            parser_name="p",
            extra=None,
        )

        params = mock_neo4j_driver.mock_session.queries[0]["params"]
        assert params["extra_json"] == "{}"

    def test_upsert_device_wraps_driver_exception(self, repo, mock_neo4j_driver):
        """A driver-level exception must be re-raised as RuntimeError with context."""
        from repositories.device_metric_repo import DeviceMetricRepo

        # Use a driver whose session.run raises immediately
        class FailingSession:
            def run(self, *args, **kwargs):
                raise ConnectionError("Neo4j unreachable")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class FailingDriver:
            def session(self):
                return FailingSession()

        failing_repo = DeviceMetricRepo(FailingDriver())  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="upsert_device"):
            failing_repo.upsert_device(
                device_id="dev-1",
                name="d",
                location_id=None,
                source_topic="t",
                parser_name="p",
            )


# ---------------------------------------------------------------------------
# upsert_metric
# ---------------------------------------------------------------------------


class TestUpsertMetric:
    """DeviceMetricRepo.upsert_metric \u2014 MERGE Metric + HAS_METRIC relationship."""

    def test_upsert_metric_creates_node(self, repo, mock_neo4j_driver):
        """First call issues MERGE on Metric + HAS_METRIC MERGE."""
        record = _make_metric_record()
        mock_neo4j_driver.mock_session.set_response(
            "has_metric",
            [record],
        )

        result = repo.upsert_metric(
            metric_id="dev-1:temp",
            device_id="dev-1",
            name="temp",
            value=23.5,
            unit="C",
            ts=datetime(2026, 6, 23, 10, 0, 0, tzinfo=timezone.utc),
            tags={"register_addr": "100"},
        )

        query = mock_neo4j_driver.mock_session.queries[0]["query"].lower()
        assert "merge" in query
        assert "metric" in query
        assert "has_metric" in query
        params = mock_neo4j_driver.mock_session.queries[0]["params"]
        assert params["metric_id"] == "dev-1:temp"
        assert params["device_id"] == "dev-1"
        assert params["name"] == "temp"
        assert params["value"] == 23.5
        assert params["unit"] == "C"
        assert isinstance(params["tags_json"], str)
        assert json.loads(params["tags_json"]) == {"register_addr": "100"}

        assert result["id"] == "dev-1:temp"
        assert result["name"] == "temp"
        assert result["last_value"] == 23.5
        assert result["unit"] == "C"

    def test_upsert_metric_updates_last_value(self, repo, mock_neo4j_driver):
        """Second call updates last_value and last_ts."""
        mock_neo4j_driver.mock_session.set_response(
            "has_metric",
            [
                _make_metric_record(
                    metric_id="dev-1:temp",
                    last_value=99.9,
                    last_ts="2026-06-23T11:00:00Z",
                )
            ],
        )

        result = repo.upsert_metric(
            metric_id="dev-1:temp",
            device_id="dev-1",
            name="temp",
            value=99.9,
            unit="C",
            ts=datetime(2026, 6, 23, 11, 0, 0, tzinfo=timezone.utc),
        )

        assert result["last_value"] == 99.9
        # One query issued (idempotent MERGE does the update)
        assert len(mock_neo4j_driver.mock_session.queries) == 1

    def test_upsert_metric_no_tags_stores_empty_json(self, repo, mock_neo4j_driver):
        """tags=None \u2192 '{}' (JSON), never NULL (Neo4j doesn't index NULL well)."""
        mock_neo4j_driver.mock_session.set_response(
            "has_metric", [_make_metric_record()]
        )

        repo.upsert_metric(
            metric_id="dev-1:temp",
            device_id="dev-1",
            name="temp",
            value=1.0,
            unit=None,
            ts=datetime(2026, 6, 23, 10, 0, 0, tzinfo=timezone.utc),
        )

        params = mock_neo4j_driver.mock_session.queries[0]["params"]
        assert params["tags_json"] == "{}"
        assert params["unit"] is None


# ---------------------------------------------------------------------------
# get_device
# ---------------------------------------------------------------------------


class TestGetDevice:
    """DeviceMetricRepo.get_device \u2014 fetch by id, None when unknown."""

    def test_get_device_returns_dict_when_found(self, repo, mock_neo4j_driver):
        mock_neo4j_driver.mock_session.set_response(
            "match (d:device",
            [_make_device_record(device_id="dev-42", name="Found Device")],
        )

        result = repo.get_device("dev-42")

        assert result is not None
        assert result["id"] == "dev-42"
        assert result["name"] == "Found Device"
        # Query used MATCH on Device by id
        query = mock_neo4j_driver.mock_session.queries[0]["query"].lower()
        assert "match" in query
        assert "device" in query
        assert mock_neo4j_driver.mock_session.queries[0]["params"]["device_id"] == "dev-42"

    def test_get_device_returns_none_for_unknown(self, repo, mock_neo4j_driver):
        """Empty result set \u2192 None (not an exception, not an empty dict)."""
        mock_neo4j_driver.mock_session.set_response("match (d:device", [])

        result = repo.get_device("dev-does-not-exist")

        assert result is None


# ---------------------------------------------------------------------------
# list_metrics
# ---------------------------------------------------------------------------


class TestListMetrics:
    """DeviceMetricRepo.list_metrics \u2014 metrics belonging to a Device."""

    def test_list_metrics_returns_metrics(self, repo, mock_neo4j_driver):
        mock_neo4j_driver.mock_session.set_response(
            "has_metric",
            [
                _make_metric_record(metric_id="dev-1:temp", name="temp", last_value=23.5),
                _make_metric_record(metric_id="dev-1:hum", name="hum", last_value=55.0),
            ],
        )

        result = repo.list_metrics("dev-1")

        assert len(result) == 2
        ids = {m["id"] for m in result}
        assert ids == {"dev-1:temp", "dev-1:hum"}
        # Query used MATCH via HAS_METRIC
        query = mock_neo4j_driver.mock_session.queries[0]["query"].lower()
        assert "match" in query
        assert "device" in query
        assert "metric" in query
        assert "has_metric" in query

    def test_list_metrics_returns_empty_for_unknown(self, repo, mock_neo4j_driver):
        """Unknown device \u2192 empty list (not an exception)."""
        mock_neo4j_driver.mock_session.set_response("has_metric", [])

        result = repo.list_metrics("dev-unknown")

        assert result == []

    def test_same_metric_name_on_two_devices_yields_distinct_metrics(
        self, repo, mock_neo4j_driver
    ):
        """Metric 'temp' on device A is distinct from Metric 'temp' on device B.

        The repo must pass ``device_id`` as a Cypher parameter so the composite
        identity is ``(device_id, name)`` — not just ``name``. We can't rely on
        the mock filtering by params, so we set different responses per call and
        verify both the returned rows AND the params match the requested device.
        """
        # First call: mock returns only dev-A's metric
        mock_neo4j_driver.mock_session.set_response(
            "has_metric",
            [_make_metric_record(metric_id="dev-A:temp", device_id="dev-A", name="temp")],
        )
        result_a = repo.list_metrics("dev-A")

        # Replace response so the second call returns only dev-B's metric
        mock_neo4j_driver.mock_session.set_response(
            "has_metric",
            [_make_metric_record(metric_id="dev-B:temp", device_id="dev-B", name="temp")],
        )
        result_b = repo.list_metrics("dev-B")

        assert [m["id"] for m in result_a] == ["dev-A:temp"]
        assert [m["id"] for m in result_b] == ["dev-B:temp"]

        # Both queries included the correct device_id param (Cypher filters)
        queries = mock_neo4j_driver.mock_session.queries
        assert queries[0]["params"]["device_id"] == "dev-A"
        assert queries[1]["params"]["device_id"] == "dev-B"


# ---------------------------------------------------------------------------
# Module-level singleton — added in Task 3a.3
# ---------------------------------------------------------------------------


class TestDeviceMetricRepoSingleton:
    """get_device_metric_repo() \u2014 lazy, cached, overridable for tests."""

    def test_singleton_returns_same_instance(self):
        """get_device_metric_repo() returns the SAME instance on repeated calls."""
        from repositories import device_metric_repo as mod

        # Override with a stub so we don't depend on database.get_db()
        sentinel = object()
        mod.set_device_metric_repo(sentinel)  # type: ignore[arg-type]

        first = mod.get_device_metric_repo()
        second = mod.get_device_metric_repo()

        assert first is second
        assert first is sentinel

    def test_singleton_overridable_for_tests(self):
        """set_device_metric_repo(mock) makes the next get_device_metric_repo() return mock."""
        from repositories import device_metric_repo as mod

        sentinel_a = object()
        sentinel_b = object()

        mod.set_device_metric_repo(sentinel_a)  # type: ignore[arg-type]
        assert mod.get_device_metric_repo() is sentinel_a

        mod.set_device_metric_repo(sentinel_b)  # type: ignore[arg-type]
        assert mod.get_device_metric_repo() is sentinel_b

        # set_device_metric_repo(None) clears the cache; the next get will
        # rebuild the repo from database.get_db() \u2014 it MUST NOT return
        # the previous sentinel.
        mod.set_device_metric_repo(None)
        fresh = mod.get_device_metric_repo()
        assert fresh is not sentinel_a
        assert fresh is not sentinel_b
        # And the cached value persists (singleton semantics)
        assert mod.get_device_metric_repo() is fresh

    def test_singleton_is_lazy_until_first_call(self):
        """Until get_device_metric_repo() is called, the module global is None.

        This guarantees that importing the module has no side effects on
        database connection state.
        """
        from repositories import device_metric_repo as mod

        mod.set_device_metric_repo(None)
        assert mod._device_metric_repo is None