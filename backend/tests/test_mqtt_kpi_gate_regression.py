"""Regression tests ensuring KPI writes stay strictly approved-only."""

from __future__ import annotations

from datetime import UTC, datetime

from services.mqtt.parsers.base import MetricReading, Reading
from services.mqtt_bridge_service import (
    MQTT_MAPPING_AMBIGUOUS_OUTCOME,
    MQTT_MAPPING_APPROVED_OUTCOME,
    MQTT_MAPPING_DRAFT_OUTCOME,
    MQTT_MAPPING_REVOKED_OUTCOME,
    MqttBridgeService,
)


class _MappingRepo:
    def __init__(self, mappings_by_call):
        self.calls = 0
        self._mappings_by_call = mappings_by_call

    def list_approved_mappings_for_source(self, source_device_id: str, source_metric_id: str):
        mapping = self._mappings_by_call[self.calls]
        self.calls += 1
        return mapping


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

    def mark_timescale_written(self, idempotency_key: str, **payload):
        self.records[idempotency_key].update(payload)
        return self.records[idempotency_key]

    def mark_event_written(self, idempotency_key: str, **payload):
        self.records[idempotency_key].update(payload)
        return self.records[idempotency_key]

    def mark_event_failed(self, idempotency_key: str, **payload):
        self.records[idempotency_key].update(payload)
        return self.records[idempotency_key]

    def mark_failed(self, idempotency_key: str, **payload):
        self.records[idempotency_key].update(payload)
        return self.records[idempotency_key]


class _StatusService:
    def __init__(self):
        self.calls = []

    def record_bridge_outcome(self, outcome: str, **kwargs) -> None:
        self.calls.append(outcome)


def _reading(value: float) -> Reading:
    return Reading(
        device_id="rtu-1",
        location_id="loc-1",
        timestamp=datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC),
        metrics=(MetricReading(name="temperature", value=value, unit="C"),),
        source_topic="rtu/loc-1/rtu-1/telemetry",
        parser_name="bliiot",
    )


def test_kpi_bridge_is_approved_only() -> None:
    metric_calls = []

    class _MetricRepo:
        def __call__(self, node_id, metric_id, value, observed_at):
            raise AssertionError("Unapproved mappings must not reach Timescale")

    mapping_repo = _MappingRepo(
        mappings_by_call=[
            [
                {
                    "id": "map-1",
                    "source_device_id": "rtu-1",
                    "source_metric_id": "rtu-1/temperature",
                    "source_metric_name": "temperature",
                    "target_ci_id": "ci-1",
                    "target_metric_def_id": "temperature",
                    "operator": ">=",
                    "warning": 70,
                    "critical": 90,
                    "status": "DRAFT",
                }
            ],
            [
                {
                    "id": "map-1",
                    "source_device_id": "rtu-1",
                    "source_metric_id": "rtu-1/temperature",
                    "source_metric_name": "temperature",
                    "target_ci_id": "ci-1",
                    "target_metric_def_id": "temperature",
                    "operator": ">=",
                    "warning": 70,
                    "critical": 90,
                    "status": "REVOKED",
                }
            ],
            [
                {
                    "id": "map-1",
                    "source_device_id": "rtu-1",
                    "source_metric_id": "rtu-1/temperature",
                    "source_metric_name": "temperature",
                    "target_ci_id": "ci-1",
                    "target_metric_def_id": "temperature",
                    "operator": ">=",
                    "warning": 70,
                    "critical": 90,
                    "status": "APPROVED",
                },
                {
                    "id": "map-2",
                    "source_device_id": "rtu-1",
                    "source_metric_id": "rtu-1/temperature",
                    "source_metric_name": "temperature",
                    "target_ci_id": "ci-2",
                    "target_metric_def_id": "temperature",
                    "operator": ">=",
                    "warning": 70,
                    "critical": 90,
                    "status": "APPROVED",
                },
            ],
        ]
    )

    service = MqttBridgeService(
        mapping_repo=mapping_repo,
        receipt_repo=_ReceiptRepo(),
        metric_writer=lambda *_args: metric_calls.append(_args),
        event_writer=lambda *_args, **_kwargs: None,
        runtime_status_service=_StatusService(),
        event_writer_driver=object(),
    )

    results = [
        service.process_reading(_reading(55.0)),
        service.process_reading(_reading(56.0)),
        service.process_reading(_reading(57.0)),
    ]

    outcomes = [result[0]["outcome"] for result in results]
    assert outcomes == [
        MQTT_MAPPING_DRAFT_OUTCOME,
        MQTT_MAPPING_REVOKED_OUTCOME,
        MQTT_MAPPING_AMBIGUOUS_OUTCOME,
    ]
    assert metric_calls == []


def test_approved_mapping_still_writes_kpi_path() -> None:
    status = _StatusService()
    metric_calls = []

    class _MetricRepo:
        def __call__(self, node_id, metric_id, value, observed_at):
            metric_calls.append((node_id, metric_id, value))

    mapping_repo = _MappingRepo(
        mappings_by_call=[
            [
                {
                    "id": "map-1",
                    "source_device_id": "rtu-1",
                    "source_metric_id": "rtu-1/temperature",
                    "source_metric_name": "temperature",
                    "target_ci_id": "ci-1",
                    "target_metric_def_id": "temperature",
                    "operator": ">=",
                    "warning": 70,
                    "critical": 90,
                    "status": "APPROVED",
                }
            ]
        ]
    )

    service = MqttBridgeService(
        mapping_repo=mapping_repo,
        receipt_repo=_ReceiptRepo(),
        metric_writer=_MetricRepo(),
        event_writer=lambda *_args, **_kwargs: None,
        runtime_status_service=status,
        event_writer_driver=object(),
    )

    result = service.process_reading(_reading(61.0))

    assert result[0]["outcome"] == MQTT_MAPPING_APPROVED_OUTCOME
    assert metric_calls == [("ci-1", "temperature", 61.0)]
