"""API models for MQTT raw telemetry and monitoring mappings."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

MQTT_RAW_CLASSIFICATION = "RAW_MQTT_NON_KPI"
MAPPING_STATUSES = {"UNMAPPED", "DRAFT", "APPROVED", "REVOKED"}
MAPPING_LIFECYCLE_STATUSES = {"DRAFT", "APPROVED", "REVOKED"}
THRESHOLD_OPERATORS = {">", ">=", "<", "<=", "==", "!="}


class MqttRawDeviceResponse(BaseModel):
    device_id: str
    name: str | None = None
    location_id: str | None = None
    source_topic: str | None = None
    parser_name: str | None = None
    last_seen: str | None = None
    classification: str = MQTT_RAW_CLASSIFICATION
    kpi_eligible: bool = False
    mapped_metrics_count: int = 0
    unmapped_metrics_count: int = 0


class MqttRawMetricResponse(BaseModel):
    device_id: str
    metric_id: str
    name: str | None = None
    last_value: float | int | str | bool | None = None
    unit: str | None = None
    last_ts: str | None = None
    classification: str = MQTT_RAW_CLASSIFICATION
    kpi_eligible: bool = False
    mapping_status: str = "UNMAPPED"

    @field_validator("mapping_status")
    @classmethod
    def validate_mapping_status(cls, value: str) -> str:
        if value not in MAPPING_STATUSES:
            raise ValueError(f"Unsupported MQTT mapping status: {value}")
        return value


class MqttMappingThresholds(BaseModel):
    operator: str | None = Field(default=None)
    warning: float | None = None
    critical: float | None = None

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, value: str | None) -> str | None:
        if value is not None and value not in THRESHOLD_OPERATORS:
            raise ValueError(f"Unsupported threshold operator: {value}")
        return value


class MqttMappingCreateRequest(BaseModel):
    source_device_id: str
    source_metric_id: str
    source_metric_name: str
    target_ci_id: str
    target_metric_def_id: str
    thresholds: MqttMappingThresholds | None = None


class MqttMappingUpdateRequest(BaseModel):
    source_metric_name: str | None = None
    target_ci_id: str | None = None
    target_metric_def_id: str | None = None
    thresholds: MqttMappingThresholds | None = None


class MqttMappingResponse(BaseModel):
    id: str
    source_device_id: str | None = None
    source_metric_id: str | None = None
    source_metric_name: str | None = None
    target_ci_id: str | None = None
    target_metric_def_id: str | None = None
    status: str
    version: int | None = None
    warning: float | None = None
    critical: float | None = None
    operator: str | None = None
    created_by: str | None = None
    approved_by: str | None = None
    revoked_by: str | None = None
    created_at: str | None = None
    approved_at: str | None = None
    revoked_at: str | None = None
    updated_at: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in MAPPING_LIFECYCLE_STATUSES:
            raise ValueError(f"Unsupported MQTT mapping lifecycle status: {value}")
        return value
