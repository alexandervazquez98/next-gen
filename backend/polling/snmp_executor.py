"""SNMP/ICMP task executor for the leased polling path.

Executors return result envelopes only. They do not write TimescaleDB, Neo4j, or
polling queue state directly.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

from polling.contracts import PollResultEnvelope, PollingProtocol, PollingResultStatus
from polling.icmp_measurements import coerce_ping_measurement, icmp_metadata, is_icmp_availability_metric, is_icmp_telemetry_metric
from polling.idempotency import generate_idempotency_key
from services.polling_event_lifecycle import is_snmp_no_response_failure

Fetcher = Callable[..., Any]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get(task: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    if isinstance(task, Mapping):
        return task.get(key, default)
    return getattr(task, key, default)


def _payload(task: Mapping[str, Any] | Any) -> dict[str, Any]:
    payload = _get(task, "payload", {}) or {}
    if isinstance(payload, str):
        return json.loads(payload)
    return dict(payload)


def _protocol(task: Mapping[str, Any] | Any) -> PollingProtocol:
    value = _get(task, "protocol")
    return value if isinstance(value, PollingProtocol) else PollingProtocol(str(value).strip().upper())


def _default_icmp_fetcher(**kwargs) -> Any:
    from engines.snmp_worker import fetch_icmp_ping_measurement

    return fetch_icmp_ping_measurement(kwargs["ip"], timeout_ms=kwargs.get("timeout_ms", 3000), retries=kwargs.get("retries", 2))


def _default_snmp_fetcher(**kwargs) -> Any:
    from engines.snmp_worker import fetch_snmp_value

    return fetch_snmp_value(
        kwargs["ip"],
        kwargs.get("community", "public"),
        kwargs["oid"],
        int(kwargs.get("port", 161)),
        include_status=True,
    )


def _result_id(task_id: Any, observed_at: datetime, status: PollingResultStatus) -> Any:
    return uuid5(NAMESPACE_URL, f"next-gen|poll-result|{task_id}|{observed_at.isoformat()}|{status.value}")


def execute_poll_task(
    task: Mapping[str, Any] | Any,
    *,
    worker_id: str | None = None,
    observed_at: datetime | None = None,
    icmp_fetcher: Fetcher | None = None,
    snmp_fetcher: Fetcher | None = None,
) -> PollResultEnvelope:
    """Execute a leased SNMP/ICMP task and return a normalized envelope."""
    protocol = _protocol(task)
    payload = _payload(task)
    observed = observed_at or _utc_now()
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    started = _utc_now()
    started_monotonic = time.monotonic()
    status = PollingResultStatus.ERROR
    value: dict[str, Any] = {"numeric": None, "text": None, "raw": None}
    error: dict[str, Any] = {"code": "unsupported_protocol", "message": protocol.value, "retryable": False}
    measurement = None
    task_metadata = _get(task, "metadata", {}) or {}
    if not isinstance(task_metadata, Mapping):
        task_metadata = {}
    metric_id = str(_get(task, "metric_id"))

    try:
        if protocol == PollingProtocol.ICMP:
            metric_metadata = {**dict(task_metadata), **({"metric_kind": _get(task, "metric_kind")} if _get(task, "metric_kind") else {})}
            if not is_icmp_availability_metric(metric_id, metric_metadata):
                status = PollingResultStatus.OK
                value = {"numeric": None, "text": None, "raw": None}
                error = {
                    "code": "skipped_icmp_telemetry" if is_icmp_telemetry_metric(metric_id, metric_metadata) else "unsupported_icmp_metric",
                    "message": "ICMP telemetry sidecars are derived from availability polls",
                    "retryable": False,
                }
            else:
                fetcher = icmp_fetcher or _default_icmp_fetcher
                measurement = coerce_ping_measurement(fetcher(
                    ip=payload.get("target") or _get(task, "source"),
                    timeout_ms=int(payload.get("timeout_ms") or 3000),
                    retries=int(payload.get("retries") or 2),
                ))
                numeric = measurement.availability_value
                status = PollingResultStatus.OK if numeric > 0 else PollingResultStatus.CRITICAL
                value = {"numeric": numeric, "text": None, "raw": numeric}
                error = {"code": None, "message": None, "retryable": False}
        elif protocol == PollingProtocol.SNMP:
            fetcher = snmp_fetcher or _default_snmp_fetcher
            raw = fetcher(
                ip=payload.get("target"),
                community=payload.get("community") or "public",
                oid=payload.get("oid"),
                port=int(payload.get("port") or 161),
            )
            if isinstance(raw, tuple) and len(raw) == 3:
                raw_value, raw_status, raw_error = raw
                normalized_status = str(raw_status or "ERROR").upper()
                if normalized_status == "OK" and raw_value is not None:
                    status = PollingResultStatus.OK
                    value = {"numeric": float(raw_value), "text": None, "raw": raw_value}
                    error = {"code": None, "message": None, "retryable": False}
                elif normalized_status == "TIMEOUT":
                    status = PollingResultStatus.TIMEOUT
                    error = {"code": "timeout", "message": raw_error or "SNMP request timed out", "retryable": True}
                elif normalized_status == "NO_DATA":
                    status = PollingResultStatus.NO_DATA
                    error = {"code": "no_data", "message": raw_error or "SNMP returned no data", "retryable": True}
                elif normalized_status == "ERROR" and is_snmp_no_response_failure(
                    PollingProtocol.SNMP,
                    normalized_status,
                    {"message": raw_error},
                ):
                    message = raw_error or "SNMP request timed out"
                    if "no data" in str(message).lower():
                        status = PollingResultStatus.NO_DATA
                        error = {"code": "no_data", "message": message, "retryable": True}
                    else:
                        status = PollingResultStatus.TIMEOUT
                        error = {"code": "timeout", "message": message, "retryable": True}
                else:
                    status = PollingResultStatus.ERROR
                    error = {"code": "snmp_error", "message": raw_error or "SNMP collection failed", "retryable": True}
            elif raw is None:
                status = PollingResultStatus.NO_DATA
                error = {"code": "no_data", "message": "SNMP returned no data", "retryable": True}
            else:
                status = PollingResultStatus.OK
                value = {"numeric": float(raw), "text": None, "raw": raw}
                error = {"code": None, "message": None, "retryable": False}
        else:
            raise ValueError(f"Unsupported SNMP leased worker protocol: {protocol.value}")
    except Exception as exc:
        status = PollingResultStatus.ERROR
        error = {"code": "executor_error", "message": str(exc), "retryable": True}

    finished = _utc_now()
    task_id = _get(task, "task_id")
    cycle_id = _get(task, "cycle_id")
    ci_id = str(_get(task, "ci_id"))
    source = str(_get(task, "source") or payload.get("target") or "")
    icmp_result_metadata: dict[str, Any] = {}
    if protocol == PollingProtocol.ICMP:
        if measurement is not None:
            icmp_result_metadata = {"metric_kind": "availability", "icmp": icmp_metadata(measurement)}
        elif is_icmp_telemetry_metric(metric_id, task_metadata):
            icmp_result_metadata = {"metric_kind": "telemetry"}
    return PollResultEnvelope(
        result_id=_result_id(task_id, observed, status),
        task_id=task_id,
        cycle_id=cycle_id,
        idempotency_key=generate_idempotency_key(
            ci_id=ci_id,
            metric_id=metric_id,
            protocol=protocol,
            source=source,
            observed_at=observed,
            cycle_id=cycle_id,
            result_kind=status.value.lower(),
        ),
        ci_id=ci_id,
        metric_id=metric_id,
        protocol=protocol,
        source=source,
        observed_at=observed,
        received_at=finished,
        status=status,
        worker_id=worker_id,
        value=value,
        error=error,
        metadata={
            **icmp_result_metadata,
            "site_id": _get(task, "site_id"),
            "subnet": _get(task, "subnet"),
            "ip_address": _get(task, "ip_address"),
            "credential_ref": _get(task, "credential_ref"),
            "endpoint": _get(task, "endpoint"),
            "metadata_version": _get(task, "metadata_version"),
            "worker_id": worker_id,
        },
        timing={
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_ms": round((time.monotonic() - started_monotonic) * 1000, 3),
        },
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def result_to_queue_row(result: PollResultEnvelope, *, priority: int = 50, partition_key: int = 0) -> dict[str, Any]:
    """Convert an envelope to `poll_result_queue` insert helper shape."""
    envelope = _jsonable(asdict(result))
    return {
        "result_id": result.result_id,
        "task_id": result.task_id,
        "cycle_id": result.cycle_id,
        "idempotency_key": result.idempotency_key,
        "protocol": result.protocol,
        "ci_id": result.ci_id,
        "metric_id": result.metric_id,
        "observed_at": result.observed_at,
        "received_at": result.received_at,
        "status": result.status,
        "priority": priority,
        "partition_key": partition_key,
        "envelope": envelope,
    }
