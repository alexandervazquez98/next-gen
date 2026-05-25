"""Pure scheduler expansion helpers for the scalable polling pipeline."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

from polling.contracts import PollingPriority, PollingProtocol
from polling.pg_queue import create_cycle, enqueue_tasks
from polling.protocol_contracts import build_protocol_payload


@dataclass(frozen=True, slots=True)
class PollCycle:
    cycle_id: UUID
    scheduled_for: datetime
    config_version: str | None = None
    target_cycle_seconds: int = 900


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_cycle(
    *,
    scheduled_for: datetime,
    config_version: str | None = None,
    target_cycle_seconds: int = 900,
    cycle_id: UUID | None = None,
) -> PollCycle:
    """Build deterministic cycle metadata for a scheduled polling window."""
    scheduled_utc = _utc(scheduled_for)
    if cycle_id is None:
        cycle_id = uuid5(NAMESPACE_URL, f"next-gen|poll-cycle|{scheduled_utc.isoformat()}|{config_version or ''}")
    return PollCycle(
        cycle_id=cycle_id,
        scheduled_for=scheduled_utc,
        config_version=config_version,
        target_cycle_seconds=target_cycle_seconds,
    )


def _protocol(record: Mapping[str, Any]) -> PollingProtocol:
    value = record.get("protocol")
    if isinstance(value, PollingProtocol):
        return value
    raw = str(value or "").strip().upper()
    if raw == "MQTT":
        raise ValueError("Production MQTT is out of scope; use MQTT_STUB")
    try:
        return PollingProtocol(raw)
    except ValueError as exc:
        raise ValueError(f"Unsupported polling protocol: {raw}") from exc


def _source(record: Mapping[str, Any], protocol: PollingProtocol) -> str:
    if protocol == PollingProtocol.SNMP:
        return f"{record.get('ip')}:{record.get('port') or record.get('snmp_port') or 161}/{record.get('oid')}"
    if protocol == PollingProtocol.ICMP:
        return str(record.get("ip") or record.get("source") or "")
    if protocol == PollingProtocol.CLI:
        return f"{record.get('ip')}:{record.get('cli_command')}"
    if protocol == PollingProtocol.REST:
        return str(record.get("endpoint") or record.get("source") or "")
    return str(record.get("source") or record.get("topic") or "mqtt_stub")


def _partition_key(*parts: Any) -> int:
    digest = hashlib.sha256("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 1024


def _task_id(cycle: PollCycle, ci_id: str, metric_id: str, protocol: PollingProtocol, source: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"next-gen|poll-task|{cycle.cycle_id}|{ci_id}|{metric_id}|{protocol.value}|{source}")


def _priority(record: Mapping[str, Any], protocol: PollingProtocol) -> PollingPriority:
    metric_id = str(record.get("metric_id") or record.get("id") or "").upper()
    if protocol == PollingProtocol.ICMP or metric_id == "PING-CHECK":
        return PollingPriority.ICMP_AVAILABILITY
    criticality = int(record.get("criticality") or 0)
    return PollingPriority.HIGH_CRITICALITY if criticality >= 3 else PollingPriority.NORMAL


def build_tasks_from_records(records: Iterable[Mapping[str, Any]], cycle: PollCycle) -> list[dict[str, Any]]:
    """Expand due metric definition records into durable queue task rows."""
    tasks: list[dict[str, Any]] = []
    for record in records:
        protocol = _protocol(record)
        ci_id = str(record.get("node_id") or record.get("ci_id") or "")
        metric_id = str(record.get("metric_id") or record.get("id") or "")
        if not ci_id or not metric_id:
            raise ValueError("Scheduler records require node_id/ci_id and metric_id/id")
        source = _source(record, protocol)
        payload = build_protocol_payload({**dict(record), "protocol": protocol.value, "source": source})
        priority = _priority(record, protocol)
        tasks.append({
            "task_id": _task_id(cycle, ci_id, metric_id, protocol, source),
            "cycle_id": cycle.cycle_id,
            "ci_id": ci_id,
            "metric_id": metric_id,
            "protocol": protocol,
            "priority": priority,
            "due_at": cycle.scheduled_for,
            "next_eligible_at": cycle.scheduled_for,
            "partition_key": _partition_key(protocol.value, record.get("site_id"), record.get("subnet"), ci_id),
            "site_id": record.get("site_id") or record.get("location_name"),
            "subnet": record.get("subnet"),
            "ip_address": record.get("ip") or record.get("ip_address"),
            "credential_ref": record.get("credential_ref") or record.get("cli_credential_ref"),
            "endpoint": record.get("endpoint") or (f"{record.get('ip')}:{record.get('port') or 161}" if protocol == PollingProtocol.SNMP else None),
            "source": source,
            "payload": payload,
            "metadata_version": record.get("metadata_version") or cycle.config_version,
        })
    return sorted(tasks, key=lambda task: (int(task["priority"]), task["protocol"].value, task["metric_id"]))


def group_tasks_by_protocol(tasks: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for task in tasks:
        protocol = task["protocol"].value if isinstance(task.get("protocol"), PollingProtocol) else str(task.get("protocol"))
        grouped.setdefault(protocol, []).append(task)
    return grouped


def has_stale_metadata(task_or_record: Mapping[str, Any], *, current_metadata_version: str | None) -> bool:
    metadata_version = task_or_record.get("metadata_version")
    return bool(metadata_version and current_metadata_version and str(metadata_version) != str(current_metadata_version))


def enqueue_cycle_tasks(db, cycle: PollCycle, tasks: Iterable[Mapping[str, Any]]) -> None:
    task_list = list(tasks)
    create_cycle(
        db,
        cycle_id=cycle.cycle_id,
        scheduled_for=cycle.scheduled_for,
        config_version=cycle.config_version,
        target_task_count=len(task_list),
    )
    enqueue_tasks(db, task_list)
