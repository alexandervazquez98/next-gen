"""MQTT subscriber loop — router-driven dispatcher with DeviceMetricRepo persistence.

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

Persistence (PR3b): the new subscriber persists ONLY to :class:`Device` and
:class:`Metric` nodes via :class:`DeviceMetricRepo`. The legacy RTU/Sensor
path is intentionally NOT called from here — this is the Q6 clean cutover.
The legacy helper :func:`services.mqtt.parsers.bliiot_s475e.process_telemetry_message`
remains importable for back-compat (tests, external callers) but is dead code
from the subscriber's perspective.

The :func:`mqtt_subscriber_loop` symbol is preserved so the back-compat shim
in ``services/mqtt_subscriber`` keeps working without modification.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from config import get_mqtt_runtime_settings, get_mqtt_settings
from postgres_db import SessionLocal
from repositories.device_metric_repo import get_device_metric_repo
from services.mqtt.client import connect_mqtt
from services.mqtt.metrics import metrics
from services.mqtt.parsers.base import ParseError
from services.mqtt.topic_router import TopicRouter
from services.mqtt_bridge_service import get_mqtt_bridge_service
from services.mqtt_runtime_status import get_mqtt_runtime_status_service

if TYPE_CHECKING:
    from services.mqtt.parsers.base import Reading

logger = logging.getLogger(__name__)

__all__ = ["mqtt_subscriber_loop", "_dispatch", "_persist_reading"]


def _safe_status_update(action: str, callback: Any) -> None:
    """Best-effort runtime status update that never owns subscriber liveness."""
    try:
        callback()
    except Exception:
        logger.warning("[MQTT] Runtime status update failed during %s", action, exc_info=True)


# Reconnect backoff bounds per design §2.6 and REQ-SUB-03.
_INITIAL_BACKOFF_S = 1.0
_MAX_BACKOFF_S = 30.0

# Heartbeat cadence for idle loops (seconds). The loop emits periodic heartbeats
# even without inbound messages so raw subscribers stay visible as running.
_HEARTBEAT_IDLE_INTERVAL_MIN_S = 5.0
_HEARTBEAT_IDLE_INTERVAL_MAX_S = 60.0

# 4 KB cap on the serialized ``extra`` blob per Q2 decision. The cap prevents
# a single message from bloating Neo4j property storage; over-cap payloads are
# replaced with a small truncation marker so downstream readers still see the
# message landed.
EXTRA_SIZE_CAP_BYTES = 4096


# ── Public loop ─────────────────────────────────────────────────────────────


async def mqtt_subscriber_loop() -> None:
    """Run the subscriber loop forever, reconnecting with exponential backoff.

    Lifecycle:
      * Read MQTT settings (cached singleton).
      * Build a :class:`TopicRouter` from the parser registry.
      * Enter a ``while True`` that opens a connection, subscribes to every
        registered pattern, and consumes inbound messages.
      * Update shared runtime status on connect/disconnect/heartbeat.
      * On connection error, sleep ``backoff`` seconds, double up to
        ``MAX_BACKOFF_S``, and retry.
      * On ``asyncio.CancelledError``, log and propagate so the container
        shutdown signal is honored.
    """
    settings = get_mqtt_settings()
    runtime_settings = get_mqtt_runtime_settings()
    router: TopicRouter = TopicRouter()
    backoff = _INITIAL_BACKOFF_S
    subscribed_patterns = list(router.subscribe_patterns())

    status_service = get_mqtt_runtime_status_service(
        stale_heartbeat_seconds=runtime_settings.missed_heartbeat_seconds
    )
    _safe_status_update("configured", lambda: status_service.mark_configured(True))

    while True:
        try:
            async with connect_mqtt(settings) as client:
                # Connected — reset the backoff so a future drop starts at 1s again.
                backoff = _INITIAL_BACKOFF_S
                _safe_status_update(
                    "heartbeat",
                    lambda: status_service.record_heartbeat(
                        running=True,
                        connected=True,
                        subscribed_patterns=subscribed_patterns,
                    ),
                )

                logger.info(
                    "[MQTT] Connected; subscribing to %d pattern(s)",
                    len(subscribed_patterns),
                )

                for pattern in subscribed_patterns:
                    await client.subscribe(pattern, settings.qos)
                    logger.debug(
                        "[MQTT] Subscribed to pattern %r (qos=%d)",
                        pattern,
                        settings.qos,
                    )

                heartbeat_interval = max(
                    _HEARTBEAT_IDLE_INTERVAL_MIN_S,
                    min(
                        _HEARTBEAT_IDLE_INTERVAL_MAX_S,
                        runtime_settings.missed_heartbeat_seconds / 3,
                    ),
                )
                next_heartbeat_after = asyncio.get_running_loop().time() + heartbeat_interval
                message_stream = client.messages.__aiter__()
                message_task = asyncio.create_task(anext(message_stream))

                try:
                    while True:
                        timeout = next_heartbeat_after - asyncio.get_running_loop().time()
                        if timeout <= 0:
                            timeout = 0

                        done, _pending = await asyncio.wait({message_task}, timeout=timeout)
                        if not done:
                            _safe_status_update(
                                "heartbeat",
                                lambda: status_service.record_heartbeat(
                                    running=True,
                                    connected=True,
                                    subscribed_patterns=subscribed_patterns,
                                ),
                            )
                            next_heartbeat_after = (
                                asyncio.get_running_loop().time() + heartbeat_interval
                            )
                            continue

                        message = message_task.result()
                        message_task = asyncio.create_task(anext(message_stream))
                        await _dispatch(message, router)
                        _safe_status_update(
                            "heartbeat",
                            lambda: status_service.record_heartbeat(
                                running=True,
                                connected=True,
                                subscribed_patterns=subscribed_patterns,
                            ),
                        )
                        next_heartbeat_after = (
                            asyncio.get_running_loop().time() + heartbeat_interval
                        )
                finally:
                    if not message_task.done():
                        message_task.cancel()

        except asyncio.CancelledError:
            logger.info("[MQTT] Subscriber cancelled — propagating for container shutdown")
            _safe_status_update("shutdown", lambda: status_service.record_disconnect("SHUTDOWN"))
            raise
        except Exception as e:
            error_text = str(e)
            _safe_status_update(
                "disconnect",
                lambda error_text=error_text: status_service.record_disconnect(
                    reason_code="MQTT_SUBSCRIBER_CONNECTION_ERROR",
                    error=error_text,
                ),
            )
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

    Per-parser metrics (PR4): every outcome increments a counter on the
    module-level :data:`services.mqtt.metrics.metrics` store. Keys are
    ``name{parser=<parser_name>}`` so operators can slice per device family.

    Args:
        message: An aiomqtt message exposing ``topic`` (str), ``payload`` (bytes),
            and async ``ack()`` / ``nack()`` methods.
        router: A :class:`TopicRouter` that resolves topics to parsers.
    """
    topic = str(message.topic)
    parser = router.resolve(topic)

    if parser is None:
        # No parser → no counter (we don't know which parser to attribute to).
        # This is the only outcome that does NOT touch the metrics store.
        logger.error("[MQTT] No parser for topic %r — ACKing to drop the message", topic)
        await message.ack()
        return

    try:
        readings = parser.parse(topic, message.payload)
    except Exception as e:
        if isinstance(e, ParseError):
            metrics.inc("parse_fail", parser=parser.name)
            logger.error(
                "[MQTT] Parser %r failed on topic %r: %s — ACKing (payload is unrecoverable)",
                parser.name,
                topic,
                e,
            )
            await message.ack()
            return

        metrics.inc("nack", parser=parser.name)
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
        metrics.inc("nack", parser=parser.name)
        logger.exception("[MQTT] Persistence failed for topic %r: %s — NACKing", topic, e)
        await message.nack()
        return

    # Success path — count once per message with the number of readings produced.
    metrics.inc("parsed_ok", count=len(readings), parser=parser.name)
    logger.debug("[MQTT] Processed %d reading(s) for topic %r", len(readings), topic)
    await message.ack()


