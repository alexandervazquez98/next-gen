"""Unit tests for MQTT mapping bridge processing and idempotent KPI/event semantics.

RED phase first: these tests define the bridge gating, idempotency, and
partial-failure behavior before implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from services.mqtt.parsers.base import MetricReading, Reading
from services.mqtt_bridge_service import (
    MQTT_MAPPING_AMBIGUOUS_OUTCOME,
    MQTT_MAPPING_APPROVED_OUTCOME,
    MQTT_MAPPING_DRAFT_OUTCOME,
    MQTT_MAPPING_DUPLICATE_OUTCOME,
    MQTT_MAPPING_EVENT_PENDING_OUTCOME,
    MQTT_MAPPING_EVENT_RETRY_SUCCESS_OUTCOME,
    MQTT_MAPPING_NON_NUMERIC_OUTCOME,
    MQTT_MAPPING_REVOKED_OUTCOME,
    MQTT_MAPPING_UNMAPPED_OUTCOME,
    MqttBridgeService,
    _DefaultRuntimeStatusService,
)
from sqlalchemy.exc import IntegrityError


@dataclass
class _Mapping:
    source_device_id: str
    source_metric_id: str
    source_metric_name: str
    target_ci_id: str
    target_metric_def_id: str
    operator: str
    warning: float
    critical: float
    status: str


class _MappingRepo:
    def __init__(self, mappings: list[_Mapping]):
        self._mappings = mappings
        self.calls: list[tuple[str, str]] = []

    def list_mappings_for_source(
        self, source_device_id: str, source_metric_id: str
    ) -> list[dict[str, Any]]:
        self.calls.append((source_device_id, source_metric_id))
        return [
            {
                "id": f"map-{i + 1}",
                "source_device_id": mapping.source_device_id,
                "source_metric_id": mapping.source_metric_id,
                "source_metric_name": mapping.source_metric_name,
                "target_ci_id": mapping.target_ci_id,
                "target_metric_def_id": mapping.target_metric_def_id,
                "operator": mapping.operator,
                "warning": mapping.warning,
                "critical": mapping.critical,
                "status": mapping.status,
            }
            for i, mapping in enumerate(self._mappings)
            if mapping.source_device_id == source_device_id
            and mapping.source_metric_id == source_metric_id
        ]

    # Backward-compatible method name used by older service versions.
    def list_approved_mappings_for_source(self, source_device_id: str, source_metric_id: str):
        return self.list_mappings_for_source(source_device_id, source_metric_id)


class _MetricRepo:
    def __init__(self):
        self.calls: list[tuple[str, str, float, datetime]] = []

    def insert_metric_value(
        self, node_id: str, metric_id: str, value: float, observed_at: datetime
    ) -> dict[str, Any]:
        self.calls.append((node_id, metric_id, value, observed_at))
        return {
            "node_id": node_id,
            "metric_id": metric_id,
            "value": value,
        }


class _FailingMetricWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float, datetime]] = []

    def __call__(self, node_id: str, metric_id: str, value: float, observed_at: datetime) -> None:
        self.calls.append((node_id, metric_id, value, observed_at))
        if len(self.calls) == 1:
            raise IntegrityError("duplicate sample", None, None)


class _EventWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, list[dict[str, Any]], dict[str, Any] | None]] = []
        self.should_fail_first = False

    def __call__(
        self,
        neo4j_driver: Any,
        payload: list[dict[str, Any]],
        **kwargs: Any,
    ) -> None:
        lock_db = kwargs.get("lock_db")
        self.calls.append((neo4j_driver, payload, {"lock_db": lock_db}))
        if self.should_fail_first:
            self.should_fail_first = False
            raise RuntimeError("event write failed")


class _StatusService:
    def __init__(self):
        self.outcomes: list[str] = []

    def record_bridge_outcome(self, outcome: str, **kwargs) -> None:
        self.outcomes.append(outcome)


class _StatusCounterService(_StatusService):
    def __init__(self) -> None:
        super().__init__()
        self.counters: list[str] = []

    def increment_counter(self, counter: str, delta: int = 1) -> None:
        self.counters.append(counter)


class _ReceiptRepo:
    def __init__(self):
        self.records: dict[str, dict[str, Any]] = {}

    def get_receipt(self, idempotency_key: str) -> dict[str, Any] | None:
        return self.records.get(idempotency_key)

    def create_receipt(
        self,
        *,
        idempotency_key: str,
        mapping_id: str,
        source_device_id: str,
        source_metric_id: str,
        observed_at: datetime,
        value_hash: str,
        status: str,
    ) -> dict[str, Any]:
        record = {
            "idempotency_key": idempotency_key,
            "mapping_id": mapping_id,
            "source_device_id": source_device_id,
            "source_metric_id": source_metric_id,
            "observed_at": observed_at,
            "value_hash": value_hash,
            "status": status,
            "timescale_written_at": None,
            "event_written_at": None,
            "last_error": None,
        }
        self.records[idempotency_key] = record
        return record

    def create_or_update_receipt(self, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self.records.get(payload["idempotency_key"])
        if existing is None:
            return self.create_receipt(
                idempotency_key=payload["idempotency_key"],
                mapping_id=payload["mapping_id"],
                source_device_id=payload["source_device_id"],
                source_metric_id=payload["source_metric_id"],
                observed_at=payload["observed_at"],
                value_hash=payload["value_hash"],
                status=payload.get("status", MQTT_MAPPING_UNMAPPED_OUTCOME),
            )
        existing.update(payload)
        return existing

    def update_receipt_status(
        self,
        idempotency_key: str,
        *,
        status: str | None = None,
        timescale_written_at: datetime | None = None,
        event_written_at: datetime | None = None,
        last_error: str | None = None,
    ) -> dict[str, Any]:
        record = self.records[idempotency_key]
        if status is not None:
            record["status"] = status
        if timescale_written_at is not None:
            record["timescale_written_at"] = timescale_written_at
        if event_written_at is not None:
            record["event_written_at"] = event_written_at
        if last_error is not None:
            record["last_error"] = last_error
        return record

    def mark_timescale_written(self, idempotency_key: str, *, status: str, now: datetime):
        return self.update_receipt_status(
            idempotency_key,
            status=status,
            timescale_written_at=now,
            last_error=None,
        )

    def mark_event_written(self, idempotency_key: str, *, status: str, now: datetime):
        return self.update_receipt_status(
            idempotency_key,
            status=status,
            event_written_at=now,
            last_error=None,
        )

    def mark_event_failed(self, idempotency_key: str, *, status: str, error: str, now: datetime):
        return self.update_receipt_status(
            idempotency_key,
            status=status,
            event_written_at=None,
            last_error=error,
        )

    def mark_failed(self, idempotency_key: str, *, status: str, error: str, now: datetime):
        return self.update_receipt_status(
            idempotency_key,
            status=status,
            last_error=error,
        )


class _FailingTimescaleMarkReceiptRepo(_ReceiptRepo):
    def __init__(self) -> None:
        super().__init__()
        self.timescale_written_calls = 0

    def mark_timescale_written(self, idempotency_key: str, *, status: str, now: datetime):
        self.timescale_written_calls += 1
        if self.timescale_written_calls == 1:
            raise RuntimeError("timescale state update failed")
        return super().mark_timescale_written(idempotency_key, status=status, now=now)


class _FailingEventMarkReceiptRepo(_ReceiptRepo):
    def __init__(self) -> None:
        super().__init__()
        self.event_written_calls = 0

    def mark_event_written(self, idempotency_key: str, *, status: str, now: datetime):
        self.event_written_calls += 1
        if self.event_written_calls == 1:
            raise RuntimeError("event state update failed")
        return super().mark_event_written(idempotency_key, status=status, now=now)


class _IdempotentEventWriter:
    def __init__(self) -> None:
        self.calls = []
        self.seen = set[tuple[str, Any]]()

    def __call__(
        self,
        neo4j_driver: Any,
        payload: list[dict[str, Any]],
        **kwargs: Any,
    ) -> None:
        row = payload[0]
        self.calls.append((neo4j_driver, payload, kwargs))
        if ("idempotency_key", row["idempotency_key"]) in self.seen:
            return
        self.seen.add(("idempotency_key", row["idempotency_key"]))


FIXED_TS = datetime(2026, 8, 1, 12, 34, 56, tzinfo=UTC)


def _reading(value: float = 12.5) -> Reading:
    return Reading(
        device_id="rtu-1",
        location_id="loc-1",
        timestamp=FIXED_TS,
        metrics=(MetricReading(name="temperature", value=value, unit="C"),),
        source_topic="rtu/loc-1/rtu-1/telemetry",
        parser_name="bliiot",
    )


def _approved_mapping() -> _Mapping:
    return _Mapping(
        source_device_id="rtu-1",
        source_metric_id="rtu-1/temperature",
        source_metric_name="temperature",
        target_ci_id="ci-1",
        target_metric_def_id="temperature",
        operator=">=",
        warning=70,
        critical=90,
        status="APPROVED",
    )


@pytest.mark.parametrize(
    "mappings,outcome",
    [
        ([], MQTT_MAPPING_UNMAPPED_OUTCOME),
        (
            [
                _Mapping(
                    "rtu-1",
                    "rtu-1/temperature",
                    "temperature",
                    "ci-1",
                    "temp",
                    ">=",
                    70,
                    90,
                    "DRAFT",
                )
            ],
            MQTT_MAPPING_DRAFT_OUTCOME,
        ),
        (
            [
                _Mapping(
                    "rtu-1",
                    "rtu-1/temperature",
                    "temperature",
                    "ci-1",
                    "temp",
                    ">=",
                    70,
                    90,
                    "REVOKED",
                )
            ],
            MQTT_MAPPING_REVOKED_OUTCOME,
        ),
        (
            [
                _Mapping(
                    "rtu-1",
                    "rtu-1/temperature",
                    "temperature",
                    "ci-1",
                    "temp",
                    ">=",
                    70,
                    90,
                    "APPROVED",
                ),
                _Mapping(
                    "rtu-1",
                    "rtu-1/temperature",
                    "temperature",
                    "ci-2",
                    "temp",
                    ">=",
                    70,
                    90,
                    "APPROVED",
                ),
            ],
            MQTT_MAPPING_AMBIGUOUS_OUTCOME,
        ),
    ],
)
def test_blocked_mapping_states_do_not_write_kpi_data(
    mappings: list[_Mapping], outcome: str
) -> None:
    metric_repo = _MetricRepo()
    event_writer = _EventWriter()
    receipt_repo = _ReceiptRepo()
    status_service = _StatusService()
    mapping_repo = _MappingRepo(mappings)
    service = MqttBridgeService(
        mapping_repo=mapping_repo,
        receipt_repo=receipt_repo,
        metric_writer=metric_repo.insert_metric_value,
        event_writer=event_writer,
        runtime_status_service=status_service,
        event_writer_driver=object(),
    )

    result = service.process_reading(_reading())

    assert mapping_repo.calls == [("rtu-1", "rtu-1/temperature")]
    assert result[0]["outcome"] == outcome
    assert metric_repo.calls == []
    assert event_writer.calls == []
    assert status_service.outcomes[-1] == outcome


def test_non_numeric_metric_reading_is_skipped() -> None:
    metric_repo = _MetricRepo()
    event_writer = _EventWriter()
    mapping_repo = _MappingRepo([_approved_mapping()])
    receipt_repo = _ReceiptRepo()
    status_service = _StatusService()
    service = MqttBridgeService(
        mapping_repo=mapping_repo,
        receipt_repo=receipt_repo,
        metric_writer=metric_repo.insert_metric_value,
        event_writer=event_writer,
        runtime_status_service=status_service,
        event_writer_driver=object(),
    )

    reading = Reading(
        device_id="rtu-1",
        location_id="loc-1",
        timestamp=FIXED_TS,
        metrics=(MetricReading(name="temperature", value="25C", unit="C"),),
        source_topic="rtu/loc-1/rtu-1/telemetry",
        parser_name="bliiot",
    )

    result = service.process_reading(reading)

    assert result[0]["outcome"] == MQTT_MAPPING_NON_NUMERIC_OUTCOME
    assert metric_repo.calls == []
    assert event_writer.calls == []


def test_approved_mapping_writes_metric_then_event_with_mapping_thresholds() -> None:
    metric_repo = _MetricRepo()
    event_writer = _EventWriter()
    mapping_repo = _MappingRepo([_approved_mapping()])
    receipt_repo = _ReceiptRepo()
    status_service = _StatusService()
    service = MqttBridgeService(
        mapping_repo=mapping_repo,
        receipt_repo=receipt_repo,
        metric_writer=metric_repo.insert_metric_value,
        event_writer=event_writer,
        runtime_status_service=status_service,
        event_writer_driver=object(),
    )

    result = service.process_reading(_reading(value=12.5))

    assert result[0]["outcome"] == MQTT_MAPPING_APPROVED_OUTCOME
    assert len(metric_repo.calls) == 1
    assert metric_repo.calls[0] == ("ci-1", "temperature", 12.5, FIXED_TS)
    assert len(event_writer.calls) == 1
    payload = event_writer.calls[0][1][0]
    assert payload["protocol"] == "MQTT"
    assert payload["source_protocol"] == "MQTT"
    assert payload["ci_id"] == "ci-1"
    assert payload["metric_id"] == "temperature"
    assert payload["value"] == {"numeric": 12.5}
    assert payload["metadata"]["operator"] == ">="
    assert payload["metadata"]["warning"] == 70
    assert payload["metadata"]["critical"] == 90
    assert payload["metadata"]["source_metric_id"] == "rtu-1/temperature"
    assert payload["idempotency_key"].startswith("mqtt:")
    assert status_service.outcomes[-1] == MQTT_MAPPING_APPROVED_OUTCOME


def test_duplicate_payload_is_skipped_after_successful_complete_receipt() -> None:
    metric_repo = _MetricRepo()
    event_writer = _EventWriter()
    mapping_repo = _MappingRepo([_approved_mapping()])
    receipt_repo = _ReceiptRepo()
    status_service = _StatusService()
    service = MqttBridgeService(
        mapping_repo=mapping_repo,
        receipt_repo=receipt_repo,
        metric_writer=metric_repo.insert_metric_value,
        event_writer=event_writer,
        runtime_status_service=status_service,
        event_writer_driver=object(),
    )

    first = service.process_reading(_reading(value=18.0))
    second = service.process_reading(_reading(value=18.0))

    assert first[0]["outcome"] == MQTT_MAPPING_APPROVED_OUTCOME
    assert second[0]["outcome"] == MQTT_MAPPING_DUPLICATE_OUTCOME
    assert len(metric_repo.calls) == 1
    assert len(event_writer.calls) == 1
    assert status_service.outcomes[-1] == MQTT_MAPPING_DUPLICATE_OUTCOME


def test_duplicate_metric_insert_retries_event_only_without_rewriting_metric() -> None:
    metric_repo = _FailingMetricWriter()
    event_writer = _EventWriter()
    event_writer.should_fail_first = True
    mapping_repo = _MappingRepo([_approved_mapping()])
    receipt_repo = _ReceiptRepo()
    status_service = _StatusService()
    service = MqttBridgeService(
        mapping_repo=mapping_repo,
        receipt_repo=receipt_repo,
        metric_writer=metric_repo,
        event_writer=event_writer,
        runtime_status_service=status_service,
        event_writer_driver=object(),
    )

    first = service.process_reading(_reading(value=44.4))
    second = service.process_reading(_reading(value=44.4))

    assert first[0]["outcome"] == MQTT_MAPPING_EVENT_PENDING_OUTCOME
    assert second[0]["outcome"] == MQTT_MAPPING_EVENT_RETRY_SUCCESS_OUTCOME
    assert len(metric_repo.calls) == 1
    assert len(event_writer.calls) == 2


def test_partial_event_failure_retries_event_only_without_rewriting_metric() -> None:
    metric_repo = _MetricRepo()
    event_writer = _EventWriter()
    event_writer.should_fail_first = True
    mapping_repo = _MappingRepo([_approved_mapping()])
    receipt_repo = _ReceiptRepo()
    status_service = _StatusService()
    service = MqttBridgeService(
        mapping_repo=mapping_repo,
        receipt_repo=receipt_repo,
        metric_writer=metric_repo.insert_metric_value,
        event_writer=event_writer,
        runtime_status_service=status_service,
        event_writer_driver=object(),
    )

    first = service.process_reading(_reading(value=42.1))
    second = service.process_reading(_reading(value=42.1))

    assert first[0]["outcome"] == MQTT_MAPPING_EVENT_PENDING_OUTCOME
    assert second[0]["outcome"] == MQTT_MAPPING_EVENT_RETRY_SUCCESS_OUTCOME
    assert len(metric_repo.calls) == 1
    assert len(event_writer.calls) == 2
    assert status_service.outcomes[-2:] == [
        MQTT_MAPPING_EVENT_PENDING_OUTCOME,
        MQTT_MAPPING_EVENT_RETRY_SUCCESS_OUTCOME,
    ]


def test_pending_receipt_without_timescale_is_not_rewritten_to_timescale() -> None:
    metric_repo = _MetricRepo()
    event_writer = _EventWriter()
    mapping_repo = _MappingRepo([_approved_mapping()])
    receipt_repo = _ReceiptRepo()
    status_service = _StatusService()
    service = MqttBridgeService(
        mapping_repo=mapping_repo,
        receipt_repo=receipt_repo,
        metric_writer=metric_repo.insert_metric_value,
        event_writer=event_writer,
        runtime_status_service=status_service,
        event_writer_driver=object(),
    )

    key = service._idempotency_key(
        "map-1",
        "rtu-1/temperature",
        FIXED_TS,
        service._value_hash("map-1", "rtu-1/temperature", 12.5, FIXED_TS),
    )
    receipt_repo.create_receipt(
        idempotency_key=key,
        mapping_id="map-1",
        source_device_id="rtu-1",
        source_metric_id="rtu-1/temperature",
        observed_at=FIXED_TS,
        value_hash=service._value_hash("map-1", "rtu-1/temperature", 12.5, FIXED_TS),
        status="PENDING_EVENT",
    )

    result = service.process_reading(_reading(value=12.5))

    assert result[0]["outcome"] == MQTT_MAPPING_EVENT_RETRY_SUCCESS_OUTCOME
    assert metric_repo.calls == []
    assert len(event_writer.calls) == 1


def test_timescale_mark_failure_stays_retryable_without_duplicate_metric_write() -> None:
    metric_repo = _MetricRepo()
    event_writer = _EventWriter()
    event_writer.should_fail_first = True
    mapping_repo = _MappingRepo([_approved_mapping()])
    receipt_repo = _FailingTimescaleMarkReceiptRepo()
    status_service = _StatusService()

    service = MqttBridgeService(
        mapping_repo=mapping_repo,
        receipt_repo=receipt_repo,
        metric_writer=metric_repo.insert_metric_value,
        event_writer=event_writer,
        runtime_status_service=status_service,
        event_writer_driver=object(),
    )

    first = service.process_reading(_reading(value=55.0))
    second = service.process_reading(_reading(value=55.0))

    assert first[0]["outcome"] == MQTT_MAPPING_EVENT_PENDING_OUTCOME
    assert second[0]["outcome"] == MQTT_MAPPING_EVENT_RETRY_SUCCESS_OUTCOME
    assert len(metric_repo.calls) == 1
    assert len(event_writer.calls) == 2


def test_event_success_without_event_receipt_mark_stays_idempotent_on_retry() -> None:
    metric_repo = _MetricRepo()
    event_writer = _IdempotentEventWriter()
    mapping_repo = _MappingRepo([_approved_mapping()])
    receipt_repo = _FailingEventMarkReceiptRepo()
    status_service = _StatusService()

    service = MqttBridgeService(
        mapping_repo=mapping_repo,
        receipt_repo=receipt_repo,
        metric_writer=metric_repo.insert_metric_value,
        event_writer=event_writer,
        runtime_status_service=status_service,
        event_writer_driver=object(),
    )

    first = service.process_reading(_reading(value=61.0))
    second = service.process_reading(_reading(value=61.0))

    assert first[0]["outcome"] == MQTT_MAPPING_EVENT_PENDING_OUTCOME
    assert second[0]["outcome"] == MQTT_MAPPING_EVENT_RETRY_SUCCESS_OUTCOME
    assert len(event_writer.calls) == 2


def test_event_writer_receives_lock_db_when_factory_provided() -> None:
    class _DB:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    lock_db = _DB()
    lock_factory_called = {"count": 0}

    class _CountingFactory:
        def __call__(self) -> _DB:
            lock_factory_called["count"] += 1
            return lock_db

    mapping_repo = _MappingRepo([_approved_mapping()])
    receipt_repo = _ReceiptRepo()
    event_writer = _EventWriter()
    service = MqttBridgeService(
        mapping_repo=mapping_repo,
        receipt_repo=receipt_repo,
        metric_writer=_MetricRepo().insert_metric_value,
        event_writer=event_writer,
        event_writer_driver=object(),
        event_writer_lock_db=_CountingFactory(),
        runtime_status_service=_StatusService(),
    )

    service.process_reading(_reading())

    assert lock_factory_called["count"] == 1
    _, _, kwargs = event_writer.calls[0]
    assert kwargs["lock_db"] is lock_db
    assert lock_db.closed is True


def test_mapped_event_pending_is_counted_as_failed() -> None:
    runtime_status = _StatusCounterService()
    runtime = _DefaultRuntimeStatusService()
    runtime._service = runtime_status

    runtime.record_bridge_outcome(MQTT_MAPPING_EVENT_PENDING_OUTCOME)

    assert runtime_status.counters == ["failed_writes_total"]
