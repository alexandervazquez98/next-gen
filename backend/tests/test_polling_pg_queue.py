from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4


class FakeSession:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = rows or []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return self.rows

    def commit(self):
        self.calls.append(("COMMIT", {}))


def _latest_sql(session):
    return session.calls[-1][0]


def test_claim_tasks_uses_skip_locked_expired_lease_reclaim_and_bounded_batch():
    from polling.pg_queue import claim_tasks

    session = FakeSession(rows=[SimpleNamespace(task_id="task-1")])
    rows = claim_tasks(
        session,
        protocol="SNMP",
        worker_id="worker-a",
        lease_ttl_seconds=30,
        batch_size=25,
        worker_partitions=[1, 2],
    )

    assert len(rows) == 1
    sql = _latest_sql(session)
    params = session.calls[-1][1]
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "status = 'leased'" in sql
    assert "lease_expires_at <= now()" in sql
    assert "lease_attempts = lease_attempts + 1" in sql
    assert "ORDER BY priority ASC" in sql
    assert params["protocol"] == "SNMP"
    assert params["worker_id"] == "worker-a"
    assert params["batch_size"] == 25
    assert params["worker_partitions"] == [1, 2]


def test_claim_results_uses_unique_writer_leases_and_retry_wait():
    from polling.pg_queue import claim_results

    session = FakeSession(rows=[SimpleNamespace(result_id="result-1")])
    claim_results(session, worker_id="writer-a", lease_ttl_seconds=45, batch_size=100, writer_partitions=[3])

    sql = _latest_sql(session)
    params = session.calls[-1][1]
    assert "FROM poll_result_queue" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "status IN ('ready', 'retry_wait')" in sql
    assert "write_attempts = write_attempts + 1" in sql
    assert params["worker_id"] == "writer-a"
    assert params["batch_size"] == 100


def test_create_cycle_and_enqueue_helpers_commit_durable_rows():
    from polling.pg_queue import create_cycle, enqueue_results, enqueue_tasks

    session = FakeSession()
    cycle_id = uuid4()
    scheduled_for = datetime.now(timezone.utc)
    create_cycle(session, cycle_id=cycle_id, scheduled_for=scheduled_for, config_version="v1", target_task_count=2)
    enqueue_tasks(session, [{
        "task_id": uuid4(),
        "cycle_id": cycle_id,
        "ci_id": "ci-1",
        "metric_id": "PING-CHECK",
        "protocol": "ICMP",
        "priority": 0,
        "due_at": scheduled_for,
        "next_eligible_at": scheduled_for,
        "partition_key": 1,
        "source": "10.0.0.1",
        "payload": {"kind": "ping"},
    }])
    enqueue_results(session, [{
        "result_id": uuid4(),
        "task_id": uuid4(),
        "cycle_id": cycle_id,
        "idempotency_key": "idem-1",
        "protocol": "ICMP",
        "ci_id": "ci-1",
        "metric_id": "PING-CHECK",
        "observed_at": scheduled_for,
        "received_at": scheduled_for,
        "status": "OK",
        "priority": 0,
        "partition_key": 1,
        "envelope": {"value": 1},
    }])

    executed = "\n".join(sql for sql, _ in session.calls)
    assert "INSERT INTO poll_cycles" in executed
    assert "INSERT INTO poll_task_queue" in executed
    assert "INSERT INTO poll_result_queue" in executed
    assert executed.count("COMMIT") == 3


def test_state_transition_helpers_preserve_error_and_dead_letter_reason():
    from polling.pg_queue import complete_task, dead_letter_task, defer_task, retry_task

    session = FakeSession()
    task_id = uuid4()
    retry_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    complete_task(session, task_id)
    defer_task(session, task_id, next_eligible_at=retry_at, error_code="cap", error_message="site cap")
    retry_task(session, task_id, next_eligible_at=retry_at, error_code="timeout", error_message="snmp timeout")
    dead_letter_task(session, task_id, reason="max retries", error_code="timeout")

    executed = "\n".join(sql for sql, _ in session.calls)
    assert "SET status = 'completed'" in executed
    assert "SET status = 'deferred'" in executed
    assert "SET status = 'retry_wait'" in executed
    assert "SET status = 'dead_letter'" in executed
    assert "dead_letter_reason" in executed


def test_lease_renew_expire_and_result_transition_helpers():
    from polling.pg_queue import (
        complete_result,
        dead_letter_result,
        expire_result_leases,
        expire_task_leases,
        renew_task_lease,
        retry_result,
    )

    session = FakeSession()
    task_id = uuid4()
    result_id = uuid4()
    retry_at = datetime.now(timezone.utc) + timedelta(minutes=1)

    renew_task_lease(session, task_id, worker_id="worker-a", lease_ttl_seconds=60)
    expire_task_leases(session)
    complete_result(session, result_id)
    retry_result(session, result_id, next_eligible_at=retry_at, error_code="db", error_message="slow")
    dead_letter_result(session, result_id, reason="bad envelope", error_code="invalid")
    expire_result_leases(session)

    executed = "\n".join(sql for sql, _ in session.calls)
    assert "lease_owner = :worker_id" in executed
    assert "WHERE task_id = :task_id AND lease_owner = :worker_id" in executed
    assert "status = 'retry_wait'" in executed
    assert "status = 'written'" in executed
    assert "UPDATE poll_result_queue" in executed
    assert "dead_letter_reason" in executed
