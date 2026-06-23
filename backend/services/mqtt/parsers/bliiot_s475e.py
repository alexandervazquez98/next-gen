"""BLIIoT S475E RTU parser — backward-compatible pluggable parser for the MQTT subscriber.

The BLIIoT S475E is a Modbus/RTU-to-MQTT gateway. It publishes telemetry on
``rtu/{location_id}/{rtu_id}/telemetry`` as a JSON object with this shape::

    {
      "timestamp": "2026-05-04T12:00:00Z",            # optional
      "sensors": [{"register_addr": 0, "value": 2375, "unit": "0.01°C"}],
      "digital_inputs": [1, 0, 1, 0, 0, 0, 0, 0],      # optional, 8 ints
      "relays": [0, 0, 0, 0]                            # optional, 4 ints
    }

This module is the source of truth for that contract. The subscriber loop
dispatches messages whose topic matches :attr:`BliiotS475EParser.topic_patterns`
to :meth:`BliiotS475EParser.parse`, which emits canonical :class:`Reading`
objects.

The two helper functions :func:`parse_telemetry_topic` and
:func:`process_telemetry_message` are kept here (and re-exported from
``services.mqtt_subscriber``) so existing tests and external callers keep
working without modification.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from models.rtu_sensor import TelemetryMessage  # re-exported below for back-compat

from .base import MetricReading, ParseError, Reading

logger = logging.getLogger(__name__)

# Re-export for callers that imported TelemetryMessage from the parser module.
__all__ = [
    "BliiotS475EParser",
    "TelemetryMessage",  # re-export
    "parse_telemetry_topic",
    "process_telemetry_message",
]


# ── Topic parsing ───────────────────────────────────────────────────────────


def parse_telemetry_topic(topic: str) -> tuple[str, str]:
    """Extract (location_id, rtu_id) from an MQTT telemetry topic.

    Topic structure: ``rtu/{location_id}/{rtu_id}/telemetry``.

    Args:
        topic: Full MQTT topic string.

    Returns:
        Tuple of (location_id, rtu_id) as strings.

    Raises:
        ValueError: If topic does not match the expected structure.
    """
    if not topic:
        raise ValueError("Topic cannot be empty")

    segments = topic.split("/")

    if len(segments) != 4:
        raise ValueError(
            f"Expected 4 topic segments (rtu/{{location_id}}/{{rtu_id}}/telemetry), "
            f"got {len(segments)}: '{topic}'"
        )

    prefix, location_id, rtu_id, suffix = segments

    if prefix != "rtu":
        raise ValueError(f"Topic must start with 'rtu/', got '{topic}'")

    if suffix != "telemetry":
        raise ValueError(f"Topic must end with 'telemetry', got '{topic}'")

    return location_id, rtu_id


# ── Timestamp parsing ───────────────────────────────────────────────────────


def _parse_timestamp(value: str | None) -> datetime:
    """Parse an ISO 8601 timestamp string, falling back to ``datetime.now(UTC)``.

    Accepts trailing ``Z`` (Zulu) as UTC, which ``datetime.fromisoformat``
    does NOT handle on Python <3.11 — we normalize it explicitly.
    """
    if value is None:
        return datetime.now(UTC)
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as e:
        raise ParseError(f"Invalid ISO 8601 timestamp '{value}': {e}") from e
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


# ── Metric construction ─────────────────────────────────────────────────────


def _build_metrics(message: TelemetryMessage) -> tuple[MetricReading, ...]:
    """Build one :class:`MetricReading` per sensor in the payload."""
    return tuple(
        MetricReading(
            name=f"register_{sensor.register_addr}",
            value=sensor.value,
            unit=sensor.unit,
            tags={"register_addr": str(sensor.register_addr)},
        )
        for sensor in message.sensors
    )


def _build_extra(message: TelemetryMessage) -> Mapping[str, Any]:
    """Capture present optional fields (``digital_inputs`` / ``relays``) only."""
    extra: dict[str, Any] = {}
    if message.digital_inputs is not None:
        extra["digital_inputs"] = list(message.digital_inputs)
    if message.relays is not None:
        extra["relays"] = list(message.relays)
    return extra


# ── Backward-compatible persistence helper ──────────────────────────────────


def process_telemetry_message(
    topic: str,
    msg: TelemetryMessage,
    rtu_service: Any,
) -> dict[str, Any]:
    """Process a parsed TelemetryMessage and upsert RTU/Sensor nodes into Neo4j.

    Preserves the legacy return contract so existing tests and external
    callers keep working without modification. PR3b will redirect BLIIoT
    persistence through :class:`DeviceMetricRepo`; this helper is kept as the
    in-process call site until then.

    Args:
        topic: Full MQTT topic string (used for error messages).
        msg: Parsed TelemetryMessage Pydantic model.
        rtu_service: RTUService instance for Neo4j operations.

    Returns:
        Dict with keys ``status``, ``rtu_id``, ``sensor_count``, ``error``.
    """
    try:
        location_id, rtu_id = parse_telemetry_topic(topic)
    except ValueError as e:
        logger.error("[MQTT] Invalid topic '%s': %s", topic, e)
        return {"status": "error", "error": f"Invalid topic: {e}"}

    try:
        rtu_service.get_or_create_rtu(
            rtu_id=rtu_id,
            location_id=location_id,
            name=f"RTU-{rtu_id[:8]}",
            ip=None,
        )

        sensor_count = 0
        for sensor in msg.sensors:
            try:
                rtu_service.get_or_create_sensor(
                    rtu_id=rtu_id,
                    register_addr=sensor.register_addr,
                    name=f"Sensor-{sensor.register_addr}",
                    unit=sensor.unit,
                    sensor_type="analog_input",
                )
                sensor_count += 1
            except ValueError as e:
                logger.warning(
                    "[MQTT] Skipping sensor at addr %s for RTU %s: %s",
                    sensor.register_addr,
                    rtu_id,
                    e,
                )
                continue

        return {
            "status": "processed",
            "rtu_id": rtu_id,
            "sensor_count": sensor_count,
        }

    except Exception as e:
        logger.error(
            "[MQTT] Failed to process telemetry from %s: %s",
            topic,
            e,
            exc_info=True,
        )
        return {"status": "error", "error": str(e)}


# ── Parser class ────────────────────────────────────────────────────────────


class BliiotS475EParser:
    """Pluggable parser for the BLIIoT S475E RTU telemetry format.

    Emits one :class:`Reading` per message. The Reading's ``device_id`` is
    the ``rtu_id`` extracted from the topic; ``location_id`` is the location
    segment; ``metrics`` is one :class:`MetricReading` per sensor; ``extra``
    carries ``digital_inputs`` and ``relays`` when present in the payload.
    """

    name = "bliiot_s475e"
    topic_patterns: tuple[str, ...] = ("rtu/+/+/telemetry",)

    def parse(self, topic: str, payload: bytes) -> list[Reading]:
        """Decode a BLIIoT telemetry message into a canonical :class:`Reading`.

        Args:
            topic: The full MQTT topic — must be ``rtu/{loc}/{rtu}/telemetry``.
            payload: The raw UTF-8 JSON body from the broker.

        Returns:
            A single-element list containing the canonical Reading. Empty
            sensors is a Pydantic validation failure and raises :class:`ParseError`.

        Raises:
            ParseError: Topic, encoding, JSON, or payload validation failure.
        """
        try:
            location_id, rtu_id = parse_telemetry_topic(topic)
        except ValueError as e:
            raise ParseError(f"Invalid topic '{topic}': {e}") from e

        try:
            payload_str = payload.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ParseError(f"Non-UTF-8 payload on topic '{topic}': {e}") from e

        try:
            payload_dict = json.loads(payload_str)
        except json.JSONDecodeError as e:
            raise ParseError(f"Invalid JSON on topic '{topic}': {e}") from e

        try:
            body = TelemetryMessage.model_validate(payload_dict)
        except Exception as e:  # Pydantic ValidationError or any wrapper
            raise ParseError(f"Payload validation failed on topic '{topic}': {e}") from e

        return [
            Reading(
                device_id=rtu_id,
                location_id=location_id,
                timestamp=_parse_timestamp(body.timestamp),
                metrics=_build_metrics(body),
                source_topic=topic,
                parser_name=self.name,
                extra=_build_extra(body),
            )
        ]
