"""PostgreSQL queue helpers for scalable metric polling.

These helpers are inert until later feature flags wire them into workers. They
keep queue SQL in one place so PR2 can test leases without changing runtime
startup behavior.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Mapping
from uuid import UUID

from sqlalchemy import text


def _value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    return value


def _json(value: Any) -> str:
    return json.dumps(value or {})


def _rows(result) -> list[Any]:
    return list(result)


def create_cycle(db, *, cycle_id: UUID | str, scheduled_for: datetime, config_version: str | None = None, target_task_count: int = 0, status: str = "open") -> None:
    db.execute(text("""
        INSERT INTO poll_cycles (cycle_id, scheduled_for, status, config_version, target_task_count)
        VALUES (:cycle_id, :scheduled_for, :status, :config_version, :target_task_count)
        ON CONFLICT (cycle_id) DO UPDATE SET
            scheduled_for = EXCLUDED.scheduled_for,
            status = EXCLUDED.status,
            config_version = EXCLUDED.config_version,
            target_task_count = EXCLUDED.target_task_count,
            updated_at = now()
    """), {
        "cycle_id": _value(cycle_id),
        "scheduled_for": scheduled_for,
        "status": status,
        "config_version": config_version,
        "target_task_count": target_task_count,
    })
    db.commit()


def enqueue_tasks(db, tasks: Iterable[Mapping[str, Any]]) -> None:
    rows = []
    for task in tasks:
        rows.append({
            "task_id": _value(task["task_id"]),
            "cycle_id": _value(task["cycle_id"]),
            "ci_id": task["ci_id"],
            "metric_id": task["metric_id"],
            "protocol": _value(task["protocol"]),
            "priority": int(task.get("priority", 50)),
            "due_at": task["due_at"],
            "next_eligible_at": task.get("next_eligible_at", task["due_at"]),
            "partition_key": int(task.get("partition_key", 0)),
            "site_id": task.get("site_id"),
            "subnet": task.get("subnet"),
            "ip_address": task.get("ip_address"),
            "credential_ref": task.get("credential_ref"),
            "endpoint": task.get("endpoint"),
            "source": task.get("source"),
            "payload": _json(task.get("payload")),
            "metadata_version": task.get("metadata_version"),
        })
    if not rows:
        return
    db.execute(text("""
        INSERT INTO poll_task_queue (
            task_id, cycle_id, ci_id, metric_id, protocol, priority, due_at,
            next_eligible_at, partition_key, site_id, subnet, ip_address,
            credential_ref, endpoint, source, payload, metadata_version
        ) VALUES (
            :task_id, :cycle_id, :ci_id, :metric_id, :protocol, :priority, :due_at,
            :next_eligible_at, :partition_key, :site_id, :subnet, :ip_address,
            :credential_ref, :endpoint, :source, CAST(:payload AS jsonb), :metadata_version
        ) ON CONFLICT (task_id) DO NOTHING
    """), rows)
    db.commit()


def enqueue_results(db, results: Iterable[Mapping[str, Any]]) -> None:
    rows = []
    for result in results:
        rows.append({
            "result_id": _value(result["result_id"]),
            "task_id": _value(result["task_id"]),
            "cycle_id": _value(result["cycle_id"]),
            "idempotency_key": result["idempotency_key"],
            "protocol": _value(result["protocol"]),
            "ci_id": result["ci_id"],
            "metric_id": result["metric_id"],
            "observed_at": result["observed_at"],
            "received_at": result["received_at"],
            "status": _value(result.get("status", "ready")),
            "priority": int(result.get("priority", 50)),
            "partition_key": int(result.get("partition_key", 0)),
            "envelope": _json(result["envelope"]),
        })
    if not rows:
        return
    db.execute(text("""
        INSERT INTO poll_result_queue (
            result_id, task_id, cycle_id, idempotency_key, protocol, ci_id,
            metric_id, observed_at, received_at, status, priority,
            partition_key, envelope
        ) VALUES (
            :result_id, :task_id, :cycle_id, :idempotency_key, :protocol, :ci_id,
            :metric_id, :observed_at, :received_at, :status, :priority,
            :partition_key, CAST(:envelope AS jsonb)
        ) ON CONFLICT (idempotency_key) DO NOTHING
    """), rows)
    db.commit()


def claim_tasks(db, *, protocol: str, worker_id: str, lease_ttl_seconds: int, batch_size: int, worker_partitions: list[int] | None = None) -> list[Any]:
    result = db.execute(text("""
        WITH claim AS (
            SELECT task_id
            FROM poll_task_queue
            WHERE (
                    (
                        status IN ('available', 'retry_wait', 'deferred')
                        AND next_eligible_at <= now()
                    )
                    OR (status = 'leased' AND lease_expires_at <= now())
                  )
              AND protocol = :protocol
              AND (:worker_partitions IS NULL OR partition_key = ANY(:worker_partitions))
            ORDER BY priority ASC, next_eligible_at ASC, task_id ASC
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        UPDATE poll_task_queue t
        SET status = 'leased',
            lease_owner = :worker_id,
            lease_expires_at = now() + (:lease_ttl_seconds * interval '1 second'),
            lease_attempts = lease_attempts + 1,
            updated_at = now()
        FROM claim
        WHERE t.task_id = claim.task_id
        RETURNING t.*
    """), {
        "protocol": protocol,
        "worker_id": worker_id,
        "lease_ttl_seconds": lease_ttl_seconds,
        "batch_size": batch_size,
        "worker_partitions": worker_partitions,
    })
    return _rows(result)


def claim_results(db, *, worker_id: str, lease_ttl_seconds: int, batch_size: int, writer_partitions: list[int] | None = None) -> list[Any]:
    result = db.execute(text("""
        WITH claim AS (
            SELECT result_id
            FROM poll_result_queue
            WHERE (
                    status IN ('ready', 'retry_wait')
                    OR (status = 'leased' AND lease_expires_at <= now())
                  )
              AND (:writer_partitions IS NULL OR partition_key = ANY(:writer_partitions))
            ORDER BY priority ASC, received_at ASC, result_id ASC
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        UPDATE poll_result_queue r
        SET status = 'leased',
            lease_owner = :worker_id,
            lease_expires_at = now() + (:lease_ttl_seconds * interval '1 second'),
            write_attempts = write_attempts + 1,
            updated_at = now()
        FROM claim
        WHERE r.result_id = claim.result_id
        RETURNING r.*
    """), {
        "worker_id": worker_id,
        "lease_ttl_seconds": lease_ttl_seconds,
        "batch_size": batch_size,
        "writer_partitions": writer_partitions,
    })
    return _rows(result)


def _transition_task(db, task_id: UUID | str, status_sql: str, **fields: Any) -> None:
    assignments = [f"status = '{status_sql}'", "updated_at = now()"]
    params = {"task_id": _value(task_id)}
    for key, value in fields.items():
        assignments.append(f"{key} = :{key}")
        params[key] = value
    db.execute(text(f"UPDATE poll_task_queue SET {', '.join(assignments)} WHERE task_id = :task_id"), params)
    db.commit()


def complete_task(db, task_id: UUID | str) -> None:
    _transition_task(db, task_id, "completed", lease_owner=None, lease_expires_at=None)


def defer_task(db, task_id: UUID | str, *, next_eligible_at: datetime, error_code: str | None = None, error_message: str | None = None) -> None:
    _transition_task(db, task_id, "deferred", next_eligible_at=next_eligible_at, lease_owner=None, lease_expires_at=None, last_error_code=error_code, last_error_message=error_message)


def retry_task(db, task_id: UUID | str, *, next_eligible_at: datetime, error_code: str | None = None, error_message: str | None = None) -> None:
    db.execute(text("""
        UPDATE poll_task_queue
        SET status = 'retry_wait',
            next_eligible_at = :next_eligible_at,
            lease_owner = NULL,
            lease_expires_at = NULL,
            execute_attempts = execute_attempts + 1,
            last_error_code = :last_error_code,
            last_error_message = :last_error_message,
            updated_at = now()
        WHERE task_id = :task_id
    """), {
        "task_id": _value(task_id),
        "next_eligible_at": next_eligible_at,
        "last_error_code": error_code,
        "last_error_message": error_message,
    })
    db.commit()


def dead_letter_task(db, task_id: UUID | str, *, reason: str, error_code: str | None = None, error_message: str | None = None) -> None:
    _transition_task(db, task_id, "dead_letter", lease_owner=None, lease_expires_at=None, dead_letter_reason=reason, last_error_code=error_code, last_error_message=error_message)


def complete_result(db, result_id: UUID | str) -> None:
    db.execute(text("""
        UPDATE poll_result_queue
        SET status = 'written', lease_owner = NULL, lease_expires_at = NULL, updated_at = now()
        WHERE result_id = :result_id
    """), {"result_id": _value(result_id)})
    db.commit()


def renew_task_lease(db, task_id: UUID | str, *, worker_id: str, lease_ttl_seconds: int) -> None:
    db.execute(text("""
        UPDATE poll_task_queue
        SET lease_owner = :worker_id,
            lease_expires_at = now() + (:lease_ttl_seconds * interval '1 second'),
            updated_at = now()
        WHERE task_id = :task_id AND lease_owner = :worker_id
    """), {"task_id": _value(task_id), "worker_id": worker_id, "lease_ttl_seconds": lease_ttl_seconds})
    db.commit()


def expire_task_leases(db) -> None:
    db.execute(text("""
        UPDATE poll_task_queue
        SET status = 'retry_wait', lease_owner = NULL, lease_expires_at = NULL, updated_at = now()
        WHERE status = 'leased' AND lease_expires_at <= now()
    """))
    db.commit()


def retry_result(db, result_id: UUID | str, *, next_eligible_at: datetime, error_code: str | None = None, error_message: str | None = None) -> None:
    db.execute(text("""
        UPDATE poll_result_queue
        SET status = 'retry_wait',
            received_at = :next_eligible_at,
            lease_owner = NULL,
            lease_expires_at = NULL,
            last_error_code = :last_error_code,
            last_error_message = :last_error_message,
            updated_at = now()
        WHERE result_id = :result_id
    """), {
        "result_id": _value(result_id),
        "next_eligible_at": next_eligible_at,
        "last_error_code": error_code,
        "last_error_message": error_message,
    })
    db.commit()


def dead_letter_result(db, result_id: UUID | str, *, reason: str, error_code: str | None = None, error_message: str | None = None) -> None:
    db.execute(text("""
        UPDATE poll_result_queue
        SET status = 'dead_letter',
            lease_owner = NULL,
            lease_expires_at = NULL,
            dead_letter_reason = :dead_letter_reason,
            last_error_code = :last_error_code,
            last_error_message = :last_error_message,
            updated_at = now()
        WHERE result_id = :result_id
    """), {
        "result_id": _value(result_id),
        "dead_letter_reason": reason,
        "last_error_code": error_code,
        "last_error_message": error_message,
    })
    db.commit()


def expire_result_leases(db) -> None:
    db.execute(text("""
        UPDATE poll_result_queue
        SET status = 'retry_wait', lease_owner = NULL, lease_expires_at = NULL, updated_at = now()
        WHERE status = 'leased' AND lease_expires_at <= now()
    """))
    db.commit()
