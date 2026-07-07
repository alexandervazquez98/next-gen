"""Read-only MQTT raw telemetry API service."""

from __future__ import annotations

from typing import Any

from database import get_db
from models.mqtt import MQTT_RAW_CLASSIFICATION
from repositories.device_metric_repo import DeviceMetricRepo


class MqttRawReadingService:
    """Expose raw MQTT Device/Metric data as explicitly non-KPI telemetry."""

    def __init__(self, repo: DeviceMetricRepo | None = None):
        self._repo = repo if repo is not None else DeviceMetricRepo(get_db())

    @staticmethod
    def _mark_non_kpi(payload: dict[str, Any]) -> dict[str, Any]:
        if "device_id" not in payload and "id" in payload:
            payload["device_id"] = payload["id"]
        if "metric_id" not in payload and "id" in payload:
            payload["metric_id"] = payload["id"]
        payload["classification"] = MQTT_RAW_CLASSIFICATION
        payload["kpi_eligible"] = False
        return payload

    def list_devices(self) -> list[dict[str, Any]]:
        return [self._mark_non_kpi(dict(device)) for device in self._repo.list_devices()]

    def list_device_metrics(self, device_id: str) -> list[dict[str, Any]]:
        metrics = self._repo.list_metrics_with_mapping_status(device_id)
        return [self._mark_non_kpi(dict(metric)) for metric in metrics]

    def list_latest_readings(self, limit: int = 100) -> list[dict[str, Any]]:
        readings = self._repo.list_latest_readings(limit=limit)
        return [self._mark_non_kpi(dict(reading)) for reading in readings]


_raw_reading_service: MqttRawReadingService | None = None


def get_mqtt_raw_reading_service() -> MqttRawReadingService:
    global _raw_reading_service
    if _raw_reading_service is None:
        _raw_reading_service = MqttRawReadingService()
    return _raw_reading_service
