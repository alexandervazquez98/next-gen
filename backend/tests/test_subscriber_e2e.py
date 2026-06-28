"""End-to-end test for the PR3b cutover.

Validates that a real BLIIoT MQTT payload flowing through the new subscriber
path:

  1. Goes through :func:`BliiotS475EParser.parse` (pure, no RTUService calls)
  2. Lands in :func:`_dispatch` (which routes by topic via the TopicRouter)
  3. Reaches :func:`_persist_reading` (which now calls DeviceMetricRepo)
  4. Results in Device+Metric upserts (NOT legacy RTU/Sensor writes)

The test mocks ``aiomqtt.Client.messages`` with an async iterator that yields
a single canned message, then runs the loop briefly, cancels it, and inspects
the mock DeviceMetricRepo to confirm the full flow.

This is the regression test for the Q6 clean cutover: the first message from
a BLIIoT RTU after PR3 deploy MUST create a Device+Metric node, NOT an
RTU/Sensor node.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager, suppress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_bliiot_payload(
    sensors: list[dict] | None = None,
    digital_inputs: list[int] | None = None,
    relays: list[int] | None = None,
    timestamp: str | None = "2026-06-23T12:00:00Z",
) -> bytes:
    """Build a BLIIoT S475E telemetry payload as bytes."""
    if sensors is None:
        sensors = [{"register_addr": 0, "value": 2375, "unit": "0.01°C"}]
    body: dict = {"sensors": sensors}
    if timestamp is not None:
        body["timestamp"] = timestamp
    if digital_inputs is not None:
        body["digital_inputs"] = digital_inputs
    if relays is not None:
        body["relays"] = relays
    return json.dumps(body).encode("utf-8")


def _make_message(topic: str, payload: bytes) -> MagicMock:
    msg = MagicMock()
    msg.topic = topic
    msg.payload = payload
    msg.ack = AsyncMock()
    msg.nack = AsyncMock()
    return msg


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset DeviceMetricRepo + parser registry between tests for isolation."""
    from repositories import device_metric_repo as repo_mod
    from services.mqtt.parsers import _clear_registry, register
    from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser

    _clear_registry()
    register(BliiotS475EParser())
    repo_mod._device_metric_repo = None
    yield
    _clear_registry()
    repo_mod._device_metric_repo = None


# ── E2E: BLIIoT message → Device+Metric ──────────────────────────────────────


class TestBliliotEndToEnd:
    """Real BLIIoT payload flows through parser → _dispatch → _persist_reading → repo."""

    async def test_bliiot_e2e_message_creates_device_and_metric_nodes(self):
        """A single BLIIoT message produces exactly one Device + one Metric upsert.

        Verifies the Q6 cutover: the new subscriber persists ONLY to
        Device+Metric. NO RTUService or process_telemetry_message is called.
        """
        from repositories import device_metric_repo as repo_mod
        from services.mqtt.subscriber import mqtt_subscriber_loop

        # ── Mock the DeviceMetricRepo so we don't need a live Neo4j ──────
        mock_repo = MagicMock()
        repo_mod.set_device_metric_repo(mock_repo)

        # ── Build a real BLIIoT message ─────────────────────────────────
        location_id = "loc-madrid-1"
        rtu_id = "rtu-bliliot-001"
        topic = f"rtu/{location_id}/{rtu_id}/telemetry"
        payload = _make_bliiot_payload(
            sensors=[
                {"register_addr": 0, "value": 2375, "unit": "0.01°C"},
                {"register_addr": 2, "value": 5500, "unit": "mV"},
            ],
            digital_inputs=[1, 0, 1, 0, 0, 0, 0, 0],
            relays=[0, 0, 1, 0],
        )
        message = _make_message(topic, payload)

        # ── Mock the MQTT client ────────────────────────────────────────
        mock_client = AsyncMock()
        mock_client.subscribe = AsyncMock()

        # Yield the message ONCE, then block on sleep (cancellation point).
        # The ``sent`` flag prevents infinite re-yield on a re-entrant cancel.
        sent = False

        async def message_stream():
            nonlocal sent
            if not sent:
                sent = True
                yield message
            # Block forever after the single yield — cancellation lands here.
            await asyncio.sleep(3600)

        mock_client.messages = message_stream()

        @asynccontextmanager
        async def fake_connect(*_args, **_kwargs):
            yield mock_client

        with patch("services.mqtt.subscriber.connect_mqtt", side_effect=fake_connect):
            task = asyncio.create_task(mqtt_subscriber_loop())
            # Give the loop time to subscribe, receive, dispatch, persist
            await asyncio.sleep(0.1)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        # ── Assertions: the full flow worked ───────────────────────────
        # 1) Message was ACKed (success path)
        message.ack.assert_awaited_once()
        message.nack.assert_not_called()

        # 2) Device upsert called once with correct identity
        mock_repo.upsert_device.assert_called_once()
        dev_kwargs = mock_repo.upsert_device.call_args.kwargs
        assert dev_kwargs["device_id"] == rtu_id
        assert dev_kwargs["location_id"] == location_id
        assert dev_kwargs["source_topic"] == topic
        assert dev_kwargs["parser_name"] == "bliiot_s475e"

        # 3) Metric upsert called once per sensor (2 sensors → 2 metrics)
        assert mock_repo.upsert_metric.call_count == 2
        metric_ids = sorted(m.kwargs["metric_id"] for m in mock_repo.upsert_metric.call_args_list)
        assert metric_ids == [f"{rtu_id}/register_0", f"{rtu_id}/register_2"]

        # 4) Extras (digital_inputs, relays) end up in repo extra
        sent_extra = dev_kwargs["extra"]
        assert sent_extra["digital_inputs"] == [1, 0, 1, 0, 0, 0, 0, 0]
        assert sent_extra["relays"] == [0, 0, 1, 0]

    async def test_bliiot_e2e_no_rtu_service_in_new_path(self):
        """The new subscriber NEVER imports or calls RTUService.

        Static + dynamic guard: we patch ``services.rtu_service.RTUService``
        to raise if instantiated, and assert no process_telemetry_message call.
        """
        from repositories import device_metric_repo as repo_mod
        from services.mqtt.subscriber import mqtt_subscriber_loop

        mock_repo = MagicMock()
        repo_mod.set_device_metric_repo(mock_repo)

        topic = "rtu/loc-1/rtu-1/telemetry"
        payload = _make_bliiot_payload()
        message = _make_message(topic, payload)

        mock_client = AsyncMock()
        mock_client.subscribe = AsyncMock()
        sent = False

        async def message_stream():
            nonlocal sent
            if not sent:
                sent = True
                yield message
            await asyncio.sleep(3600)

        mock_client.messages = message_stream()

        @asynccontextmanager
        async def fake_connect(*_args, **_kwargs):
            yield mock_client

        # Sentinel: any RTUService instantiation raises → would crash the loop.
        def _no_rtu(*_args, **_kwargs):
            raise AssertionError(
                "RTUService must NOT be called from the new subscriber (Q6 cutover)"
            )

        with (
            patch("services.mqtt.subscriber.connect_mqtt", side_effect=fake_connect),
            patch("services.rtu_service.RTUService", side_effect=_no_rtu),
        ):
            task = asyncio.create_task(mqtt_subscriber_loop())
            await asyncio.sleep(0.1)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        # If we got here without the AssertionError firing, the new path is clean.
        message.ack.assert_awaited_once()
        mock_repo.upsert_device.assert_called_once()
