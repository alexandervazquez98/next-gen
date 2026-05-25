"""Backpressure and retry policy primitives for scalable polling.

PR6 keeps this module side-effect-light: policy evaluation is pure, and the
optional apply helpers only translate decisions into existing durable queue
state transitions. Runtime wiring remains feature-flagged/out of scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from uuid import UUID

from polling import pg_queue
from polling.contracts import PollingPriority, PollingProtocol


@dataclass(frozen=True, slots=True)
class BackpressureConfig:
    max_task_queue_depth: int = 100_000
    max_task_queue_age_seconds: int = 900
    max_result_queue_age_seconds: int = 300
    max_writer_lag_seconds: int = 120
    max_db_latency_ms: int = 2_000
    max_protocol_failure_rate: float = 0.5
    max_worker_saturation: float = 0.9
    retry_base_seconds: int = 60
    retry_max_seconds: int = 900
    retry_max_attempts: int = 5
    circuit_failure_threshold: int = 3
    circuit_cooldown_seconds: int = 300
    pressure_defer_seconds: int = 60

    @classmethod
    def from_settings(cls, settings: Any) -> "BackpressureConfig":
        return cls(
            max_task_queue_depth=int(getattr(settings, "backpressure_max_task_queue_depth", cls.max_task_queue_depth)),
            max_writer_lag_seconds=int(getattr(settings, "backpressure_max_writer_lag_seconds", cls.max_writer_lag_seconds)),
            retry_max_attempts=int(getattr(settings, "backpressure_retry_max_attempts", cls.retry_max_attempts)),
        )


@dataclass(frozen=True, slots=True)
class BackpressureSignals:
    task_queue_depth: int = 0
    oldest_task_age_seconds: int = 0
    result_queue_age_seconds: int = 0
    writer_lag_seconds: int = 0
    db_write_latency_ms: int = 0
    protocol_failure_rate: float = 0.0
    worker_saturation: float = 0.0


@dataclass(frozen=True, slots=True)
class BackpressureReason:
    code: str
    message: str
    value: float | int | None = None
    threshold: float | int | None = None


@dataclass(frozen=True, slots=True)
class BackpressureDecision:
    action: str
    reasons: list[BackpressureReason] = field(default_factory=list)
    next_eligible_at: datetime | None = None
    dead_letter_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    protected_priority: bool = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get(row: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    return row.get(key, default) if isinstance(row, Mapping) else getattr(row, key, default)


def _protocol(task: Mapping[str, Any] | Any) -> str:
    value = _get(task, "protocol", "")
    return value.value if isinstance(value, PollingProtocol) else str(value).upper()


def _priority(task: Mapping[str, Any] | Any) -> int:
    value = _get(task, "priority", PollingPriority.NORMAL)
    return int(value)


def _is_icmp_protected(task: Mapping[str, Any] | Any) -> bool:
    return _protocol(task) == PollingProtocol.ICMP.value or _priority(task) == int(PollingPriority.ICMP_AVAILABILITY)


def _pressure_reasons(signals: BackpressureSignals, config: BackpressureConfig) -> list[BackpressureReason]:
    reasons: list[BackpressureReason] = []
    checks = (
        ("task_queue_depth", signals.task_queue_depth, config.max_task_queue_depth, ">"),
        ("task_queue_age", signals.oldest_task_age_seconds, config.max_task_queue_age_seconds, ">"),
        ("result_queue_age", signals.result_queue_age_seconds, config.max_result_queue_age_seconds, ">"),
        ("writer_lag", signals.writer_lag_seconds, config.max_writer_lag_seconds, ">"),
        ("db_latency", signals.db_write_latency_ms, config.max_db_latency_ms, ">"),
        ("protocol_failure_rate", signals.protocol_failure_rate, config.max_protocol_failure_rate, ">"),
        ("worker_saturation", signals.worker_saturation, config.max_worker_saturation, ">"),
    )
    for code, value, threshold, _ in checks:
        if value > threshold:
            reasons.append(BackpressureReason(code=code, message=f"{code} exceeded threshold", value=value, threshold=threshold))
    return reasons


def evaluate_backpressure(
    task: Mapping[str, Any] | Any,
    signals: BackpressureSignals,
    *,
    config: BackpressureConfig | None = None,
    now: datetime | None = None,
) -> BackpressureDecision:
    """Return an allow/defer decision for current pressure without dropping work."""
    config = config or BackpressureConfig()
    reasons = _pressure_reasons(signals, config)
    if not reasons:
        return BackpressureDecision(action="allow")

    if _is_icmp_protected(task) and not any(r.code == "protocol_failure_rate" for r in reasons):
        return BackpressureDecision(
            action="allow",
            reasons=[*reasons, BackpressureReason("icmp_priority_protected", "ICMP/PING-CHECK protected under pressure")],
            protected_priority=True,
        )

    next_eligible_at = (now or _utc_now()) + timedelta(seconds=config.pressure_defer_seconds)
    return BackpressureDecision(
        action="defer",
        reasons=reasons,
        next_eligible_at=next_eligible_at,
        error_code="backpressure",
        error_message=", ".join(reason.code for reason in reasons),
    )


def retry_decision(
    task: Mapping[str, Any] | Any,
    *,
    config: BackpressureConfig | None = None,
    now: datetime | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> BackpressureDecision:
    """Return retry/cooldown/dead-letter decision for repeated failures."""
    config = config or BackpressureConfig()
    now = now or _utc_now()
    attempts = int(_get(task, "execute_attempts", _get(task, "write_attempts", 0)) or 0)
    code = error_code or str(_get(task, "last_error_code", "error") or "error")

    if attempts >= config.retry_max_attempts:
        return BackpressureDecision(
            action="dead_letter",
            dead_letter_reason=f"max_attempts_exceeded:{code}",
            error_code=code,
            error_message=error_message,
        )
    if attempts >= config.circuit_failure_threshold:
        return BackpressureDecision(
            action="circuit_open",
            next_eligible_at=now + timedelta(seconds=config.circuit_cooldown_seconds),
            error_code="circuit_open",
            error_message=error_message or f"Circuit opened after {attempts} attempts",
        )

    backoff = min(config.retry_max_seconds, config.retry_base_seconds * (2 ** max(attempts, 0)))
    return BackpressureDecision(
        action="retry_wait",
        next_eligible_at=now + timedelta(seconds=backoff),
        error_code=code,
        error_message=error_message,
    )


def apply_task_decision(db, task_id: UUID | str, decision: BackpressureDecision) -> None:
    """Persist a task decision using queue helpers; allow/throttle are no-ops."""
    if decision.action == "defer":
        pg_queue.defer_task(
            db,
            task_id,
            next_eligible_at=decision.next_eligible_at or _utc_now(),
            error_code=decision.error_code,
            error_message=decision.error_message,
        )
    elif decision.action in {"retry_wait", "circuit_open"}:
        pg_queue.retry_task(
            db,
            task_id,
            next_eligible_at=decision.next_eligible_at or _utc_now(),
            error_code=decision.error_code,
            error_message=decision.error_message,
        )
    elif decision.action == "dead_letter":
        pg_queue.dead_letter_task(
            db,
            task_id,
            reason=decision.dead_letter_reason or "backpressure_dead_letter",
            error_code=decision.error_code,
            error_message=decision.error_message,
        )
