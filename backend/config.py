# backend/config.py
"""Application configuration — centralized settings loaded from environment.

This module provides Pydantic BaseSettings for type-safe env var access.
Currently covers MQTT configuration. Expand as needed for other subsystems.
"""

from __future__ import annotations

import os
from typing import Optional
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Event Batch Pruner Settings
# ---------------------------------------------------------------------------


class EventBatchSettings(BaseModel):
    """Batch processing settings for the event batch pruner."""

    batch_size: int = 500
    batch_delay_ms: int = 100
    batch_timeout_s: int = 30

    @classmethod
    def from_env(cls) -> "EventBatchSettings":
        """Load event batch settings from environment variables."""
        return cls(
            batch_size=int(os.getenv("EVENT_BATCH_SIZE", "500")),
            batch_delay_ms=int(os.getenv("EVENT_BATCH_DELAY_MS", "100")),
            batch_timeout_s=int(os.getenv("EVENT_BATCH_TIMEOUT_S", "30")),
        )


_event_batch_settings: Optional[EventBatchSettings] = None


def get_event_batch_settings() -> EventBatchSettings:
    """Return cached event batch settings (singleton)."""
    global _event_batch_settings
    if _event_batch_settings is None:
        _event_batch_settings = EventBatchSettings.from_env()
    return _event_batch_settings


# ---------------------------------------------------------------------------
# MQTT Settings
# ---------------------------------------------------------------------------


class MQTTSettings(BaseModel):
    """MQTT broker connection settings."""

    broker_url: str = "mqtt://localhost:1883"
    username: Optional[str] = None
    password: Optional[str] = None
    client_id: str = "rtu-telemetry-subscriber"
    wildcard_topic: str = "rtu/+/+/telemetry"
    qos: int = 1

    @classmethod
    def from_env(cls) -> "MQTTSettings":
        """Load MQTT settings from environment variables."""
        return cls(
            broker_url=os.getenv("MQTT_BROKER_URL", "mqtt://localhost:1883"),
            username=os.getenv("MQTT_USERNAME"),
            password=os.getenv("MQTT_PASSWORD"),
            client_id=os.getenv("MQTT_CLIENT_ID", "rtu-telemetry-subscriber"),
            wildcard_topic=os.getenv("MQTT_WILDCARD_TOPIC", "rtu/+/+/telemetry"),
            qos=int(os.getenv("MQTT_QOS", "1")),
        )


# Singleton instance (lazy-loaded)
_mqtt_settings: Optional[MQTTSettings] = None


def get_mqtt_settings() -> MQTTSettings:
    """Return cached MQTT settings (singleton)."""
    global _mqtt_settings
    if _mqtt_settings is None:
        _mqtt_settings = MQTTSettings.from_env()
    return _mqtt_settings
