"""Data access for MQTT metric sample receipt tracking (idempotency + retries)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from models.mqtt_metric_sample_receipt import MqttMetricSampleReceipt
from postgres_db import SessionLocal
from sqlalchemy import text
from sqlalchemy.orm import Session

RECEIPT_STATUS_PENDING_METRIC = "PENDING_METRIC"
RECEIPT_STATUS_PENDING_EVENT = "PENDING_EVENT"
RECEIPT_STATUS_COMPLETE = "COMPLETE"
RECEIPT_STATUS_FAILED = "FAILED"


class MqttMetricSampleReceiptRepository:
    """Persist and query mapping bridge dedupe receipts."""

    def __init__(self, session_factory: Callable[[], Session] | None = None):
        self._session_factory = session_factory or SessionLocal

    def _get_db(self) -> Session:
        return self._session_factory()

    @staticmethod
    def _to_dict(record: MqttMetricSampleReceipt | None) -> dict[str, Any] | None:
        if record is None:
            return None
        return {
            "idempotency_key": record.idempotency_key,
            "mapping_id": record.mapping_id,
            "source_device_id": record.source_device_id,
            "source_metric_id": record.source_metric_id,
            "observed_at": record.observed_at,
            "value_hash": record.value_hash,
            "status": record.status,
            "timescale_written_at": record.timescale_written_at,
            "event_written_at": record.event_written_at,
            "last_error": record.last_error,
        }

    @staticmethod
    def _ensure_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def get_receipt(self, idempotency_key: str) -> dict[str, Any] | None:
        """Return one receipt for the idempotency key, if any."""
        db = self._get_db()
        try:
            row = (
                db.query(MqttMetricSampleReceipt)
                .filter(MqttMetricSampleReceipt.idempotency_key == idempotency_key)
                .one_or_none()
            )
            if row is None:
                return None
            payload = self._to_dict(row)
            if payload is not None:
                payload["observed_at"] = self._ensure_datetime(payload["observed_at"])
                payload["timescale_written_at"] = self._ensure_datetime(
                    payload["timescale_written_at"]
                )
                payload["event_written_at"] = self._ensure_datetime(payload["event_written_at"])
            return payload
        finally:
            db.close()

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
        """Create a new receipt row."""
        db = self._get_db()
        try:
            record = MqttMetricSampleReceipt(
                idempotency_key=idempotency_key,
                mapping_id=mapping_id,
                source_device_id=source_device_id,
                source_metric_id=source_metric_id,
                observed_at=observed_at,
                value_hash=value_hash,
                status=status,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return self._to_dict(record)
        except Exception:
            db.rollback()
            existing = self.get_receipt(idempotency_key)
            if existing is not None:
                return existing
            raise
        finally:
            db.close()

    def mark_timescale_written(
        self,
        idempotency_key: str,
        *,
        status: str,
        now: datetime,
    ) -> dict[str, Any]:
        """Mark metric write done and keep event state for downstream retries."""
        db = self._get_db()
        try:
            row = (
                db.query(MqttMetricSampleReceipt)
                .filter(MqttMetricSampleReceipt.idempotency_key == idempotency_key)
                .one_or_none()
            )
            if row is None:
                raise ValueError(f"Receipt not found: {idempotency_key}")
            row.status = status
            row.timescale_written_at = now
            row.last_error = None
            db.commit()
            db.refresh(row)
            return self._to_dict(row)
        finally:
            db.close()

    def mark_event_written(
        self,
        idempotency_key: str,
        *,
        status: str,
        now: datetime,
    ) -> dict[str, Any]:
        db = self._get_db()
        try:
            row = (
                db.query(MqttMetricSampleReceipt)
                .filter(MqttMetricSampleReceipt.idempotency_key == idempotency_key)
                .one_or_none()
            )
            if row is None:
                raise ValueError(f"Receipt not found: {idempotency_key}")
            row.status = status
            row.event_written_at = now
            row.last_error = None
            db.commit()
            db.refresh(row)
            return self._to_dict(row)
        finally:
            db.close()

    def mark_event_failed(
        self,
        idempotency_key: str,
        *,
        status: str,
        error: str,
        now: datetime,
    ) -> dict[str, Any]:
        db = self._get_db()
        try:
            row = (
                db.query(MqttMetricSampleReceipt)
                .filter(MqttMetricSampleReceipt.idempotency_key == idempotency_key)
                .one_or_none()
            )
            if row is None:
                raise ValueError(f"Receipt not found: {idempotency_key}")
            row.status = status
            row.event_written_at = None
            row.last_error = error
            row.timescale_written_at = row.timescale_written_at or now
            db.commit()
            db.refresh(row)
            return self._to_dict(row)
        finally:
            db.close()

    def mark_failed(
        self,
        idempotency_key: str,
        *,
        status: str,
        error: str,
        now: datetime,
    ) -> dict[str, Any]:
        db = self._get_db()
        try:
            row = (
                db.query(MqttMetricSampleReceipt)
                .filter(MqttMetricSampleReceipt.idempotency_key == idempotency_key)
                .one_or_none()
            )
            if row is None:
                raise ValueError(f"Receipt not found: {idempotency_key}")
            row.status = status
            row.last_error = error
            db.commit()
            db.refresh(row)
            return self._to_dict(row)
        finally:
            db.close()

    def ensure_schema(self) -> None:
        db = self._get_db()
        try:
            db.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS mqtt_metric_sample_receipts (\n"
                    "    idempotency_key TEXT PRIMARY KEY,\n"
                    "    mapping_id TEXT NOT NULL,\n"
                    "    source_device_id TEXT NOT NULL,\n"
                    "    source_metric_id TEXT NOT NULL,\n"
                    "    observed_at TIMESTAMPTZ NOT NULL,\n"
                    "    value_hash TEXT NOT NULL,\n"
                    "    status TEXT NOT NULL,\n"
                    "    timescale_written_at TIMESTAMPTZ,\n"
                    "    event_written_at TIMESTAMPTZ,\n"
                    "    last_error TEXT\n"
                    ")"
                )
            )
            db.commit()
        finally:
            db.close()
