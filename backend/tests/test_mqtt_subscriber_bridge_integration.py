"""Subscriber integration tests for MQTT bridge invocation from raw persistence."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest
from services.mqtt.parsers.base import MetricReading, Reading


@pytest.mark.asyncio
async def test_persist_reading_invokes_bridge_without_breaking_raw_flow(monkeypatch) -> None:
    class _MetricRepo:
        def __init__(self) -> None:
            self.device_calls = []
            self.metric_calls = []

        def upsert_device(
            self, device_id: str, name: str, location_id: str | None = None, **kwargs
        ) -> dict[str, str]:
            self.device_calls.append((device_id, location_id, name))
            return {"id": device_id}

        def upsert_metric(
            self,
            *,
            metric_id: str,
            device_id: str,
            name: str,
            value: float,
            unit: str | None = None,
            ts=None,
            tags: dict[str, str] | None = None,
            **kwargs,
        ) -> None:
            self.metric_calls.append((metric_id, device_id, name, value, ts))

    metric_repo = _MetricRepo()
    bridge_calls: list[Reading] = []

    class _BridgeService:
        def process_reading(self, reading: Reading):
            bridge_calls.append(reading)
            return [{"outcome": "SKIPPED_UNMAPPED"}]

    module = importlib.import_module("services.mqtt.subscriber")
    monkeypatch.setattr(module, "get_device_metric_repo", lambda: metric_repo)
    monkeypatch.setattr(module, "get_mqtt_bridge_service", lambda **kwargs: _BridgeService())

    reading = Reading(
        device_id="rtu-1",
        location_id="loc-1",
        timestamp=datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC),
        metrics=(MetricReading(name="temperature", value=20.0, unit="C"),),
        source_topic="rtu/loc-1/rtu-1/telemetry",
        parser_name="bliiot",
    )

    await module._persist_reading(reading)

    assert metric_repo.device_calls == [("rtu-1", "loc-1", "rtu-1")]
    assert metric_repo.metric_calls == [
        (
            "rtu-1/temperature",
            "rtu-1",
            "temperature",
            20.0,
            datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC),
        ),
    ]
    assert len(bridge_calls) == 1


@pytest.mark.asyncio
async def test_bridge_failure_does_not_break_raw_persistence(monkeypatch) -> None:
    class _MetricRepo:
        def upsert_device(
            self, device_id: str, name: str, location_id: str | None = None, **kwargs
        ) -> dict[str, str]:
            return {"id": device_id}

        def upsert_metric(self, **kwargs):
            return None

    module = importlib.import_module("services.mqtt.subscriber")
    monkeypatch.setattr(module, "get_device_metric_repo", lambda: _MetricRepo())
    monkeypatch.setattr(
        module,
        "get_mqtt_bridge_service",
        lambda **kwargs: type(
            "Bridge",
            (),
            {
                "process_reading": staticmethod(
                    lambda _r: (_ for _ in ()).throw(RuntimeError("bridge unavailable"))
                )
            },
        )(),
    )

    reading = Reading(
        device_id="rtu-1",
        location_id="loc-1",
        timestamp=datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC),
        metrics=(MetricReading(name="temperature", value=20.0, unit="C"),),
        source_topic="rtu/loc-1/rtu-1/telemetry",
        parser_name="bliiot",
    )

    # No exception should escape _persist_reading when the bridge fails.
    await module._persist_reading(reading)


@pytest.mark.asyncio
async def test_persist_reading_builds_bridge_with_lock_factory_when_available(monkeypatch) -> None:
    class _MetricRepo:
        def upsert_device(
            self, device_id: str, name: str, location_id: str | None = None, **kwargs
        ) -> dict[str, str]:
            return {"id": device_id}

        def upsert_metric(self, **kwargs):
            return None

    captured: dict[str, object] = {}

    class _BridgeService:
        def process_reading(self, _reading: Reading) -> list[dict[str, str]]:
            return [{"outcome": "SKIPPED_UNMAPPED"}]

    instance = _BridgeService()

    def _bridge_factory(**kwargs: object) -> _BridgeService:
        captured["kwargs"] = kwargs
        return instance

    module = importlib.import_module("services.mqtt.subscriber")
    monkeypatch.setattr(module, "get_device_metric_repo", lambda: _MetricRepo())
    monkeypatch.setattr(module, "get_mqtt_bridge_service", _bridge_factory)

    reading = Reading(
        device_id="rtu-1",
        location_id="loc-1",
        timestamp=datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC),
        metrics=(MetricReading(name="temperature", value=20.0, unit="C"),),
        source_topic="rtu/loc-1/rtu-1/telemetry",
        parser_name="bliiot",
    )

    await module._persist_reading(reading)

    assert captured["kwargs"]["event_writer_lock_db"] is module.SessionLocal
