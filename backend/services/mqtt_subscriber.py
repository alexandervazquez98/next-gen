"""MQTT Subscriber Service — async background worker for RTU telemetry ingestion.

Uses aiomqtt (async MQTT client) to subscribe to the wildcard topic
`rtu/+/+/telemetry`, parse incoming JSON payloads, and upsert RTU/Sensor
nodes into Neo4j via RTUService.

Design decisions (from design.md):
- Library: aiomqtt>=2.0.0 (best async integration, fits asyncio patterns)
- Runner: Background task in main.py startup (like snmp_collector_loop)
- Reconnection: Exponential backoff (1s → 2s → 4s → 30s cap)
- Message ACK: ACK on parse failure, ACK on Neo4j success, NACK on Neo4j transient failure
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from models.rtu_sensor import TelemetryMessage
from services.rtu_service import RTUService
from config import get_mqtt_settings

logger = logging.getLogger(__name__)

# ── MQTT Settings (loaded from environment via config.py) ────────────────────
_mqtt_settings = get_mqtt_settings()

MQTT_BROKER_URL: str = _mqtt_settings.broker_url
MQTT_USERNAME: Optional[str] = _mqtt_settings.username
MQTT_PASSWORD: Optional[str] = _mqtt_settings.password
MQTT_CLIENT_ID: str = _mqtt_settings.client_id
MQTT_WILDCARD_TOPIC: str = _mqtt_settings.wildcard_topic
MQTT_QOS: int = _mqtt_settings.qos

# ── Topic Parsing ─────────────────────────────────────────────────────────────


def parse_telemetry_topic(topic: str) -> tuple[str, str]:
    """Extract (location_id, rtu_id) from an MQTT telemetry topic.

    Topic structure: rtu/{location_id}/{rtu_id}/telemetry

    Args:
        topic: Full MQTT topic string

    Returns:
        Tuple of (location_id, rtu_id) as strings

    Raises:
        ValueError: If topic does not match the expected structure
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


# ── Message Processing ────────────────────────────────────────────────────────


def process_telemetry_message(
    topic: str,
    msg: TelemetryMessage,
    rtu_service: RTUService,
) -> dict:
    """Process a parsed TelemetryMessage and upsert RTU/Sensor nodes into Neo4j.

    Args:
        topic: Full MQTT topic string (used for error messages)
        msg: Parsed TelemetryMessage Pydantic model
        rtu_service: RTUService instance for Neo4j operations

    Returns:
        Dict with keys:
          - status: "processed" | "error"
          - rtu_id: The RTU id (on success)
          - sensor_count: Number of sensors upserted
          - error: Error message (on failure)
    """
    try:
        location_id, rtu_id = parse_telemetry_topic(topic)
    except ValueError as e:
        logger.error("[MQTT] Invalid topic '%s': %s", topic, e)
        return {"status": "error", "error": f"Invalid topic: {e}"}

    try:
        # Upsert RTU node (get-or-create)
        rtu_service.get_or_create_rtu(
            rtu_id=rtu_id,
            location_id=location_id,
            name=f"RTU-{rtu_id[:8]}",
            ip=None,
        )

        # Upsert each sensor from the payload
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
                # Invalid sensor register — skip this sensor, continue processing
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


# ── MQTT Subscriber Loop ───────────────────────────────────────────────────────


async def mqtt_subscriber_loop() -> None:
    """Main MQTT subscriber loop — connects, subscribes, and processes messages.

    Runs as a long-lived background task. Implements exponential backoff
    reconnection (1s → 2s → 4s → 30s cap). Handles SIGTERM via asyncio.CancelledError.

    Uses aiomqtt for async MQTT client operations.
    """
    try:
        import aiomqtt
    except ImportError:
        logger.error(
            "[MQTT] aiomqtt not installed. MQTT subscriber disabled. "
            "Install with: pip install aiomqtt>=2.0.0"
        )
        return

    logger.info("[MQTT] Starting MQTT subscriber loop")

    rtu_service = RTUService()
    backoff_delay = 1.0
    max_backoff_delay = 30.0

    while True:
        try:
            # Build broker URL from components
            broker_url = MQTT_BROKER_URL
            # Parse mqtt://host:port format
            if broker_url.startswith("mqtt://"):
                host_port = broker_url[7:]  # strip 'mqtt://'
                if ":" in host_port:
                    host, port_str = host_port.rsplit(":", 1)
                    port = int(port_str)
                else:
                    host = host_port
                    port = 1883
            else:
                host = broker_url
                port = 1883

            logger.info(
                "[MQTT] Connecting to broker %s:%s (client_id=%s)",
                host,
                port,
                MQTT_CLIENT_ID,
            )

            async with aiomqtt.connect(
                host=host,
                port=port,
                username=MQTT_USERNAME,
                password=MQTT_PASSWORD,
                client_id=MQTT_CLIENT_ID,
                timeout=5.0,
            ) as client:
                logger.info(
                    "[MQTT] Connected. Subscribing to '%s' (QoS %d)",
                    MQTT_WILDCARD_TOPIC,
                    MQTT_QOS,
                )
                await client.subscribe(MQTT_WILDCARD_TOPIC, MQTT_QOS)

                # Reset backoff on successful connection
                backoff_delay = 1.0

                async for message in client.messages:
                    try:
                        try:
                            payload_str = message.payload.decode("utf-8")
                        except UnicodeDecodeError as e:
                            logger.error(
                                "[MQTT] Non-UTF8 payload on topic '%s': %s — ACKing to discard",
                                message.topic,
                                e,
                            )
                            await message.ack()
                            continue

                        try:
                            payload = json.loads(payload_str)
                        except json.JSONDecodeError as e:
                            logger.error(
                                "[MQTT] Invalid JSON on topic '%s': %s — ACKing to discard",
                                message.topic,
                                e,
                            )
                            await message.ack()
                            continue

                        telemetry = TelemetryMessage(**payload)
                    except Exception as e:
                        logger.error(
                            "[MQTT] Failed to parse payload on topic '%s': %s — ACKing to discard",
                            message.topic,
                            e,
                        )
                        await message.ack()
                        continue

                    try:
                        result = process_telemetry_message(
                            topic=str(message.topic),
                            msg=telemetry,
                            rtu_service=rtu_service,
                        )

                        if result["status"] == "processed":
                            logger.debug(
                                "[MQTT] Processed RTU %s with %d sensors",
                                result.get("rtu_id"),
                                result.get("sensor_count"),
                            )
                            await message.ack()
                        else:
                            logger.warning(
                                "[MQTT] Processing failed for topic '%s': %s — NACKing for redelivery",
                                message.topic,
                                result.get("error"),
                            )
                            await message.nack()

                    except asyncio.CancelledError:
                        await message.ack()
                        raise
                    except Exception as e:
                        logger.error(
                            "[MQTT] Unexpected error processing message on topic '%s': %s",
                            message.topic,
                            e,
                            exc_info=True,
                        )
                        await message.nack()

        except asyncio.CancelledError:
            logger.info("[MQTT] Subscriber cancelled (SIGTERM). Shutting down.")
            raise

        except Exception as e:
            logger.warning(
                "[MQTT] Connection error: %s. Reconnecting in %.1fs",
                e,
                backoff_delay,
                exc_info=True,
            )
            await asyncio.sleep(backoff_delay)
            backoff_delay = min(backoff_delay * 2, max_backoff_delay)
