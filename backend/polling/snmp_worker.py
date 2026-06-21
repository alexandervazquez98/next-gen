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


def _envelope_severity(result) -> str:
    """Derive a severity string for a leased-worker envelope.

    Used as the `severity` argument to `resolve_correlation_fields`. The
    resolver currently treats severity as informational, but keeping a sensible
    value here makes the call site self-documenting and matches the Path A
    pattern (`_tag_failure_with_correlation` derives severity from the row).
    """
    status = getattr(result, "status", None)
    if status == PollingResultStatus.CRITICAL:
        return "CRITICAL"
    if status == PollingResultStatus.WARNING:
        return "WARNING"
    if status in {PollingResultStatus.TIMEOUT, PollingResultStatus.NO_DATA, PollingResultStatus.ERROR}:
        # Collection failures derive severity from metadata.criticality in the
        # writer; mirror Path A's fallback to "WARNING" here for the resolver.
        metadata = getattr(result, "metadata", {}) or {}
        criticality = metadata.get("criticality")
        try:
            normalized = int(criticality or 0)
        except (TypeError, ValueError):
            normalized = 0
        if normalized >= 3:
            return "CRITICAL"
        if normalized == 2:
            return "WARNING"
        return "WARNING"
    return "INFO"


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

    # Per-cycle memo cache for `resolve_correlation_fields` (REQ-CORR-2).
    # Shared across all claims in this single worker iteration so duplicate
    # CIs within the cycle only re-traverse the topology once (~5s TTL).
    correlation_cache: dict[str, tuple] = {}

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

                # Path C pre-tag (REQ-CORR-2): stamp correlation fields onto
                # the envelope metadata BEFORE the envelope is enqueued. The
                # writer (`event_writer.build_event_rows`) preserves these
                # fields via `metadata.get("correlation_type")` /
                # `metadata.get("propagated_from")` / `metadata.get(
                # "root_cause_ci_id")`, so pre-tagging here is what the writer
                # needs to persist ROOT vs PROPAGATED for Path C.
                from services.event_service import resolve_correlation_fields

                ci_id = str(getattr(result, "ci_id", "") or task.get("ci_id") or "")
                severity = _envelope_severity(result)
                if ci_id:
                    correlation = resolve_correlation_fields(
                        ci_id,
                        severity,
                        cache=correlation_cache,
                    )
                    metadata = getattr(result, "metadata", None)
                    if not isinstance(metadata, dict):
                        metadata = {}
                        try:
                            result.metadata = metadata
                        except Exception:
                            metadata = None
                    if metadata is not None:
                        metadata["correlation_type"] = correlation["correlation_type"]
                        metadata["propagated_from"] = correlation["propagated_from"]
                        metadata["root_cause_ci_id"] = correlation["root_cause_ci_id"]

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
