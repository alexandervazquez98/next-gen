"""Unit tests for the MQTT subscriber loop (PR2b).

Covers:
  * :func:`_dispatch` — pure async function that routes one message through the
    parser registry, persists the result, and ACKs/NACKs accordingly.
  * :func:`mqtt_subscriber_loop` — smoke test: starts the loop in a background
    task with a mocked broker, cancels after a short delay, asserts
    ``CancelledError`` propagates.

The full loop is integration territory (requires a live broker). PR2b verifies
the dispatch contract here; the existing skipped test in
``test_rtu_integration.py`` covers the live-broker case end-to-end.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from services.mqtt.parsers.base import MetricReading, Reading

pytestmark = [pytest.mark.unit]


# ── Fixtures ────────────────────────────────────────────────────────────────


def _make_message(topic: str, payload: bytes) -> MagicMock:
    """Build a fake aiomqtt.Message with ack/nack AsyncMocks."""
    msg = MagicMock()
    msg.topic = topic
    msg.payload = payload
    msg.ack = AsyncMock()
    msg.nack = AsyncMock()
    return msg


def _make_reading(
    parser_name: str = "bliiot_s475e",
    topic: str = "rtu/loc-1/rtu-1/telemetry",
    metrics: tuple[MetricReading, ...] = (),
    extra: dict | None = None,
) -> Reading:
    """Build a minimal Reading for unit testing."""
    return Reading(
        device_id="rtu-1",
        location_id="loc-1",
        timestamp=datetime(2026, 6, 23, 12, 0, 0, tzinfo=UTC),
        metrics=metrics,
        source_topic=topic,
        parser_name=parser_name,
        extra=extra if extra is not None else {},
    )


def _make_router(parser: object | None) -> MagicMock:
    """Build a mock TopicRouter that returns ``parser`` from .resolve()."""
    router = MagicMock()
    router.resolve = MagicMock(return_value=parser)
    return router


# Autouse: clear parser registry between tests for isolation.
@pytest.fixture(autouse=True)
def _clear_parser_registry():
    from services.mqtt.parsers import _clear_registry, register
    from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser

    _clear_registry()
    register(BliiotS475EParser())
    yield
    _clear_registry()


# ── _dispatch ───────────────────────────────────────────────────────────────


class TestDispatchNoParser:
    """When no parser matches, the loop must ACK to drop the message."""

    async def test_no_parser_resolved_acks_and_drops(self):
        """router.resolve returns None → log error + ack + no parse call."""
        from services.mqtt.subscriber import _dispatch

        router = _make_router(None)
        message = _make_message("unknown/topic", b'{"foo": 1}')

        await _dispatch(message, router)

        message.ack.assert_awaited_once()
        message.nack.assert_not_called()
        router.resolve.assert_called_once_with("unknown/topic")


class TestDispatchSuccess:
    """Happy path: parser returns readings → persist → ACK."""

    async def test_parser_success_acks(self):
        """parser.parse succeeds → _persist_reading called → ack."""
        from services.mqtt.subscriber import _dispatch

        parser = MagicMock()
        parser.name = "bliiot_s475e"
        reading = _make_reading()
        parser.parse = MagicMock(return_value=[reading])

        router = _make_router(parser)
        message = _make_message("rtu/loc-1/rtu-1/telemetry", b'{"sensors": []}')

        with patch(
            "services.mqtt.subscriber._persist_reading",
            new=AsyncMock(),
        ) as persist:
            await _dispatch(message, router)

        parser.parse.assert_called_once_with("rtu/loc-1/rtu-1/telemetry", b'{"sensors": []}')
        persist.assert_awaited_once_with(reading)
        message.ack.assert_awaited_once()
        message.nack.assert_not_called()


class TestDispatchParseFailure:
    """ParseError → ACK (drop the message — payload is unrecoverable)."""

    async def test_parse_error_acks(self):
        """parser.parse raises ParseError → ack, no persist call."""
        from services.mqtt.parsers.base import ParseError
        from services.mqtt.subscriber import _dispatch

        parser = MagicMock()
        parser.name = "bliiot_s475e"
        parser.parse = MagicMock(side_effect=ParseError("malformed JSON"))

        router = _make_router(parser)
        message = _make_message("rtu/loc-1/rtu-1/telemetry", b"not json")

        with patch(
            "services.mqtt.subscriber._persist_reading",
            new=AsyncMock(),
        ) as persist:
            await _dispatch(message, router)

        persist.assert_not_called()
        message.ack.assert_awaited_once()
        message.nack.assert_not_called()


class TestDispatchParserBug:
    """Other parser exceptions → NACK (could be transient — redeliver)."""

    async def test_non_parse_error_nacks(self):
        """parser.parse raises generic Exception → nack, no persist call."""
        from services.mqtt.subscriber import _dispatch

        parser = MagicMock()
        parser.name = "bliiot_s475e"
        parser.parse = MagicMock(side_effect=RuntimeError("parser bug"))

        router = _make_router(parser)
        message = _make_message("rtu/loc-1/rtu-1/telemetry", b'{"sensors": []}')

        with patch(
            "services.mqtt.subscriber._persist_reading",
            new=AsyncMock(),
        ) as persist:
            await _dispatch(message, router)

        persist.assert_not_called()
        message.nack.assert_awaited_once()
        message.ack.assert_not_called()


class TestDispatchPersistFailure:
    """Persistence failure → NACK (broker redelivers)."""

    async def test_persist_failure_nacks(self):
        """_persist_reading raises → nack, ack not called."""
        from services.mqtt.subscriber import _dispatch

        parser = MagicMock()
        parser.name = "bliiot_s475e"
        reading = _make_reading()
        parser.parse = MagicMock(return_value=[reading])

        router = _make_router(parser)
        message = _make_message("rtu/loc-1/rtu-1/telemetry", b'{"sensors": []}')

        with patch(
            "services.mqtt.subscriber._persist_reading",
            new=AsyncMock(side_effect=ConnectionError("Neo4j down")),
        ):
            await _dispatch(message, router)

        message.nack.assert_awaited_once()
        message.ack.assert_not_called()


class TestDispatchBliiotPersist:
    """BLIIoT readings persist via DeviceMetricRepo (PR3b clean cutover, Q6)."""

    async def test_bliiot_parser_persists_via_device_metric_repo(self):
        """parser_name='bliiot_s475e' → _persist_reading calls device_metric_repo.

        Verifies the Q6 cutover: BLIIoT messages now persist ONLY to Device+Metric
        nodes. ``RTUService`` and ``process_telemetry_message`` are NOT called.
        """
        from repositories import device_metric_repo as repo_mod
        from services.mqtt.subscriber import _dispatch

        metric = MetricReading(
            name="register_0",
            value=2375,
            unit="0.01°C",
            tags={"register_addr": "0"},
        )
        reading = _make_reading(
            parser_name="bliiot_s475e",
            topic="rtu/loc-1/rtu-1/telemetry",
            metrics=(metric,),
        )
        parser = MagicMock()
        parser.name = "bliiot_s475e"
        parser.parse = MagicMock(return_value=[reading])

        router = _make_router(parser)
        message = _make_message(
            "rtu/loc-1/rtu-1/telemetry",
            json.dumps(
                {
                    "timestamp": "2026-06-23T12:00:00Z",
                    "sensors": [{"register_addr": 0, "value": 2375, "unit": "0.01°C"}],
                }
            ).encode("utf-8"),
        )

        # Inject a mock DeviceMetricRepo singleton
        mock_repo = MagicMock()
        repo_mod.set_device_metric_repo(mock_repo)

        try:
            await _dispatch(message, router)
        finally:
            repo_mod.set_device_metric_repo(None)

        # Device upsert called with correct identity/provenance
        mock_repo.upsert_device.assert_called_once()
        dev_kwargs = mock_repo.upsert_device.call_args.kwargs
        assert dev_kwargs["device_id"] == "rtu-1"
        assert dev_kwargs["location_id"] == "loc-1"
        assert dev_kwargs["source_topic"] == "rtu/loc-1/rtu-1/telemetry"
        assert dev_kwargs["parser_name"] == "bliiot_s475e"

        # Metric upsert called once for the sensor
        assert mock_repo.upsert_metric.call_count == 1
        m_kwargs = mock_repo.upsert_metric.call_args.kwargs
        assert m_kwargs["metric_id"] == "rtu-1/register_0"
        assert m_kwargs["value"] == 2375
        assert m_kwargs["unit"] == "0.01°C"

        # Q6: NO legacy path was invoked
        # (subscriber no longer imports RTUService or process_telemetry_message)
        message.ack.assert_awaited_once()
        message.nack.assert_not_called()


class TestDispatchUnknownParser:
    """Non-BLIIoT parsers persist via DeviceMetricRepo (PR3b cutover)."""

    async def test_unknown_parser_persists_via_repo(self):
        """parser_name='some_other' → _persist_reading calls repo (no NotImplementedError).

        PR3b replaced the PR2b stub: every parser now persists via
        DeviceMetricRepo. The dispatch still ACKs the message on success.
        """
        from repositories import device_metric_repo as repo_mod
        from services.mqtt.subscriber import _dispatch

        metric = MetricReading(name="reading_0", value=42.0)
        reading = _make_reading(parser_name="some_other", metrics=(metric,))
        parser = MagicMock()
        parser.name = "some_other"
        parser.parse = MagicMock(return_value=[reading])

        router = _make_router(parser)
        message = _make_message("other/topic/0/telemetry", b'{"foo": 1}')

        mock_repo = MagicMock()
        repo_mod.set_device_metric_repo(mock_repo)

        try:
            await _dispatch(message, router)
        finally:
            repo_mod.set_device_metric_repo(None)

        # Repo was called (no NotImplementedError)
        mock_repo.upsert_device.assert_called_once()
        mock_repo.upsert_metric.assert_called_once()
        # ACK on success
        message.ack.assert_awaited_once()
        message.nack.assert_not_called()


class TestDispatchBliiotExtra:
    """BLIIoT extras (digital_inputs, relays) survive the round-trip."""

    async def test_digital_inputs_and_relays_passed_through(self):
        """reading.extra['digital_inputs']/'relays' end up in repo.upsert_device(extra=...)."""
        from repositories import device_metric_repo as repo_mod
        from services.mqtt.subscriber import _dispatch

        metric = MetricReading(
            name="register_0",
            value=2375,
            unit="0.01°C",
            tags={"register_addr": "0"},
        )
        reading = _make_reading(
            parser_name="bliiot_s475e",
            extra={"digital_inputs": [1, 0, 1, 0], "relays": [0, 1]},
            metrics=(metric,),
        )
        parser = MagicMock()
        parser.name = "bliiot_s475e"
        parser.parse = MagicMock(return_value=[reading])

        router = _make_router(parser)
        message = _make_message("rtu/loc-1/rtu-1/telemetry", b"{}")

        mock_repo = MagicMock()
        repo_mod.set_device_metric_repo(mock_repo)

        try:
            await _dispatch(message, router)
        finally:
            repo_mod.set_device_metric_repo(None)

        sent_extra = mock_repo.upsert_device.call_args.kwargs["extra"]
        assert sent_extra["digital_inputs"] == [1, 0, 1, 0]
        assert sent_extra["relays"] == [0, 1]


# ── mqtt_subscriber_loop smoke ───────────────────────────────────────────────


class TestLoopSmoke:
    """Smoke test for mqtt_subscriber_loop: starts, gets cancelled, propagates."""

    async def test_loop_starts_subscribes_and_cancels(self):
        """Start the loop, wait for it to subscribe, cancel it, assert CancelledError.

        The mock client's ``messages`` async iterator yields nothing but suspends
        on ``asyncio.sleep`` forever — that gives the test a real cancellation
        point so ``task.cancel()`` is delivered promptly (AsyncMock awaits are
        not enough by themselves for cooperative cancellation).
        """
        from services.mqtt.subscriber import mqtt_subscriber_loop

        mock_client = AsyncMock()
        mock_client.subscribe = AsyncMock()

        async def waiting_messages():
            """Async iterator that waits forever — yields nothing but suspends."""
            # Block on a real await so cancel arrives cleanly.
            await asyncio.sleep(3600)
            return
            yield  # noqa: F841 — makes this an async generator

        mock_client.messages = waiting_messages()

        @asynccontextmanager
        async def fake_connect(*_args, **_kwargs):
            yield mock_client

        with patch("services.mqtt.subscriber.connect_mqtt", side_effect=fake_connect):
            task = asyncio.create_task(mqtt_subscriber_loop())
            # Give the loop a moment to subscribe, then cancel.
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        # The loop must have subscribed to all registered patterns (BLIIoT's
        # "rtu/+/+/telemetry") before cancellation.
        subscribe_calls = [c.args[0] for c in mock_client.subscribe.await_args_list]
        assert "rtu/+/+/telemetry" in subscribe_calls
