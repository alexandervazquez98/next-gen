"""Service layer for MQTT raw-to-monitoring bridge.

- resolve approved mappings only
- write metric sample to Timescale
- write events to Neo4j via event rows
- use receipts for idempotency and status transitions
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from database import get_db as get_neo4j_db
from polling.event_writer import batch_update_events
from postgres_db import SessionLocal
from repositories.metric_repo import insert_metric_value
from repositories.mqtt_mapping_repo import MqttMappingRepo
from repositories.mqtt_metric_sample_receipt_repo import (
    RECEIPT_STATUS_COMPLETE,
    RECEIPT_STATUS_FAILED,
    RECEIPT_STATUS_PENDING_EVENT,
    RECEIPT_STATUS_PENDING_METRIC,
    MqttMetricSampleReceiptRepository,
)
from services.mqtt.parsers.base import MetricReading, Reading
from services.mqtt_runtime_status import get_mqtt_runtime_status_service
from sqlalchemy.exc import IntegrityError

MQTT_MAPPING_UNMAPPED_OUTCOME = "SKIPPED_UNMAPPED"
MQTT_MAPPING_DRAFT_OUTCOME = "SKIPPED_DRAFT"
MQTT_MAPPING_REVOKED_OUTCOME = "SKIPPED_REVOKED"
MQTT_MAPPING_AMBIGUOUS_OUTCOME = "BLOCKED_AMBIGUOUS_MAPPING"
MQTT_MAPPING_NON_NUMERIC_OUTCOME = "SKIPPED_NON_NUMERIC"
MQTT_MAPPING_DUPLICATE_OUTCOME = "SKIPPED_DUPLICATE"
MQTT_MAPPING_APPROVED_OUTCOME = "MAPPED_PERSISTED"
MQTT_MAPPING_EVENT_PENDING_OUTCOME = "MAPPED_EVENT_PENDING"
MQTT_MAPPING_EVENT_RETRY_SUCCESS_OUTCOME = "MAPPED_EVENT_RETRY_SUCCESS"


class _DefaultMetricWriter:
    def __call__(self, node_id: str, metric_id: str, value: float, observed_at: datetime) -> None:
        db = SessionLocal()
        try:
            insert_metric_value(
                db=db,
                node_id=node_id,
                metric_id=metric_id,
                value=value,
                timestamp=observed_at,
            )
        finally:
            db.close()


class _DefaultRuntimeStatusService:
    def __init__(self) -> None:
        self._service = get_mqtt_runtime_status_service()

    def record_bridge_outcome(self, outcome: str) -> None:
        if outcome in {
            MQTT_MAPPING_APPROVED_OUTCOME,
            MQTT_MAPPING_EVENT_RETRY_SUCCESS_OUTCOME,
            MQTT_MAPPING_DUPLICATE_OUTCOME,
        }:
            self._service.increment_counter("mapped_writes_total")
        elif outcome in {
            MQTT_MAPPING_UNMAPPED_OUTCOME,
            MQTT_MAPPING_DRAFT_OUTCOME,
            MQTT_MAPPING_REVOKED_OUTCOME,
            MQTT_MAPPING_AMBIGUOUS_OUTCOME,
            MQTT_MAPPING_NON_NUMERIC_OUTCOME,
        }:
            self._service.increment_counter("unmapped_skips_total")
        else:
            self._service.increment_counter("failed_writes_total")


class MqttBridgeService:
    """Deterministic, fail-closed bridge between MQTT raw readings and KPI writes."""

    def __init__(
        self,
        *,
        mapping_repo: MqttMappingRepo | None = None,
        receipt_repo: MqttMetricSampleReceiptRepository | None = None,
        metric_writer: Callable[[str, str, float, datetime], Any] | None = None,
        event_writer: Callable[[Any, list[dict[str, Any]], Any], Any] | None = None,
        runtime_status_service: Any | None = None,
        event_writer_driver: Any | None = None,
        event_writer_lock_db: Callable[[], Any] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._mapping_repo = mapping_repo or MqttMappingRepo()
        self._receipt_repo = receipt_repo or MqttMetricSampleReceiptRepository()
        self._metric_writer = metric_writer or _DefaultMetricWriter()
        self._event_writer = event_writer or batch_update_events
        self._runtime_status_service = runtime_status_service or _DefaultRuntimeStatusService()
        self._event_writer_driver = (
            event_writer_driver if event_writer_driver is not None else get_neo4j_db()
        )
        self._event_writer_lock_db = event_writer_lock_db
        self._now = now_provider or (lambda: datetime.now(UTC))

    @staticmethod
    def _normalize_observed_at(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    @staticmethod
    def _canonical_numeric(value: Any) -> tuple[float | None, bool]:
        if isinstance(value, bool):
            return None, False
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None, False
        return numeric, True

    @staticmethod
    def _value_hash(
        mapping_id: str, source_metric_id: str, value: float, observed_at: datetime
    ) -> str:
        payload = {
            "mapping_id": mapping_id,
            "source_metric_id": source_metric_id,
            "value": value,
            "observed_at": MqttBridgeService._normalize_observed_at(observed_at)
            .isoformat()
            .replace(
                "+00:00",
                "Z",
            ),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _idempotency_key(
        mapping_id: str,
        source_metric_id: str,
        observed_at: datetime,
        value_hash: str,
    ) -> str:
        return f"mqtt:{mapping_id}:{source_metric_id}:{MqttBridgeService._normalize_observed_at(observed_at).isoformat()}:{value_hash}"

    def _make_event_payload(
        self,
        *,
        reading: Reading,
        metric: MetricReading,
        mapping: dict[str, Any],
        value: float,
        idempotency_key: str,
        observed_at: datetime,
    ) -> dict[str, Any]:
        return {
            "idempotency_key": idempotency_key,
            "protocol": "MQTT",
            "source_protocol": "MQTT",
            "ci_id": mapping["target_ci_id"],
            "metric_id": mapping["target_metric_def_id"],
            "value": {"numeric": value},
            "status": "OK",
            "observed_at": observed_at.isoformat(),
            "metadata": {
                "mapping_id": mapping["id"],
                "source_device_id": reading.device_id,
                "source_metric_id": f"{reading.device_id}/{metric.name}",
                "source_metric_name": mapping.get("source_metric_name") or metric.name,
                "operator": mapping.get("operator") or ">=",
                "warning": mapping.get("warning"),
                "critical": mapping.get("critical"),
            },
        }

    def _record_outcome(self, outcome: str) -> None:
        self._runtime_status_service.record_bridge_outcome(outcome)

    def _mark_timescale_written(self, idempotency_key: str, now: datetime) -> None:
        if hasattr(self._receipt_repo, "mark_timescale_written"):
            self._receipt_repo.mark_timescale_written(
                idempotency_key,
                status=RECEIPT_STATUS_PENDING_EVENT,
                now=now,
            )
            return
        self._receipt_repo.update_receipt_status(
            idempotency_key,
            status=RECEIPT_STATUS_PENDING_EVENT,
            timescale_written_at=now,
            last_error=None,
        )

    def _mark_event_written(self, idempotency_key: str, now: datetime) -> None:
        if hasattr(self._receipt_repo, "mark_event_written"):
            self._receipt_repo.mark_event_written(
                idempotency_key,
                status=RECEIPT_STATUS_COMPLETE,
                now=now,
            )
            return
        self._receipt_repo.update_receipt_status(
            idempotency_key,
            status=RECEIPT_STATUS_COMPLETE,
            event_written_at=now,
            last_error=None,
        )

    def _mark_event_failed(self, idempotency_key: str, now: datetime, error: str) -> None:
        if hasattr(self._receipt_repo, "mark_event_failed"):
            self._receipt_repo.mark_event_failed(
                idempotency_key,
                status=RECEIPT_STATUS_PENDING_EVENT,
                error=error,
                now=now,
            )
            return
        self._receipt_repo.update_receipt_status(
            idempotency_key,
            status=RECEIPT_STATUS_PENDING_EVENT,
            last_error=error,
            event_written_at=None,
        )

    def _mark_failed(self, idempotency_key: str, now: datetime, error: str) -> None:
        if hasattr(self._receipt_repo, "mark_failed"):
            self._receipt_repo.mark_failed(
                idempotency_key,
                status=RECEIPT_STATUS_FAILED,
                error=error,
                now=now,
            )
            return
        self._receipt_repo.update_receipt_status(
            idempotency_key,
            status=RECEIPT_STATUS_FAILED,
            last_error=error,
        )

    def _invoke_event_writer(self, payloads: list[dict[str, Any]]) -> None:
        lock_db = None
        try:
            if self._event_writer_lock_db is not None:
                lock_db = self._event_writer_lock_db()

            if lock_db is not None:
                self._event_writer(
                    self._event_writer_driver,
                    payloads,
                    lock_db=lock_db,
                )
            else:
                self._event_writer(
                    self._event_writer_driver,
                    payloads,
                )
        finally:
            if lock_db is not None:
                close = getattr(lock_db, "close", None)
                if callable(close):
                    close()

    def _write_events_and_update_receipt(
        self,
        *,
        idempotency_key: str,
        payload: list[dict[str, Any]],
        success_outcome: str,
        pending_outcome: str,
    ) -> tuple[str, dict[str, str] | None]:
        try:
            self._invoke_event_writer(payload)
            self._mark_event_written(
                idempotency_key,
                self._now(),
            )
            return success_outcome, None
        except Exception as exc:
            self._mark_event_failed(
                idempotency_key,
                self._now(),
                str(exc),
            )
            return pending_outcome, {"error": str(exc)}

    def _resolve_approved_mapping(
        self,
        source_device_id: str,
        source_metric_id: str,
    ) -> tuple[dict[str, Any] | None, str]:
        if hasattr(self._mapping_repo, "list_mappings_for_source"):
            mappings = self._mapping_repo.list_mappings_for_source(
                source_device_id=source_device_id,
                source_metric_id=source_metric_id,
            )
        else:
            mappings = self._mapping_repo.list_approved_mappings_for_source(
                source_device_id=source_device_id,
                source_metric_id=source_metric_id,
            )
        approved = [m for m in mappings if str(m.get("status") or "").upper() == "APPROVED"]

        if len(approved) == 1:
            return approved[0], MQTT_MAPPING_APPROVED_OUTCOME

        if len(approved) > 1:
            return None, MQTT_MAPPING_AMBIGUOUS_OUTCOME

        if not mappings:
            return None, MQTT_MAPPING_UNMAPPED_OUTCOME

        statuses = {str(item.get("status") or "").upper() for item in mappings}
        if statuses == {"DRAFT"}:
            return None, MQTT_MAPPING_DRAFT_OUTCOME
        if statuses == {"REVOKED"}:
            return None, MQTT_MAPPING_REVOKED_OUTCOME

        return None, MQTT_MAPPING_AMBIGUOUS_OUTCOME

    def process_reading(self, reading: Reading) -> list[dict[str, Any]]:
        outcomes: list[dict[str, Any]] = []
        observed_at = self._normalize_observed_at(reading.timestamp)

        for metric in reading.metrics:
            source_metric_id = f"{reading.device_id}/{metric.name}"
            numeric, ok = self._canonical_numeric(metric.value)

            if not ok:
                outcome = MQTT_MAPPING_NON_NUMERIC_OUTCOME
                self._record_outcome(outcome)
                outcomes.append(
                    {
                        "source_device_id": reading.device_id,
                        "source_metric_id": source_metric_id,
                        "mapping_id": None,
                        "idempotency_key": None,
                        "outcome": outcome,
                    }
                )
                continue

            mapping, outcome = self._resolve_approved_mapping(
                source_device_id=reading.device_id,
                source_metric_id=source_metric_id,
            )
            if mapping is None:
                self._record_outcome(outcome)
                outcomes.append(
                    {
                        "source_device_id": reading.device_id,
                        "source_metric_id": source_metric_id,
                        "mapping_id": None,
                        "idempotency_key": None,
                        "outcome": outcome,
                    }
                )
                continue

            mapping_id = str(mapping["id"])
            value_hash = self._value_hash(mapping_id, source_metric_id, numeric, observed_at)
            idempotency_key = self._idempotency_key(
                mapping_id,
                source_metric_id,
                observed_at,
                value_hash,
            )

            receipt = self._receipt_repo.get_receipt(idempotency_key)
            if receipt is None:
                self._receipt_repo.create_receipt(
                    idempotency_key=idempotency_key,
                    mapping_id=mapping_id,
                    source_device_id=reading.device_id,
                    source_metric_id=source_metric_id,
                    observed_at=observed_at,
                    value_hash=value_hash,
                    status=RECEIPT_STATUS_PENDING_METRIC,
                )
                receipt = self._receipt_repo.get_receipt(idempotency_key)

            if receipt is None:
                self._mark_failed(
                    idempotency_key,
                    self._now(),
                    "Receipt could not be created",
                )
                outcome = RECEIPT_STATUS_FAILED
                self._record_outcome(outcome)
                outcomes.append(
                    {
                        "source_device_id": reading.device_id,
                        "source_metric_id": source_metric_id,
                        "mapping_id": mapping_id,
                        "idempotency_key": idempotency_key,
                        "outcome": outcome,
                        "error": "Receipt creation failed",
                    }
                )
                continue

            if receipt.get("status") == RECEIPT_STATUS_COMPLETE:
                outcome = MQTT_MAPPING_DUPLICATE_OUTCOME
                self._record_outcome(outcome)
                outcomes.append(
                    {
                        "source_device_id": reading.device_id,
                        "source_metric_id": source_metric_id,
                        "mapping_id": mapping_id,
                        "idempotency_key": idempotency_key,
                        "outcome": outcome,
                    }
                )
                continue

            payload = self._make_event_payload(
                reading=reading,
                metric=metric,
                mapping=mapping,
                value=numeric,
                idempotency_key=idempotency_key,
                observed_at=observed_at,
            )

            if receipt.get("status") == RECEIPT_STATUS_PENDING_EVENT:
                outcome, event_error = self._write_events_and_update_receipt(
                    idempotency_key=idempotency_key,
                    payload=[payload],
                    success_outcome=MQTT_MAPPING_EVENT_RETRY_SUCCESS_OUTCOME,
                    pending_outcome=MQTT_MAPPING_EVENT_PENDING_OUTCOME,
                )
                outcome_entry = {
                    "source_device_id": reading.device_id,
                    "source_metric_id": source_metric_id,
                    "mapping_id": mapping_id,
                    "idempotency_key": idempotency_key,
                    "outcome": outcome,
                }
                if event_error is not None:
                    outcome_entry["error"] = event_error["error"]
                self._record_outcome(outcome)
                outcomes.append(outcome_entry)
                continue

            metric_written = False
            try:
                self._metric_writer(
                    mapping["target_ci_id"],
                    mapping["target_metric_def_id"],
                    numeric,
                    observed_at,
                )
                metric_written = True
            except IntegrityError:
                # Duplicate Timescale sample in the same key range should be treated as
                # idempotent (event-only path should be used next).
                metric_written = True
            except Exception as exc:
                self._mark_failed(
                    idempotency_key,
                    self._now(),
                    str(exc),
                )
                outcome = RECEIPT_STATUS_FAILED
                self._record_outcome(outcome)
                outcomes.append(
                    {
                        "source_device_id": reading.device_id,
                        "source_metric_id": source_metric_id,
                        "mapping_id": mapping_id,
                        "idempotency_key": idempotency_key,
                        "outcome": outcome,
                        "error": str(exc),
                    }
                )
                continue

            if metric_written:
                with suppress(Exception):
                    self._mark_timescale_written(
                        idempotency_key,
                        self._now(),
                    )

                outcome, event_error = self._write_events_and_update_receipt(
                    idempotency_key=idempotency_key,
                    payload=[payload],
                    success_outcome=MQTT_MAPPING_APPROVED_OUTCOME,
                    pending_outcome=MQTT_MAPPING_EVENT_PENDING_OUTCOME,
                )
            else:
                outcome = RECEIPT_STATUS_FAILED
                event_error = {"error": "Metric was not written"}

            outcome_entry = {
                "source_device_id": reading.device_id,
                "source_metric_id": source_metric_id,
                "mapping_id": mapping_id,
                "idempotency_key": idempotency_key,
                "outcome": outcome,
            }
            if event_error is not None:
                outcome_entry["error"] = event_error["error"]
            self._record_outcome(outcome)
            outcomes.append(outcome_entry)

        return outcomes


_bridge_service: MqttBridgeService | None = None


def get_mqtt_bridge_service(
    mapping_repo: MqttMappingRepo | None = None,
    receipt_repo: MqttMetricSampleReceiptRepository | None = None,
    metric_writer: Callable[[str, str, float, datetime], Any] | None = None,
    event_writer: Callable[[Any, list[dict[str, Any]], Any], Any] | None = None,
    runtime_status_service: Any | None = None,
    event_writer_driver: Any | None = None,
    event_writer_lock_db: Callable[[], Any] | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> MqttBridgeService:
    global _bridge_service
    if _bridge_service is None:
        _bridge_service = MqttBridgeService(
            mapping_repo=mapping_repo,
            receipt_repo=receipt_repo,
            metric_writer=metric_writer,
            event_writer=event_writer,
            runtime_status_service=runtime_status_service,
            event_writer_driver=event_writer_driver,
            event_writer_lock_db=event_writer_lock_db,
            now_provider=now_provider,
        )
    elif event_writer_lock_db is not None:
        _bridge_service._event_writer_lock_db = event_writer_lock_db
    return _bridge_service
