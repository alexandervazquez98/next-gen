"""RTU/Sensor Pydantic models for telemetry infrastructure.

These models cover:
- RTU node CRUD (RTUCreate, RTUUpdate, RTUResponse)
- Sensor node CRUD (SensorCreate, SensorUpdate, SensorResponse)
- MQTT telemetry payload (TelemetryMessage, TelemetrySensor)
"""

from datetime import datetime
from typing import Dict, List, Literal, Optional
from uuid import UUID

import ipaddress
from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# RTU Models
# ─────────────────────────────────────────────────────────────────────────────


class RTUBase(BaseModel):
    """Base RTU fields shared across create/update operations."""

    name: str = Field(..., min_length=1, max_length=255, description="Human-readable RTU name")
    ip: Optional[str] = Field(None, max_length=45, description="Device IP address (IPv4 or IPv6)")
    location_id: UUID = Field(..., description="FK to parent Location node")
    mqtt_config: Optional[Dict] = Field(None, description="JSON object with broker host/port/TLS config")

    @field_validator("ip")
    @classmethod
    def validate_ip(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                ipaddress.ip_address(v)
            except ValueError:
                raise ValueError(f"Invalid IP address: {v}")
        return v


class RTUCreate(RTUBase):
    """Payload for creating a new RTU node."""

    pass  # All fields inherited from RTUBase; mqtt_topic is computed on creation


class RTUUpdate(BaseModel):
    """Payload for updating an existing RTU."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    ip: Optional[str] = Field(None, max_length=45)
    status: Optional[Literal["online", "offline", "unknown"]] = Field(
        None,
        description="Operational state: online, offline, unknown",
    )
    mqtt_config: Optional[Dict] = None

    @field_validator("ip")
    @classmethod
    def validate_ip(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                ipaddress.ip_address(v)
            except ValueError:
                raise ValueError(f"Invalid IP address: {v}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in {"online", "offline", "unknown"}:
            raise ValueError(f"status must be one of: online, offline, unknown; got '{v}'")
        return v


class RTUResponse(BaseModel):
    """Full RTU node representation (as returned by API)."""

    id: UUID
    name: str
    ip: Optional[str] = None
    layer: str = Field(default="RTU", description="CI subtype discriminator — always 'RTU'")
    status: Literal["online", "offline", "unknown"] = Field(default="unknown")
    location_id: UUID
    mqtt_topic: str = Field(..., description="Full MQTT topic: rtu/{location_id}/{rtu_id}/telemetry")
    mqtt_config: Optional[Dict] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────────────────────────────────────
# Sensor Models
# ─────────────────────────────────────────────────────────────────────────────


class SensorBase(BaseModel):
    """Base sensor fields shared across create/update operations."""

    name: str = Field(..., min_length=1, max_length=255, description="Human-readable sensor name")
    register_addr: int = Field(..., ge=0, le=319, description="Modbus register address (0-based, 0-319)")
    register_count: int = Field(default=1, ge=1, le=4, description="Number of registers consumed (1-4)")
    unit: Optional[str] = Field(None, max_length=32, description="Unit of measurement (e.g., '°C', '%RH')")
    sensor_type: str = Field(
        ...,
        description="Sensor classification: temperature, humidity, analog_input, relay, digital_input",
    )

    @field_validator("register_addr")
    @classmethod
    def validate_register_addr(cls, v: int) -> int:
        if v < 0 or v > 319:
            raise ValueError(f"register_addr must be between 0 and 319, got {v}")
        return v

    @field_validator("register_count")
    @classmethod
    def validate_register_count(cls, v: int) -> int:
        if v < 1 or v > 4:
            raise ValueError(f"register_count must be between 1 and 4, got {v}")
        return v


class SensorCreate(SensorBase):
    """Payload for creating a new Sensor node."""

    pass  # All fields from SensorBase


class SensorUpdate(BaseModel):
    """Payload for updating an existing Sensor."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    unit: Optional[str] = Field(None, max_length=32)


class SensorResponse(BaseModel):
    """Full Sensor node representation (as returned by API)."""

    id: UUID
    name: str
    register_addr: int
    register_count: int
    unit: Optional[str] = None
    sensor_type: str
    rtu_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────────────────────────────────────
# MQTT Telemetry Payload Models
# ─────────────────────────────────────────────────────────────────────────────


class TelemetrySensor(BaseModel):
    """A single sensor reading from the MQTT telemetry payload."""

    register_addr: int = Field(..., ge=0, le=319, description="Modbus register address (0-319)")
    value: int = Field(..., description="Raw register value")
    unit: Optional[str] = Field(None, description="Unit string from device")


class TelemetryMessage(BaseModel):
    """Root MQTT payload for RTU telemetry messages.

    Topic structure: rtu/{location_id}/{rtu_id}/telemetry

    Example payload:
        {
          "timestamp": "2026-05-04T12:00:00Z",
          "sensors": [{"register_addr": 0, "value": 2375, "unit": "0.01°C"}],
          "digital_inputs": [1, 0, 1, 0, 0, 0, 0, 0],
          "relays": [0, 0, 0, 0]
        }
    """

    timestamp: Optional[str] = Field(None, description="ISO 8601 event timestamp; defaults to server receive time")
    sensors: List[TelemetrySensor] = Field(..., min_length=1, description="Array of 1-16 sensor readings")
    digital_inputs: Optional[List[int]] = Field(
        None,
        description="Array of 8 bits (DI1-DI8), values 0 or 1",
    )
    relays: Optional[List[int]] = Field(None, description="Array of 4 relay states, values 0 or 1")

    @field_validator("sensors")
    @classmethod
    def validate_sensors_not_empty(cls, v: List[TelemetrySensor]) -> List[TelemetrySensor]:
        if len(v) == 0:
            raise ValueError("sensors array must contain at least 1 reading")
        if len(v) > 16:
            raise ValueError("sensors array must not exceed 16 readings")
        return v


# ─────────────────────────────────────────────────────────────────────────────
# SensorType Enum (reference for valid values)
# ─────────────────────────────────────────────────────────────────────────────

SENSOR_TYPES = frozenset({
    "temperature",
    "humidity",
    "analog_input",
    "relay",
    "digital_input",
})