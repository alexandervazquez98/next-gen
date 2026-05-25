from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4


class FakeSettings:
    def __init__(self, enabled=False):
        self.snmp_leased_worker_enabled = enabled
        self.task_batch_size = 10


class FakeLimiter:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.released = []

    def acquire(self, task):
        return SimpleNamespace(allowed=self.allowed, reason="cap reached", error_code="safety_limit")

    def release(self, task):
        self.released.append(task["task_id"])


def _row(protocol="SNMP"):
    return SimpleNamespace(
        task_id=uuid4(),
        cycle_id=uuid4(),
        ci_id="ci-1",
        metric_id="CPU" if protocol == "SNMP" else "PING-CHECK",
        protocol=protocol,
        priority=50 if protocol == "SNMP" else 0,
        source="10.0.0.1:161/1.2.3" if protocol == "SNMP" else "10.0.0.1",
        partition_key=1,
        payload={"kind": "snmp_get", "target": "10.0.0.1", "oid": "1.2.3", "community": "public", "port": 161}
        if protocol == "SNMP" else {"kind": "icmp_ping", "target": "10.0.0.1"},
    )


def test_leased_worker_noops_when_flag_disabled(monkeypatch):
    from polling import snmp_worker

    calls = []
    monkeypatch.setattr(snmp_worker.pg_queue, "claim_tasks", lambda *args, **kwargs: calls.append("claim"))

    stats = snmp_worker.run_leased_snmp_worker_once(object(), settings=FakeSettings(enabled=False))

    assert stats == {"claimed": 0, "enqueued": 0, "deferred": 0, "retried": 0, "completed": 0}
    assert calls == []


def test_leased_worker_claims_executes_enqueues_and_completes(monkeypatch):
    from polling import snmp_worker

    claimed = [_row("ICMP"), _row("SNMP")]
    enqueued = []
    completed = []

    def fake_claim(db, *, protocol, **kwargs):
        return [row for row in claimed if row.protocol == protocol]

    monkeypatch.setattr(snmp_worker.pg_queue, "claim_tasks", fake_claim)
    monkeypatch.setattr(snmp_worker.pg_queue, "enqueue_results", lambda db, rows: enqueued.extend(rows))
    monkeypatch.setattr(snmp_worker.pg_queue, "complete_task", lambda db, task_id: completed.append(task_id))
    monkeypatch.setattr(snmp_worker.pg_queue, "retry_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(snmp_worker.pg_queue, "defer_task", lambda *args, **kwargs: None)

    stats = snmp_worker.run_leased_snmp_worker_once(
        object(),
        settings=FakeSettings(enabled=True),
        worker_id="worker-a",
        safety_limiter=FakeLimiter(True),
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        icmp_fetcher=lambda **kwargs: 1.0,
        snmp_fetcher=lambda **kwargs: 42.0,
    )

    assert stats["claimed"] == 2
    assert stats["enqueued"] == 2
    assert stats["completed"] == 2
    assert len(enqueued) == 2
    assert {row["protocol"] for row in enqueued} == {"ICMP", "SNMP"}
    assert len(completed) == 2


def test_leased_worker_defers_when_safety_limit_denies(monkeypatch):
    from polling import snmp_worker

    deferred = []
    monkeypatch.setattr(
        snmp_worker.pg_queue,
        "claim_tasks",
        lambda *args, **kwargs: [_row("SNMP")] if kwargs["protocol"] == "SNMP" else [],
    )
    monkeypatch.setattr(snmp_worker.pg_queue, "enqueue_results", lambda *args, **kwargs: None)
    monkeypatch.setattr(snmp_worker.pg_queue, "defer_task", lambda db, task_id, **kwargs: deferred.append((task_id, kwargs)))

    stats = snmp_worker.run_leased_snmp_worker_once(
        object(), settings=FakeSettings(enabled=True), safety_limiter=FakeLimiter(False)
    )

    assert stats["claimed"] == 1
    assert stats["deferred"] == 1
    assert deferred[0][1]["error_code"] == "safety_limit"
