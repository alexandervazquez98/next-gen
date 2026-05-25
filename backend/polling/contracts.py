"""Shared contracts for the scalable polling pipeline.

These types are intentionally side-effect free: they do not claim queues,
poll devices, or write databases. Later SDD slices reuse them when adding the
PostgreSQL queue, leased workers, and writer pool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
from typing import Any, cast
from uuid import UUID


class PollingProtocol(str, Enum):
    """Supported polling protocol contract names.

    MQTT_STUB is an extension point for capacity modeling only; production MQTT
    semantics remain out of scope for PR 1.
    """

    ICMP = "ICMP"
    SNMP = "SNMP"
    CLI = "CLI"
    REST = "REST"
    MQTT_STUB = "MQTT_STUB"


class PollingPriority(IntEnum):
    """Lower values are claimed first by future queue workers."""

    ICMP_AVAILABILITY = 0
    HIGH_CRITICALITY = 10
    NORMAL = 50
    COOLDOWN = 90


class PollingTaskStatus(str, Enum):
    AVAILABLE = "available"
    LEASED = "leased"
    DEFERRED = "deferred"
    COMPLETED = "completed"
    RETRY_WAIT = "retry_wait"
    DEAD_LETTER = "dead_letter"


class PollingResultStatus(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    NO_DATA = "NO_DATA"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


def _coerce_protocol(protocol: PollingProtocol | str) -> PollingProtocol:
    try:
        return protocol if isinstance(protocol, PollingProtocol) else PollingProtocol(str(protocol).upper())
    except ValueError as exc:
        raise ValueError(f"Unsupported polling protocol: {protocol}") from exc


def _coerce_result_status(status: PollingResultStatus | str) -> PollingResultStatus:
    try:
        return status if isinstance(status, PollingResultStatus) else PollingResultStatus(str(status).upper())
    except ValueError as exc:
        raise ValueError(f"Unsupported polling result status: {status}") from exc


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class PollTask:
    task_id: UUID
    cycle_id: UUID
    ci_id: str
    metric_id: str
    protocol: PollingProtocol | str
    source: str
    priority: PollingPriority | int | None = None
    status: PollingTaskStatus | str = PollingTaskStatus.AVAILABLE
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    worker_id: str | None = None

    def __post_init__(self) -> None:
        self.protocol = _coerce_protocol(self.protocol)
        self.status = self.status if isinstance(self.status, PollingTaskStatus) else PollingTaskStatus(str(self.status))
        if self.priority is None:
            self.priority = (
                PollingPriority.ICMP_AVAILABILITY
                if self.protocol == PollingProtocol.ICMP
                else PollingPriority.NORMAL
            )
        elif not isinstance(self.priority, PollingPriority):
            self.priority = PollingPriority(int(self.priority))

    def log_context(self) -> dict[str, str | None]:
        protocol = cast(PollingProtocol, self.protocol)
        return {
            "cycle_id": str(self.cycle_id),
            "task_id": str(self.task_id),
            "ci_id": self.ci_id,
            "metric_id": self.metric_id,
            "protocol": protocol.value,
            "worker_id": self.worker_id,
        }


@dataclass(slots=True)
class PollResultEnvelope:
    result_id: UUID
    task_id: UUID
    cycle_id: UUID
    idempotency_key: str
    ci_id: str
    metric_id: str
    protocol: PollingProtocol | str
    source: str
    observed_at: datetime
    received_at: datetime = field(default_factory=_utc_now)
    status: PollingResultStatus | str = PollingResultStatus.OK
    worker_id: str | None = None
    value: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    timing: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.protocol = _coerce_protocol(self.protocol)
        self.status = _coerce_result_status(self.status)

    def log_context(self) -> dict[str, str | None]:
        protocol = cast(PollingProtocol, self.protocol)
        return {
            "cycle_id": str(self.cycle_id),
            "task_id": str(self.task_id),
            "result_id": str(self.result_id),
            "idempotency_key": self.idempotency_key,
            "ci_id": self.ci_id,
            "metric_id": self.metric_id,
            "protocol": protocol.value,
            "worker_id": self.worker_id,
        }
