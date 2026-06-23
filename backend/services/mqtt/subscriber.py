"""MQTT subscriber loop — PR2b router-driven dispatcher.

This module is the runtime heart of the new subscriber. The legacy BLIIoT-only
loop has been replaced with a generic dispatcher that:

  1. Opens a connection via :func:`services.mqtt.client.connect_mqtt`.
  2. Builds a :class:`TopicRouter` from the parser registry.
  3. Subscribes to the deduplicated union of every parser's ``topic_patterns``.
  4. Iterates inbound messages and dispatches each through
     :func:`_dispatch` — which routes by topic, parses, persists, then ACKs
     or NACKs the message per design §2.6.
  5. Reconnects with exponential backoff (1s → 30s cap) on transient errors.
  6. Propagates ``asyncio.CancelledError`` so container shutdown works cleanly.

Persistence is a PR2b stub:
  * BLIIoT readings (parser_name == ``"bliiot_s475e"``) are persisted via the
    legacy :func:`services.mqtt.parsers.bliiot_s475e.process_telemetry_message`
    helper. This keeps the legacy RTU/Sensor write path operational.
  * All other parsers raise :class:`NotImplementedError` from
    :func:`_persist_reading` until PR3b replaces the body with a
    :class:`DeviceMetricRepo` integration.

The :func:`mqtt_subscriber_loop` symbol is preserved so the back-compat shim
in ``services/mqtt_subscriber`` keeps working without modification.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC
from typing import TYPE_CHECKING, Any

from config import get_mqtt_settings
from services.mqtt.client import connect_mqtt
from services.mqtt.parsers.base import ParseError
from services.mqtt.parsers.bliiot_s475e import process_telemetry_message
from services.mqtt.topic_router import TopicRouter
from services.rtu_service import RTUService

if TYPE_CHECKING:
    from services.mqtt.parsers.base import Reading

logger = logging.getLogger(__name__)

__all__ = ["mqtt_subscriber_loop", "_dispatch", "_persist_reading"]


# Reconnect backoff bounds per design §2.6 and REQ-SUB-03.
_INITIAL_BACKOFF_S = 1.0
_MAX_BACKOFF_S = 30.0


# ── Public loop ─────────────────────────────────────────────────────────────


async def mqtt_subscriber_loop() -> None:
    """Run the subscriber loop forever, reconnecting with exponential backoff.

    Lifecycle:
      * Read MQTT settings (cached singleton).
      * Build a :class:`TopicRouter` from the parser registry.
      * Enter a ``while True`` that opens a connection, subscribes to every
        registered pattern, and consumes inbound messages.
      * On connection error, sleep ``backoff`` seconds, double up to
        ``MAX_BACKOFF_S``, and retry.
      * On ``asyncio.CancelledError``, log and propagate so the container
        shutdown signal is honored.
    """
    settings = get_mqtt_settings()
    router: TopicRouter = TopicRouter()
    backoff = _INITIAL_BACKOFF_S

    while True:
        try:
            async with connect_mqtt(settings) as client:
                # Connected — reset the backoff so a future drop starts at 1s again.
                backoff = _INITIAL_BACKOFF_S
                logger.info(
                    "[MQTT] Connected; subscribing to %d pattern(s)",
                    len(router.subscribe_patterns()),
                )

                for pattern in router.subscribe_patterns():
                    await client.subscribe(pattern, settings.qos)
                    logger.debug("[MQTT] Subscribed to pattern %r (qos=%d)", pattern, settings.qos)

                async for message in client.messages:
                    await _dispatch(message, router)

        except asyncio.CancelledError:
            logger.info("[MQTT] Subscriber cancelled — propagating for container shutdown")
            raise
        except Exception as e:
            logger.warning(
                "[MQTT] Connection error: %s; retrying in %.1fs", e, backoff, exc_info=True
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF_S)


# ── Dispatch ────────────────────────────────────────────────────────────────


async def _dispatch(message: Any, router: TopicRouter) -> None:
    """Route one MQTT message through the parser registry, persist, ACK/NACK.

    ACK/NACK policy (per design §2.6):
      * No parser resolved → log error, ACK (drop — no parser means no owner).
      * :class:`ParseError` from ``parser.parse()`` → log, ACK (payload is bad).
      * Any other parser exception → log, NACK (could be transient — redeliver).
      * Persistence exception → log, NACK (Neo4j transient — redeliver).
      * Success → persist all readings, ACK.

    Args:
        message: An aiomqtt message exposing ``topic`` (str), ``payload`` (bytes),
            and async ``ack()`` / ``nack()`` methods.
        router: A :class:`TopicRouter` that resolves topics to parsers.
    """
    topic = str(message.topic)
    parser = router.resolve(topic)

    if parser is None:
        logger.error("[MQTT] No parser for topic %r — ACKing to drop the message", topic)
        await message.ack()
        return

    try:
        readings = parser.parse(topic, message.payload)
    except Exception as e:
        if isinstance(e, ParseError):
            logger.error(
                "[MQTT] Parser %r failed on topic %r: %s — ACKing (payload is unrecoverable)",
                parser.name,
                topic,
                e,
            )
            await message.ack()
            return

        logger.exception(
            "[MQTT] Parser %r raised unexpected exception on topic %r: %s — NACKing",
            parser.name,
            topic,
            e,
        )
        await message.nack()
        return

    try:
        for reading in readings:
            await _persist_reading(reading)
    except Exception as e:
        logger.exception("[MQTT] Persistence failed for topic %r: %s — NACKing", topic, e)
        await message.nack()
        return

    logger.debug("[MQTT] Processed %d reading(s) for topic %r", len(readings), topic)
    await message.ack()


# ── Persistence ─────────────────────────────────────────────────────────────


async def _persist_reading(reading: Reading) -> None:
    """Persist a single :class:`Reading`.

    PR2b stub: BLIIoT readings flow through the legacy
    :func:`services.mqtt.parsers.bliiot_s475e.process_telemetry_message` helper
    so the existing RTU/Sensor Neo4j writes keep working. PR3b will replace
    this body with :class:`DeviceMetricRepo` upserts so non-BLIIoT parsers can
    persist via the generic Device+Metric model.

    Args:
        reading: A canonical :class:`Reading` produced by a registered parser.

    Raises:
        NotImplementedError: The reading's parser is not yet wired to the new
            DeviceMetricRepo. PR3b will replace this path with a repo call.
    """
    if reading.parser_name == "bliiot_s475e":
        _persist_bliiot_reading(reading)
        return

    raise NotImplementedError(
        f"_persist_reading not implemented for parser {reading.parser_name!r}; "
        "PR3b will replace this stub with a DeviceMetricRepo.upsert_* call."
    )


def _persist_bliiot_reading(reading: Reading) -> None:
    """Sync helper: convert a BLIIoT :class:`Reading` and call the legacy helper.

    Pulled out of :func:`_persist_reading` so the conversion logic is easy to
    test in isolation if we ever need it.
    """
    msg = _reading_to_telemetry_message(reading)
    rtu_service = RTUService()
    process_telemetry_message(reading.source_topic, msg, rtu_service)


def _reading_to_telemetry_message(reading: Reading) -> Any:
    """Reconstruct a :class:`TelemetryMessage` Pydantic model from a Reading.

    The BLIIoT :class:`MetricReading` stores the Modbus register address in
    the ``register_addr`` tag (a string). ``digital_inputs`` and ``relays``
    survive through :attr:`Reading.extra`.
    """
    from models.rtu_sensor import TelemetryMessage

    sensors_data: list[dict[str, Any]] = []
    for metric in reading.metrics:
        # ``tags["register_addr"]`` is stored as a string by the parser.
        raw_addr = metric.tags.get("register_addr", "0")
        try:
            register_addr = int(raw_addr)
        except (TypeError, ValueError):
            register_addr = 0
        sensors_data.append(
            {
                "register_addr": register_addr,
                "value": metric.value,
                "unit": metric.unit,
            }
        )

    msg_dict: dict[str, Any] = {"sensors": sensors_data}

    ts = reading.timestamp
    if ts is not None:
        # ``datetime.isoformat()`` returns "+00:00" suffixes — TelemetryMessage
        # accepts those; only the trailing "Z" needs normalizing (legacy code
        # path via ``TelemetryMessage`` pydantic-validates ISO 8601 directly).
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        msg_dict["timestamp"] = ts.isoformat()

    if isinstance(reading.extra, Mapping):
        for key in ("digital_inputs", "relays"):
            if key in reading.extra:
                msg_dict[key] = list(reading.extra[key])

    return TelemetryMessage.model_validate(msg_dict)
