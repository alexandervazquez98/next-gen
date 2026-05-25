from datetime import datetime, timedelta, timezone
from uuid import uuid4


def _task(**overrides):
    base = {
        "task_id": uuid4(),
        "protocol": "SNMP",
        "priority": 50,
        "execute_attempts": 0,
    }
    base.update(overrides)
    return base


def test_backpressure_defers_normal_work_but_protects_icmp_priority():
    from polling.backpressure import BackpressureConfig, BackpressureSignals, evaluate_backpressure

    config = BackpressureConfig(max_task_queue_depth=100, max_writer_lag_seconds=30, max_db_latency_ms=500)
    signals = BackpressureSignals(task_queue_depth=250, writer_lag_seconds=45, db_write_latency_ms=750)

    normal = evaluate_backpressure(_task(protocol="SNMP", priority=50), signals, config=config)
    icmp = evaluate_backpressure(_task(protocol="ICMP", priority=0), signals, config=config)

    assert normal.action == "defer"
    assert normal.next_eligible_at is not None
    assert {reason.code for reason in normal.reasons} >= {"task_queue_depth", "writer_lag", "db_latency"}
    assert icmp.action == "allow"
    assert icmp.protected_priority is True
    assert any(reason.code == "icmp_priority_protected" for reason in icmp.reasons)


def test_worker_saturation_and_failure_rate_trigger_throttle_without_silent_loss():
    from polling.backpressure import BackpressureConfig, BackpressureSignals, evaluate_backpressure

    decision = evaluate_backpressure(
        _task(protocol="SNMP", priority=50),
        BackpressureSignals(protocol_failure_rate=0.75, worker_saturation=0.95),
        config=BackpressureConfig(max_protocol_failure_rate=0.5, max_worker_saturation=0.9),
    )

    assert decision.action == "defer"
    assert decision.dead_letter_reason is None
    assert {reason.code for reason in decision.reasons} == {"protocol_failure_rate", "worker_saturation"}


def test_retry_policy_backoff_cooldown_and_dead_letter_reasons():
    from polling.backpressure import BackpressureConfig, retry_decision

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    config = BackpressureConfig(
        retry_base_seconds=10,
        retry_max_seconds=120,
        circuit_failure_threshold=3,
        circuit_cooldown_seconds=300,
        retry_max_attempts=5,
    )

    first_retry = retry_decision(_task(execute_attempts=1), config=config, now=now, error_code="timeout")
    cooldown = retry_decision(_task(execute_attempts=3), config=config, now=now, error_code="timeout")
    dead = retry_decision(_task(execute_attempts=5), config=config, now=now, error_code="timeout")

    assert first_retry.action == "retry_wait"
    assert first_retry.next_eligible_at == now + timedelta(seconds=20)
    assert cooldown.action == "circuit_open"
    assert cooldown.next_eligible_at == now + timedelta(seconds=300)
    assert cooldown.dead_letter_reason is None
    assert dead.action == "dead_letter"
    assert dead.dead_letter_reason == "max_attempts_exceeded:timeout"


def test_apply_task_decision_uses_durable_queue_transitions(monkeypatch):
    from polling import backpressure
    from polling.backpressure import BackpressureDecision, apply_task_decision

    calls = []
    task_id = uuid4()
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(backpressure.pg_queue, "defer_task", lambda db, tid, **kw: calls.append(("defer", tid, kw)))
    monkeypatch.setattr(backpressure.pg_queue, "retry_task", lambda db, tid, **kw: calls.append(("retry", tid, kw)))
    monkeypatch.setattr(backpressure.pg_queue, "dead_letter_task", lambda db, tid, **kw: calls.append(("dead", tid, kw)))

    apply_task_decision(object(), task_id, BackpressureDecision(action="defer", next_eligible_at=when, error_code="pressure", error_message="queue high"))
    apply_task_decision(object(), task_id, BackpressureDecision(action="retry_wait", next_eligible_at=when, error_code="timeout"))
    apply_task_decision(object(), task_id, BackpressureDecision(action="dead_letter", dead_letter_reason="max_attempts"))

    assert calls[0] == ("defer", task_id, {"next_eligible_at": when, "error_code": "pressure", "error_message": "queue high"})
    assert calls[1][0] == "retry"
    assert calls[2] == ("dead", task_id, {"reason": "max_attempts", "error_code": None, "error_message": None})
