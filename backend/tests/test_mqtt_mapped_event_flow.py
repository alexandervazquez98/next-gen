"""Regression tests for event metadata propagation in MQTT KPI bridge path."""

from __future__ import annotations

from datetime import UTC, datetime

from services.mqtt.parsers.base import MetricReading, Reading
from services.mqtt_bridge_service import (
    MQTT_MAPPING_APPROVED_OUTCOME,
    MqttBridgeService,
)


class _EventWriter:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, neo4j_driver, payload):
        self.calls.append((neo4j_driver, payload))


class _MappingRepo:
    def __init__(self, mapping_over_time: list[dict[str, object]]):
        self._mapping_over_time = mapping_over_time
        self.calls = 0

    def list_approved_mappings_for_source(self, source_device_id: str, source_metric_id: str):
        mapping = self._mapping_over_time[min(self.calls, len(self._mapping_over_time) - 1)]
        self.calls += 1
        return [mapping]


class _ReceiptRepo:
    def __init__(self) -> None:
        self.records = {}

    def get_receipt(self, idempotency_key: str):
        return self.records.get(idempotency_key)

    def create_receipt(self, **payload):
        self.records[payload["idempotency_key"]] = {
            **payload,
            "status": payload["status"],
            "timescale_written_at": None,
            "event_written_at": None,
            "last_error": None,
        }
        return self.records[payload["idempotency_key"]]

    def update_receipt_status(self, idempotency_key: str, **payload):
        self.records[idempotency_key].update(payload)
        return self.records[idempotency_key]


class _MetricRepo:
    def insert_metric_value(self, node_id, metric_id, value, observed_at):
        return {"node_id": node_id, "metric_id": metric_id}


class _StatusService:
    def record_bridge_outcome(self, outcome: str, **kwargs) -> None:
        pass


def _reading(value: float, at: datetime) -> Reading:
    return Reading(
        device_id="rtu-1",
        location_id="loc-1",
        timestamp=at,
        metrics=(MetricReading(name="temperature", value=value, unit="C"),),
        source_topic="rtu/loc-1/rtu-1/telemetry",
        parser_name="bliiot",
    )


def test_event_metadata_uses_current_thresholds_from_mapping() -> None:
    mapping_v1 = {
        "id": "map-1",
        "source_device_id": "rtu-1",
        "source_metric_id": "rtu-1/temperature",
        "source_metric_name": "temperature",
        "target_ci_id": "ci-1",
        "target_metric_def_id": "temperature",
        "operator": ">=",
        "warning": 80,
        "critical": 95,
        "status": "APPROVED",
    }
    mapping_v2 = {
        **mapping_v1,
        "warning": 50,
        "critical": 75,
    }

    event_writer = _EventWriter()
    service = MqttBridgeService(
        mapping_repo=_MappingRepo([mapping_v1, mapping_v2]),
        receipt_repo=_ReceiptRepo(),
        metric_writer=_MetricRepo().insert_metric_value,
        event_writer=event_writer,
        runtime_status_service=_StatusService(),
        event_writer_driver=object(),
    )

    first_ts = datetime(2026, 8, 1, 12, 34, 56, tzinfo=UTC)
    second_ts = datetime(2026, 8, 1, 12, 34, 57, tzinfo=UTC)

    first = service.process_reading(_reading(20.0, first_ts))
    second = service.process_reading(_reading(21.0, second_ts))

    assert first[0]["outcome"] == MQTT_MAPPING_APPROVED_OUTCOME
    assert second[0]["outcome"] == MQTT_MAPPING_APPROVED_OUTCOME
    assert len(event_writer.calls) == 2
    first_payload = event_writer.calls[0][1][0]
    second_payload = event_writer.calls[1][1][0]

    assert first_payload["metadata"]["warning"] == 80
    assert first_payload["metadata"]["critical"] == 95
    assert second_payload["metadata"]["warning"] == 50
    assert second_payload["metadata"]["critical"] == 75
    assert first_payload["metadata"]["source_metric_name"] == "temperature"
    assert second_payload["metadata"]["source_metric_name"] == "temperature"


def test_event_payload_keeps_protocol_and_observation_time() -> None:
    event_writer = _EventWriter()
    service = MqttBridgeService(
        mapping_repo=_MappingRepo(
            [
                {
                    "id": "map-1",
                    "source_device_id": "rtu-1",
                    "source_metric_id": "rtu-1/temperature",
                    "source_metric_name": "temperature",
                    "target_ci_id": "ci-1",
                    "target_metric_def_id": "temperature",
                    "operator": "<",
                    "warning": 40,
                    "critical": 60,
                    "status": "APPROVED",
                }
            ]
        ),
        receipt_repo=_ReceiptRepo(),
        metric_writer=_MetricRepo().insert_metric_value,
        event_writer=event_writer,
        runtime_status_service=_StatusService(),
        event_writer_driver=object(),
    )

    observed_at = datetime(2026, 8, 1, 13, 0, 0, tzinfo=UTC)

    result = service.process_reading(_reading(39.0, observed_at))

    payload = event_writer.calls[0][1][0]
    assert payload["observed_at"] == observed_at.isoformat()
    assert payload["protocol"] == "MQTT"
    assert payload["source_protocol"] == "MQTT"
    assert payload["metadata"]["operator"] == "<"
    assert payload["idempotency_key"].startswith("mqtt:")
    assert result[0]["mapping_id"] == "map-1"
