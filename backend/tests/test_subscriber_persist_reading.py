"""Unit tests for ``_persist_reading`` (PR3b cutover to DeviceMetricRepo).

Replaces the PR2b stub. Verifies that:

  * ``_persist_reading`` calls ``repo.upsert_device`` exactly once per Reading.
  * It calls ``repo.upsert_metric`` exactly once per :class:`MetricReading`.
  * ``extra`` larger than 4 KB (Q2) is replaced with a truncation marker and a
    warning is logged.
  * Any driver-level exception is wrapped in :class:`RuntimeError` so the
    caller (``_dispatch``) can NACK uniformly per design §2.6.

The repo methods are SYNC (matching ``topology_repo`` / ``rtu_sensor_repo`` —
see ``repositories/device_metric_repo.py`` docstring), even though
``_persist_reading`` is itself ``async def``. This is intentional: the function
is async only so the existing ``await _persist_reading(reading)`` call site in
``_dispatch`` does not need to change.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from services.mqtt.parsers.base import MetricReading, Reading

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_reading(
    device_id: str = "rtu-1",
    location_id: str | None = "loc-1",
    metrics: tuple[MetricReading, ...] = (),
    extra: dict | None = None,
    parser_name: str = "bliiot_s475e",
    source_topic: str = "rtu/loc-1/rtu-1/telemetry",
) -> Reading:
    """Build a minimal Reading for unit testing ``_persist_reading``."""
    return Reading(
        device_id=device_id,
        location_id=location_id,
        timestamp=datetime(2026, 6, 23, 12, 0, 0, tzinfo=UTC),
        metrics=metrics,
        source_topic=source_topic,
        parser_name=parser_name,
        extra=extra if extra is not None else {},
    )


@pytest.fixture(autouse=True)
def _reset_device_metric_repo_singleton():
    """Reset DeviceMetricRepo singleton between tests for isolation."""
    from repositories import device_metric_repo as mod

    mod._device_metric_repo = None
    yield
    mod._device_metric_repo = None


# ── _persist_reading happy path ──────────────────────────────────────────────


class TestPersistReadingCreatesDeviceAndMetrics:
    """``_persist_reading`` calls repo.upsert_device once and upsert_metric per metric."""

    async def test_persist_reading_creates_device_and_metrics(self):
        """Two-metric Reading → 1 upsert_device + 2 upsert_metric calls.

        Verifies that the new path (PR3b) replaces the PR2b BLIIoT-stub path.
        The mock repo's ``set_device_metric_repo`` injection must be honored.
        """
        from repositories import device_metric_repo as repo_mod
        from services.mqtt.subscriber import _persist_reading

        mock_repo = MagicMock()
        repo_mod.set_device_metric_repo(mock_repo)

        metrics = (
            MetricReading(
                name="register_0", value=2375, unit="0.01°C", tags={"register_addr": "0"}
            ),
            MetricReading(name="register_2", value=5500, unit="mV", tags={"register_addr": "2"}),
        )
        reading = _make_reading(metrics=metrics)

        await _persist_reading(reading)

        # 1 upsert_device call
        mock_repo.upsert_device.assert_called_once()
        # 1 upsert_metric call per metric (2)
        assert mock_repo.upsert_metric.call_count == 2

        # Device call args
        dev_kwargs = mock_repo.upsert_device.call_args.kwargs
        assert dev_kwargs["device_id"] == "rtu-1"
        assert dev_kwargs["location_id"] == "loc-1"
        assert dev_kwargs["source_topic"] == "rtu/loc-1/rtu-1/telemetry"
        assert dev_kwargs["parser_name"] == "bliiot_s475e"
        # extra is passed as a dict (the repo serializes to JSON internally)
        assert isinstance(dev_kwargs["extra"], dict)

        # First metric call args
        m0_kwargs = mock_repo.upsert_metric.call_args_list[0].kwargs
        assert m0_kwargs["device_id"] == "rtu-1"
        assert m0_kwargs["metric_id"] == "rtu-1/register_0"
        assert m0_kwargs["name"] == "register_0"
        assert m0_kwargs["value"] == 2375
        assert m0_kwargs["unit"] == "0.01°C"
        assert m0_kwargs["tags"] == {"register_addr": "0"}

        # Second metric call args
        m1_kwargs = mock_repo.upsert_metric.call_args_list[1].kwargs
        assert m1_kwargs["metric_id"] == "rtu-1/register_2"
        assert m1_kwargs["value"] == 5500

    async def test_persist_reading_with_zero_metrics(self):
        """Reading with no metrics → 1 upsert_device + 0 upsert_metric calls.

        Edge case: a parser may emit a Reading with an empty metrics tuple
        (e.g., a heartbeat message). Device must still be upserted so the
        last_seen field is updated.
        """
        from repositories import device_metric_repo as repo_mod
        from services.mqtt.subscriber import _persist_reading

        mock_repo = MagicMock()
        repo_mod.set_device_metric_repo(mock_repo)

        reading = _make_reading(metrics=())

        await _persist_reading(reading)

        mock_repo.upsert_device.assert_called_once()
        mock_repo.upsert_metric.assert_not_called()


# ── 4 KB extra cap (Q2) ─────────────────────────────────────────────────────


class TestPersistReadingExtraCap:
    """``Reading.extra`` > 4 KB is replaced with a truncation marker (Q2 decision)."""

    async def test_persist_reading_truncates_extra_above_4kb(self, caplog):
        from repositories import device_metric_repo as repo_mod
        from services.mqtt.subscriber import _persist_reading

        mock_repo = MagicMock()
        repo_mod.set_device_metric_repo(mock_repo)

        # 5000-byte string serializes to ~5100 bytes JSON — well over 4096.
        big_blob = "x" * 5000
        reading = _make_reading(extra={"blob": big_blob})

        with caplog.at_level(logging.WARNING, logger="services.mqtt.subscriber"):
            await _persist_reading(reading)

        # The upsert_device call received a truncation marker
        dev_kwargs = mock_repo.upsert_device.call_args.kwargs
        sent_extra = dev_kwargs["extra"]
        assert sent_extra.get("_truncated") is True
        assert isinstance(sent_extra.get("_original_size"), int)
        assert sent_extra["_original_size"] > 4096

        # A warning was logged with the size and device_id
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("truncated" in r.getMessage().lower() for r in warnings)
        assert any("rtu-1" in r.getMessage() for r in warnings)

    async def test_persist_reading_keeps_small_extra(self):
        """Reading with extra <= 4 KB is passed through unchanged."""
        from repositories import device_metric_repo as repo_mod
        from services.mqtt.subscriber import _persist_reading

        mock_repo = MagicMock()
        repo_mod.set_device_metric_repo(mock_repo)

        small_extra = {"digital_inputs": [1, 0, 1], "relays": [0, 1]}
        reading = _make_reading(extra=small_extra)

        await _persist_reading(reading)

        dev_kwargs = mock_repo.upsert_device.call_args.kwargs
        # Same dict (not truncated)
        assert dev_kwargs["extra"] == small_extra


# ── Exception propagation ───────────────────────────────────────────────────


class TestPersistReadingExceptionPropagation:
    """Driver exceptions are wrapped in RuntimeError so _dispatch can NACK."""

    async def test_persist_reading_propagates_neo4j_exception(self):
        from repositories import device_metric_repo as repo_mod
        from services.mqtt.subscriber import _persist_reading

        mock_repo = MagicMock()
        mock_repo.upsert_device.side_effect = Exception("Neo4j unreachable")
        repo_mod.set_device_metric_repo(mock_repo)

        reading = _make_reading(metrics=(MetricReading(name="register_0", value=1),))

        with pytest.raises(RuntimeError, match="rtu-1"):
            await _persist_reading(reading)

        # No metric upserts happened — failure happened on device upsert
        mock_repo.upsert_metric.assert_not_called()

    async def test_persist_reading_wraps_metric_exception(self):
        """Failure on upsert_metric (after upsert_device succeeded) also wraps in RuntimeError."""
        from repositories import device_metric_repo as repo_mod
        from services.mqtt.subscriber import _persist_reading

        mock_repo = MagicMock()
        mock_repo.upsert_metric.side_effect = Exception("metric write failed")
        repo_mod.set_device_metric_repo(mock_repo)

        reading = _make_reading(metrics=(MetricReading(name="register_0", value=1),))

        with pytest.raises(RuntimeError, match="rtu-1/register_0"):
            await _persist_reading(reading)
