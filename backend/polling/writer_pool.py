"""Dedicated polling result writer pool primitives."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID

from config import get_icmp_settings
from models.timescale_models import MetricValue
from polling import event_writer, pg_queue
from polling.icmp_measurements import (
    ICMP_AVAILABILITY_METRIC_ID,
    ICMP_JITTER_METRIC_ID,
    ICMP_LATENCY_METRIC_ID,
    ICMP_PACKET_LOSS_METRIC_ID,
    evaluate_jitter_status,
    evaluate_latency_status,
    evaluate_packet_loss_status,
    jitter_threshold_metadata,
    latency_threshold_metadata,
    packet_loss_threshold_metadata,
)
from sqlalchemy import text


def _utc_now() -> datetime:
    return datetime.now(UTC)


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


def _is_internal_icmp_availability(envelope: Mapping[str, Any]) -> bool:
    return (
        str(envelope.get("protocol") or "").upper() == "ICMP"
        and envelope.get("metric_id") == ICMP_AVAILABILITY_METRIC_ID
        and bool((envelope.get("metadata") or {}).get("internal"))
    )


def _sample(envelope: Mapping[str, Any]) -> dict[str, Any] | None:
    if _is_internal_icmp_availability(envelope):
        return None
    numeric = _numeric(envelope)
    if numeric is None:
        return None
    return {
        "node_id": envelope["ci_id"],
        "metric_id": envelope["metric_id"],
        "value": numeric,
        "time": _timestamp(envelope["observed_at"]),
    }


def previous_metric_value(db, node_id: str, metric_id: str, before: datetime) -> float | None:
    result = db.execute(
        text("""
            SELECT value FROM metric_values
            WHERE node_id = :node_id AND metric_id = :metric_id AND time < :before
            ORDER BY time DESC LIMIT 1
        """),
        {"node_id": node_id, "metric_id": metric_id, "before": before},
    )
    row = result.first() if hasattr(result, "first") else None
    if not row:
        return None
    value = row[0] if not isinstance(row, Mapping) else row.get("value")
    return None if value is None else float(value)


def _sidecar_samples(db, envelope: Mapping[str, Any]) -> list[dict[str, Any]]:
    icmp = ((envelope.get("metadata") or {}).get("icmp") or {})
    sidecar_ids = set(icmp.get("sidecar_metric_ids") or [])
    if not sidecar_ids:
        return []
    observed = _timestamp(envelope["observed_at"])
    samples = []
    numeric = _numeric(envelope)
    if ICMP_LATENCY_METRIC_ID in sidecar_ids and "latency_ms" in icmp:
        latency = float(icmp["latency_ms"])
        samples.append({"node_id": envelope["ci_id"], "metric_id": ICMP_LATENCY_METRIC_ID, "value": latency, "time": observed})
        previous = previous_metric_value(db, envelope["ci_id"], ICMP_LATENCY_METRIC_ID, observed)
    else:
        latency = None
        previous = None
    if ICMP_JITTER_METRIC_ID in sidecar_ids and latency is not None and previous is not None:
        samples.append({"node_id": envelope["ci_id"], "metric_id": ICMP_JITTER_METRIC_ID, "value": abs(latency - previous), "time": observed})
    if ICMP_PACKET_LOSS_METRIC_ID in sidecar_ids and numeric is not None:
        packet_loss = 0.0 if numeric > 0 else 100.0
        samples.append({"node_id": envelope["ci_id"], "metric_id": ICMP_PACKET_LOSS_METRIC_ID, "value": packet_loss, "time": observed})
    return samples


def _icmp_latency_event_envelope(
    envelope: Mapping[str, Any], db: Any | None = None
) -> dict[str, Any] | None:
    icmp = ((envelope.get("metadata") or {}).get("icmp") or {})
    if "latency_ms" not in icmp:
        return None
    latency = float(icmp["latency_ms"])
    settings = get_icmp_settings()
    metadata = latency_threshold_metadata(
        warning_ms=settings.latency_warning_ms,
        critical_ms=settings.latency_critical_ms,
    )
    status = evaluate_latency_status(
        latency,
        warning_ms=settings.latency_warning_ms,
        critical_ms=settings.latency_critical_ms,
    )
    return {
        **dict(envelope),
        "metric_id": ICMP_LATENCY_METRIC_ID,
        "status": status,
        "value": {"numeric": latency, "raw": latency},
        "metadata": metadata,
    }


def _icmp_jitter_event_envelope(
    envelope: Mapping[str, Any], db: Any | None = None
) -> dict[str, Any] | None:
    """Build a jitter event envelope from a sidecar ICMP envelope.

    Jitter cannot be computed without both the current latency sample AND a
    previous latency sample from the timeseries DB. Returning ``None`` when
    either is missing is the design choice: the CI-down path (availability=0,
    packet_loss=100) is owned by ``_icmp_packet_loss_event_envelope``, so we
    do NOT synthesize a sentinel jitter value here. The first-ever sample on
    a CI also returns ``None`` because there is no baseline.
    """
    icmp = ((envelope.get("metadata") or {}).get("icmp") or {})
    if "latency_ms" not in icmp:
        return None
    latency = float(icmp["latency_ms"])
    observed = _timestamp(envelope["observed_at"])
    previous = previous_metric_value(db, envelope["ci_id"], ICMP_LATENCY_METRIC_ID, observed)
    if previous is None:
        return None
    jitter = abs(latency - previous)
    settings = get_icmp_settings()
    metadata = jitter_threshold_metadata(
        warning_ms=settings.jitter_warning_ms,
        critical_ms=settings.jitter_critical_ms,
    )
    status = evaluate_jitter_status(
        jitter,
        warning_ms=settings.jitter_warning_ms,
        critical_ms=settings.jitter_critical_ms,
    )
    if status == "OK":
        return None
    return {
        **dict(envelope),
        "metric_id": ICMP_JITTER_METRIC_ID,
        "status": status,
        "value": {"numeric": jitter, "raw": jitter},
        "metadata": metadata,
    }


def _icmp_packet_loss_event_envelope(
    envelope: Mapping[str, Any], db: Any | None = None
) -> dict[str, Any] | None:
    """Build a packet-loss event envelope from a sidecar ICMP envelope.

    Packet loss is derived from the availability numeric (0 → 100%, >0 → 0%).
    When the CI is down the value is 100% — always CRITICAL given the default
    critical threshold. Healthy CIs return ``None`` so the event stream only
    carries actionable packet-loss observations.
    """
    icmp = ((envelope.get("metadata") or {}).get("icmp") or {})
    sidecar_ids = set(icmp.get("sidecar_metric_ids") or [])
    if ICMP_PACKET_LOSS_METRIC_ID not in sidecar_ids:
        return None
    numeric = _numeric(envelope)
    if numeric is None:
        return None
    packet_loss = 0.0 if numeric > 0 else 100.0
    settings = get_icmp_settings()
    metadata = packet_loss_threshold_metadata(
        warning_pct=settings.packet_loss_warning_pct,
        critical_pct=settings.packet_loss_critical_pct,
    )
    status = evaluate_packet_loss_status(
        packet_loss,
        warning_pct=settings.packet_loss_warning_pct,
        critical_pct=settings.packet_loss_critical_pct,
    )
    if status == "OK":
        return None
    return {
        **dict(envelope),
        "metric_id": ICMP_PACKET_LOSS_METRIC_ID,
        "status": status,
        "value": {"numeric": packet_loss, "raw": packet_loss},
        "metadata": metadata,
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
        samples = []
        for item in new_payloads:
            if item["sample"] is not None:
                samples.append(item["sample"])
            samples.extend(_sidecar_samples(timescale_db, item["envelope"]))
        persist_samples_and_receipts(timescale_db, new_payloads, samples)
        stats["inserted"] += len(samples)
    except Exception as exc:
        retry_at = (now or _utc_now()) + timedelta(seconds=30)
        for item in new_payloads:
            pg_queue.retry_result(queue_db, item["result_id"], next_eligible_at=retry_at, error_code="timescale_error", error_message=str(exc))
            stats["retried"] += 1
        return stats

    event_payloads = []
    for item in new_payloads + pending_payloads:
        if not _is_internal_icmp_availability(item["envelope"]):
            event_payloads.append(item)
        for envelope_factory in (
            _icmp_latency_event_envelope,
            _icmp_jitter_event_envelope,
            _icmp_packet_loss_event_envelope,
        ):
            derived = envelope_factory(item["envelope"], timescale_db)
            if derived is not None:
                event_payloads.append({**item, "envelope": derived})
    try:
        # #322 / design §3 — pass the leased timescale_db as lock_db so
        # the advisory lock acquired before each Event UNWIND is held by
        # the same Postgres transaction that backs the metric insert.
        # Lock lifecycle: lock_db stays open for the duration of the
        # batch_update_events call; commit/close below releases the
        # locks. timescale_db is passed (not queue_db) because the lock
        # targets Timescale event correlation tables.
        event_writer.batch_update_events(
            neo4j_driver,
            [item["envelope"] for item in event_payloads],
            lock_db=timescale_db,
        )
    except Exception as exc:
        retry_at = (now or _utc_now()) + timedelta(seconds=30)
        retried_result_ids = set()
        for item in event_payloads:
            if item["result_id"] in retried_result_ids:
                continue
            retried_result_ids.add(item["result_id"])
            pg_queue.retry_result(queue_db, item["result_id"], next_eligible_at=retry_at, error_code="neo4j_pending", error_message=str(exc))
            stats["retried"] += 1
        return stats

    for item in new_payloads + pending_payloads:
        pg_queue.complete_result(queue_db, item["result_id"])
        stats["written"] += 1
    return stats
