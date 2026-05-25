"""Dedicated polling result writer pool primitives."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Iterable, Mapping
from uuid import UUID

from sqlalchemy import text

from models.timescale_models import MetricValue
from polling import event_writer, pg_queue


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get(row: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    return row.get(key, default) if isinstance(row, Mapping) else getattr(row, key, default)


def _value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _envelope(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    raw = _get(row, "envelope") or {}
    data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    data.setdefault("idempotency_key", _get(row, "idempotency_key"))
    data.setdefault("ci_id", _get(row, "ci_id"))
    data.setdefault("metric_id", _get(row, "metric_id"))
    data.setdefault("protocol", _get(row, "protocol"))
    data.setdefault("observed_at", _get(row, "observed_at"))
    return data


def _numeric(envelope: Mapping[str, Any]) -> float | None:
    try:
        value = (envelope.get("value") or {}).get("numeric")
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _timestamp(value: Any) -> Any:
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _sample(envelope: Mapping[str, Any]) -> dict[str, Any] | None:
    numeric = _numeric(envelope)
    if numeric is None:
        return None
    return {
        "node_id": envelope["ci_id"],
        "metric_id": envelope["metric_id"],
        "value": numeric,
        "time": _timestamp(envelope["observed_at"]),
    }


def receipt_exists(db, idempotency_key: str) -> bool:
    result = db.execute(
        text("SELECT 1 FROM metric_sample_receipts WHERE idempotency_key = :idempotency_key LIMIT 1"),
        {"idempotency_key": idempotency_key},
    )
    return result.first() is not None if hasattr(result, "first") else bool(list(result))


def _receipt_payload(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    payload = []
    for row in rows:
        envelope = row["envelope"]
        payload.append({
            "idempotency_key": row["idempotency_key"],
            "result_id": _value(row["result_id"]),
            "cycle_id": _value(row["cycle_id"]),
            "ci_id": envelope["ci_id"],
            "metric_id": envelope["metric_id"],
            "protocol": _value(envelope.get("protocol")),
            "source": envelope.get("source"),
            "observed_at": envelope["observed_at"],
            "value_status": _value(envelope.get("status", "OK")),
        })
    return payload


def _insert_receipt_payload(db, payload: list[dict[str, Any]]) -> None:
    if payload:
        db.execute(text("""
            INSERT INTO metric_sample_receipts (
                idempotency_key, result_id, cycle_id, ci_id, metric_id, protocol,
                source, observed_at, value_status
            ) VALUES (
                :idempotency_key, :result_id, :cycle_id, :ci_id, :metric_id, :protocol,
                :source, :observed_at, :value_status
            ) ON CONFLICT (idempotency_key) DO NOTHING
        """), payload)


def persist_samples_and_receipts(db, rows: Iterable[Mapping[str, Any]], samples: Iterable[Mapping[str, Any]]) -> None:
    """Persist samples and idempotency receipts in one telemetry DB transaction."""
    sample_objects = [
        MetricValue(
            time=sample.get("time", _utc_now()),
            node_id=sample["node_id"],
            metric_id=sample["metric_id"],
            value=sample["value"],
        )
        for sample in samples
    ]
    try:
        if sample_objects:
            db.bulk_save_objects(sample_objects)
        _insert_receipt_payload(db, _receipt_payload(rows))
        db.commit()
    except Exception:
        db.rollback()
        raise


def _result_payload(row: Any) -> dict[str, Any]:
    envelope = _envelope(row)
    return {
        "row": row,
        "result_id": _get(row, "result_id"),
        "cycle_id": _get(row, "cycle_id"),
        "idempotency_key": _get(row, "idempotency_key"),
        "envelope": envelope,
        "sample": _sample(envelope),
        "neo4j_pending": _get(row, "last_error_code") == "neo4j_pending",
    }


def _enabled(settings: Any) -> bool:
    return bool(getattr(settings, "db_writer_enabled", False))


def run_writer_once(
    queue_db,
    timescale_db,
    neo4j_driver,
    *,
    settings,
    worker_id: str,
    lease_ttl_seconds: int = 60,
    writer_partitions: list[int] | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """Claim one result batch and persist samples/events idempotently."""
    stats = {"claimed": 0, "inserted": 0, "duplicates": 0, "written": 0, "retried": 0, "dead_lettered": 0}
    if not _enabled(settings):
        return stats
    rows = pg_queue.claim_results(
        queue_db,
        worker_id=worker_id,
        lease_ttl_seconds=lease_ttl_seconds,
        batch_size=int(getattr(settings, "result_batch_size", 100)),
        writer_partitions=writer_partitions,
    )
    stats["claimed"] = len(rows)
    if not rows:
        return stats

    payloads = [_result_payload(row) for row in rows]
    duplicate_payloads = [item for item in payloads if receipt_exists(timescale_db, item["idempotency_key"])]
    new_payloads = [item for item in payloads if item not in duplicate_payloads]
    pending_payloads = [item for item in duplicate_payloads if item["neo4j_pending"]]
    completed_duplicates = [item for item in duplicate_payloads if not item["neo4j_pending"]]

    for item in completed_duplicates:
        pg_queue.complete_result(queue_db, item["result_id"])
        stats["duplicates"] += 1
        stats["written"] += 1

    try:
        samples = [item["sample"] for item in new_payloads if item["sample"] is not None]
        persist_samples_and_receipts(timescale_db, new_payloads, samples)
        stats["inserted"] += len(samples)
    except Exception as exc:
        retry_at = (now or _utc_now()) + timedelta(seconds=30)
        for item in new_payloads:
            pg_queue.retry_result(queue_db, item["result_id"], next_eligible_at=retry_at, error_code="timescale_error", error_message=str(exc))
            stats["retried"] += 1
        return stats

    event_payloads = new_payloads + pending_payloads
    try:
        event_writer.batch_update_events(neo4j_driver, [item["envelope"] for item in event_payloads])
    except Exception as exc:
        retry_at = (now or _utc_now()) + timedelta(seconds=30)
        for item in event_payloads:
            pg_queue.retry_result(queue_db, item["result_id"], next_eligible_at=retry_at, error_code="neo4j_pending", error_message=str(exc))
            stats["retried"] += 1
        return stats

    for item in event_payloads:
        pg_queue.complete_result(queue_db, item["result_id"])
        stats["written"] += 1
    return stats