# ── Persistence ─────────────────────────────────────────────────────────────


async def _persist_reading(reading: Reading) -> None:
    """Persist a canonical :class:`Reading` via :class:`DeviceMetricRepo`.

    Replaces the PR2b stub. Implements the Q6 clean cutover: the new subscriber
    persists ONLY to :class:`Device` and :class:`Metric` nodes via
    :class:`DeviceMetricRepo`. It never calls the legacy persistence path. The
    legacy helper :func:`services.mqtt.parsers.bliiot_s475e.process_telemetry_message`
    remains importable for back-compat only (external callers + the legacy test suite).

    Contract (per design §2.6 and Q1/Q2 decisions):

      * Calls ``repo.upsert_device`` once, then ``repo.upsert_metric`` once per
        :class:`MetricReading`. The repo's MERGE keeps every call idempotent,
        so MQTT redelivery is safe.
      * ``Reading.extra`` is capped at :data:`EXTRA_SIZE_CAP_BYTES` (4 KB,
        Q2). When the serialized JSON exceeds the cap, the extra is replaced
        with ``{"_truncated": True, "_original_size": N}`` and a warning is
        logged so operators can spot abusive payloads.
      * Any exception from the repo is wrapped in :class:`RuntimeError` with
        the device id / metric id in the message. This gives the caller
        (:func:`_dispatch`) a uniform error to NACK on per design §2.6.

    Note: ``DeviceMetricRepo`` exposes SYNC methods (matching the
    ``topology_repo`` / ``rtu_sensor_repo`` conventions — see
    ``repositories/device_metric_repo.py`` docstring). This function is still
    ``async def`` so the existing ``await _persist_reading(reading)`` call
    site in :func:`_dispatch` does not need to change.

    Args:
        reading: A canonical :class:`Reading` produced by a registered parser.

    Raises:
        RuntimeError: Wrapped repo / driver error (caller NACKs the message).
    """
    repo = get_device_metric_repo()

    # 4 KB cap on extra (Q2). Serialization cost is negligible per message.
    extra = dict(reading.extra or {})
    extra_json = json.dumps(extra, default=str)
    if len(extra_json) > EXTRA_SIZE_CAP_BYTES:
        original_size = len(extra_json)
        extra = {"_truncated": True, "_original_size": original_size}
        logger.warning(
            "Reading extra truncated: %d bytes > %d cap (device_id=%s)",
            original_size,
            EXTRA_SIZE_CAP_BYTES,
            reading.device_id,
        )

    # Upsert device (idempotent MERGE on Device.id).
    try:
        repo.upsert_device(
            device_id=reading.device_id,
            name=reading.device_id,  # default name to id until we have richer metadata
            location_id=reading.location_id,
            source_topic=reading.source_topic,
            parser_name=reading.parser_name,
            extra=extra,
        )
    except Exception as e:
        raise RuntimeError(f"Device upsert failed for {reading.device_id!r}: {e}") from e

    # Upsert each metric.
    for metric in reading.metrics:
        metric_id = f"{reading.device_id}/{metric.name}"
        try:
            repo.upsert_metric(
                metric_id=metric_id,
                device_id=reading.device_id,
                name=metric.name,
                value=metric.value,
                unit=metric.unit,
                ts=reading.timestamp,
                tags=dict(metric.tags or {}),
            )
        except Exception as e:
            raise RuntimeError(f"Metric upsert failed for {metric_id!r}: {e}") from e

    # Bridge to KPI/event path is failure-observability-only by design.
    # Raw persistence must remain independent; never block on bridge failures.
    if get_mqtt_runtime_settings().bridge_enabled:
        try:
            bridge_service = get_mqtt_bridge_service(event_writer_lock_db=SessionLocal)
            bridge_service.process_reading(reading)
        except Exception:
            logger.warning(
                "Bridge processing failed for device=%r: continuing raw persistence",
                reading.device_id,
                exc_info=True,
            )
