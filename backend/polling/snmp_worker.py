"""Flagged leased SNMP/ICMP worker loop for the scalable polling path."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from polling import pg_queue
from polling.contracts import PollingProtocol, PollingResultStatus
from polling.safety_limits import ActiveSafetyLimiter
from polling.snmp_executor import execute_poll_task, result_to_queue_row


DEFAULT_STATS = {"claimed": 0, "enqueued": 0, "deferred": 0, "retried": 0, "completed": 0}


def _get(row: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _task_dict(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    keys = (
        "task_id", "cycle_id", "ci_id", "metric_id", "protocol", "priority", "source", "partition_key",
        "payload", "site_id", "subnet", "ip_address", "credential_ref", "endpoint", "metadata_version",
    )
    return {key: _get(row, key) for key in keys if _get(row, key) is not None}


def _next_retry(now: datetime, seconds: int = 60) -> datetime:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now + timedelta(seconds=seconds)


def run_leased_snmp_worker_once(
    db,
    *,
    settings,
    worker_id: str = "snmp-worker",
    safety_limiter: Any = None,
    now: datetime | None = None,
    icmp_fetcher=None,
    snmp_fetcher=None,
) -> dict[str, int]:
    """Run one flagged leased-worker iteration.

    This function is inert unless `settings.snmp_leased_worker_enabled` is true.
    """
    stats = dict(DEFAULT_STATS)
    if not getattr(settings, "snmp_leased_worker_enabled", False):
        return stats

    safety_limiter = safety_limiter or ActiveSafetyLimiter()
    observed_at = now or datetime.now(timezone.utc)
    batch_size = int(getattr(settings, "task_batch_size", 100))
    lease_ttl = int(getattr(settings, "lease_ttl_seconds", 120))

    for protocol in (PollingProtocol.ICMP.value, PollingProtocol.SNMP.value):
        rows = pg_queue.claim_tasks(
            db,
            protocol=protocol,
            worker_id=worker_id,
            lease_ttl_seconds=lease_ttl,
            batch_size=batch_size,
        )
        stats["claimed"] += len(rows)
        for row in rows:
            task = _task_dict(row)
            decision = safety_limiter.acquire(task)
            if not decision.allowed:
                pg_queue.defer_task(
                    db,
                    task["task_id"],
                    next_eligible_at=_next_retry(observed_at, 30),
                    error_code=decision.error_code,
                    error_message=decision.reason,
                )
                stats["deferred"] += 1
                continue
            try:
                result = execute_poll_task(
                    task,
                    worker_id=worker_id,
                    observed_at=observed_at,
                    icmp_fetcher=icmp_fetcher,
                    snmp_fetcher=snmp_fetcher,
                )
                pg_queue.enqueue_results(db, [
                    result_to_queue_row(
                        result,
                        priority=int(task.get("priority", 50)),
                        partition_key=int(task.get("partition_key", 0)),
                    )
                ])
                stats["enqueued"] += 1
                if result.status in {PollingResultStatus.OK, PollingResultStatus.CRITICAL}:
                    pg_queue.complete_task(db, task["task_id"])
                    stats["completed"] += 1
                else:
                    pg_queue.retry_task(
                        db,
                        task["task_id"],
                        next_eligible_at=_next_retry(observed_at),
                        error_code=result.error.get("code"),
                        error_message=result.error.get("message"),
                    )
                    stats["retried"] += 1
            finally:
                safety_limiter.release(task)
    return stats
