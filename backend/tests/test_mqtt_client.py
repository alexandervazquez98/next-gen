"""Unit tests for the MQTT client helper (PR2b).

Covers ``parse_broker_url`` (sync) and ``connect_mqtt`` (async context manager).
``connect_mqtt`` is tested with a mocked ``aiomqtt.Client`` — no live broker.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = [pytest.mark.unit]


# ── parse_broker_url ─────────────────────────────────────────────────────────


class TestParseBrokerUrl:
    """Pure-function tests for parse_broker_url — no broker, no asyncio."""

    def test_mqtt_plain_returns_host_port_no_tls(self):
        """mqtt://localhost:1883 → ('localhost', 1883, False)."""
        from services.mqtt.client import parse_broker_url

        host, port, tls = parse_broker_url("mqtt://localhost:1883")
        assert host == "localhost"
        assert port == 1883
        assert tls is False

    def test_mqtts_returns_tls_true(self):
        """mqtts://broker.example.com:8883 → ('broker.example.com', 8883, True)."""
        from services.mqtt.client import parse_broker_url

        host, port, tls = parse_broker_url("mqtts://broker.example.com:8883")
        assert host == "broker.example.com"
        assert port == 8883
        assert tls is True

    def test_mqtt_default_port_when_omitted(self):
        """mqtt://localhost (no port) defaults to 1883."""
        from services.mqtt.client import parse_broker_url

        host, port, tls = parse_broker_url("mqtt://localhost")
        assert host == "localhost"
        assert port == 1883
        assert tls is False

    def test_mqtts_default_port_when_omitted(self):
        """mqtts://broker (no port) defaults to 8883."""
        from services.mqtt.client import parse_broker_url

        host, port, tls = parse_broker_url("mqtts://broker.example.com")
        assert host == "broker.example.com"
        assert port == 8883
        assert tls is True

    def test_with_path_raises(self):
        """mqtt://localhost:1883/extra raises ValueError."""
        from services.mqtt.client import parse_broker_url

        with pytest.raises(ValueError, match="path"):
            parse_broker_url("mqtt://localhost:1883/extra")

    def test_invalid_scheme_raises(self):
        """http://localhost raises ValueError."""
        from services.mqtt.client import parse_broker_url

        with pytest.raises(ValueError, match="scheme"):
            parse_broker_url("http://localhost")

    def test_empty_url_raises(self):
        """Empty string raises ValueError."""
        from services.mqtt.client import parse_broker_url

        with pytest.raises(ValueError):
            parse_broker_url("")

    def test_mqtt_scheme_only_raises(self):
        """Just 'mqtt://' raises ValueError (no host)."""
        from services.mqtt.client import parse_broker_url

        with pytest.raises(ValueError):
            parse_broker_url("mqtt://")


# ── connect_mqtt ─────────────────────────────────────────────────────────────


class TestConnectMqtt:
    """Async tests for connect_mqtt — uses a mocked aiomqtt.Client."""

    async def test_yields_client(self):
        """connect_mqtt yields a connected aiomqtt.Client (mocked)."""
        from config import MQTTSettings
        from services.mqtt.client import connect_mqtt

        mock_client = AsyncMock()

        @asynccontextmanager
        async def fake_client_ctx(*args, **kwargs):
            yield mock_client

        settings = MQTTSettings(
            broker_url="mqtt://broker.test:1883",
            username="user1",
            password="pw1",
            client_id="cid",
            qos=1,
        )

        with patch("services.mqtt.client.aiomqtt.Client", side_effect=fake_client_ctx):
            async with connect_mqtt(settings) as client:
                assert client is mock_client

    async def test_passes_host_and_port(self):
        """connect_mqtt forwards host/port parsed from broker_url to aiomqtt.Client."""
        from config import MQTTSettings
        from services.mqtt.client import connect_mqtt

        captured: dict = {}

        @asynccontextmanager
        async def fake_client_ctx(hostname, port, **_):
            captured["hostname"] = hostname
            captured["port"] = port
            yield AsyncMock()

        settings = MQTTSettings(broker_url="mqtt://broker.test:1883")

        with patch("services.mqtt.client.aiomqtt.Client", side_effect=fake_client_ctx):
            async with connect_mqtt(settings):
                pass

        assert captured["hostname"] == "broker.test"
        assert captured["port"] == 1883

    async def test_passes_credentials_when_present(self):
        """connect_mqtt forwards username/password when set on settings."""
        from config import MQTTSettings
        from services.mqtt.client import connect_mqtt

        captured: dict = {}

        @asynccontextmanager
        async def fake_client_ctx(*, username, password, identifier, **_):
            captured["username"] = username
            captured["password"] = password
            captured["identifier"] = identifier
            yield AsyncMock()

        settings = MQTTSettings(
            broker_url="mqtt://broker.test:1883",
            username="u",
            password="p",
            client_id="my-cid",
        )

        with patch("services.mqtt.client.aiomqtt.Client", side_effect=fake_client_ctx):
            async with connect_mqtt(settings):
                pass

        assert captured["username"] == "u"
        assert captured["password"] == "p"
        assert captured["identifier"] == "my-cid"

    async def test_passes_tls_context_for_mqtts(self):
        """connect_mqtt sets tls_context=True for mqtts:// URLs."""
        from config import MQTTSettings
        from services.mqtt.client import connect_mqtt

        captured: dict = {}

        @asynccontextmanager
        async def fake_client_ctx(*, tls_context, **_):
            captured["tls_context"] = tls_context
            yield AsyncMock()

        settings = MQTTSettings(broker_url="mqtts://secure.test:8883")

        with patch("services.mqtt.client.aiomqtt.Client", side_effect=fake_client_ctx):
            async with connect_mqtt(settings):
                pass

        # tls_context may be True (default context) or an ssl.SSLContext instance
        assert captured["tls_context"] is not None
        assert captured["tls_context"] is not False

    async def test_no_tls_for_mqtt(self):
        """connect_mqtt leaves tls_context as None (no TLS) for mqtt:// URLs."""
        from config import MQTTSettings
        from services.mqtt.client import connect_mqtt

        captured: dict = {}

        @asynccontextmanager
        async def fake_client_ctx(*, tls_context, **_):
            captured["tls_context"] = tls_context
            yield AsyncMock()

        settings = MQTTSettings(broker_url="mqtt://plain.test:1883")

        with patch("services.mqtt.client.aiomqtt.Client", side_effect=fake_client_ctx):
            async with connect_mqtt(settings):
                pass

        assert captured["tls_context"] is None

    async def test_propagates_client_errors(self):
        """If aiomqtt.Client raises during connection, the exception propagates."""
        from config import MQTTSettings
        from services.mqtt.client import connect_mqtt

        settings = MQTTSettings(broker_url="mqtt://broken.test:1883")

        @asynccontextmanager
        async def broken_ctx(*args, **kwargs):
            raise ConnectionError("broker unreachable")
            yield  # noqa: F841 — unreachable

        with (
            patch("services.mqtt.client.aiomqtt.Client", side_effect=broken_ctx),
            pytest.raises(ConnectionError, match="unreachable"),
        ):
            async with connect_mqtt(settings):
                pass
