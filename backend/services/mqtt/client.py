"""MQTT broker client helper (PR2b).

Provides:
  * :func:`parse_broker_url` — pure parser for ``mqtt://host:port`` /
    ``mqtts://host:port`` URLs.
  * :func:`connect_mqtt` — async context manager that wraps
    :class:`aiomqtt.Client` with credentials and TLS configuration pulled
    from :class:`~config.MQTTSettings`.

The shared helper exists so :mod:`services.mqtt.subscriber` and (later)
:mod:`services.escalation_notifier` can reuse the same connect logic. PR2b
does NOT modify ``escalation_notifier.py`` — that migration is out of scope
per design §2.7.
"""

from __future__ import annotations

import logging
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import aiomqtt

if TYPE_CHECKING:
    from config import MQTTSettings

logger = logging.getLogger(__name__)

__all__ = ["parse_broker_url", "connect_mqtt"]


# Default MQTT ports per the spec — used when no port is supplied in the URL.
_MQTT_DEFAULT_PORT = 1883
_MQTTS_DEFAULT_PORT = 8883


def parse_broker_url(url: str) -> tuple[str, int, bool]:
    """Parse an MQTT broker URL into ``(host, port, use_tls)``.

    Supported schemes:
      * ``mqtt://host[:port]`` → ``(host, port, False)``. Default port 1883.
      * ``mqtts://host[:port]`` → ``(host, port, True)``. Default port 8883.

    Args:
        url: Broker URL string from :attr:`MQTTSettings.broker_url`.

    Returns:
        Tuple ``(host, port, use_tls)`` ready to pass to :class:`aiomqtt.Client`.

    Raises:
        ValueError: The URL is empty, has an unsupported scheme, has a path
            (``mqtt://host:port/extra``), or is otherwise malformed.
    """
    if not url:
        raise ValueError("Broker URL cannot be empty")

    parsed = urlparse(url)

    if parsed.scheme not in ("mqtt", "mqtts"):
        raise ValueError(
            f"Unsupported broker URL scheme {parsed.scheme!r}; expected 'mqtt' or 'mqtts'"
        )

    if parsed.path and parsed.path != "":
        raise ValueError(f"Broker URL must not contain a path component: {url!r}")

    host = parsed.hostname
    if not host:
        raise ValueError(f"Broker URL is missing a hostname: {url!r}")

    use_tls = parsed.scheme == "mqtts"

    if parsed.port is not None:
        port = parsed.port
    elif use_tls:
        port = _MQTTS_DEFAULT_PORT
    else:
        port = _MQTT_DEFAULT_PORT

    return host, port, use_tls


@asynccontextmanager
async def connect_mqtt(
    settings: MQTTSettings,
) -> AsyncIterator[aiomqtt.Client]:
    """Open a short-lived MQTT connection, yielding the connected client.

    The returned :class:`aiomqtt.Client` is itself an async context manager,
    so this helper is a thin wrapper that:
      1. Parses ``settings.broker_url`` via :func:`parse_broker_url`.
      2. Configures credentials, client identifier, and TLS from ``settings``.
      3. Yields the connected client and disconnects on exit.

    Args:
        settings: Loaded :class:`~config.MQTTSettings` instance.

    Yields:
        A connected :class:`aiomqtt.Client` ready for subscribe/publish.

    Raises:
        ValueError: Broker URL is malformed.
        aiomqtt.MqttError: Broker handshake failed.
    """
    host, port, use_tls = parse_broker_url(settings.broker_url)

    tls_context = ssl.create_default_context() if use_tls else None

    async with aiomqtt.Client(
        hostname=host,
        port=port,
        username=settings.username,
        password=settings.password,
        identifier=settings.client_id,
        tls_context=tls_context,
    ) as client:
        logger.debug(
            "[MQTT] Connected to %s://%s:%d (tls=%s, client_id=%s)",
            "mqtts" if use_tls else "mqtt",
            host,
            port,
            use_tls,
            settings.client_id,
        )
        yield client
