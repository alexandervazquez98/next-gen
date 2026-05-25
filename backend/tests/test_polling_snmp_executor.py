from datetime import datetime, timezone
from uuid import uuid4


def _task(protocol="SNMP", payload=None, **overrides):
    base = {
        "task_id": uuid4(),
        "cycle_id": uuid4(),
        "ci_id": "ci-1",
        "metric_id": "CPU" if protocol == "SNMP" else "PING-CHECK",
        "protocol": protocol,
        "source": "10.0.0.1:161/1.2.3" if protocol == "SNMP" else "10.0.0.1",
        "priority": 50 if protocol == "SNMP" else 0,
        "payload": payload or {
            "kind": "snmp_get",
            "target": "10.0.0.1",
            "community": "public",
            "oid": "1.2.3",
            "port": 161,
        },
        "metadata": {"site_id": "site-a"},
    }
    base.update(overrides)
    return base


def test_snmp_executor_maps_success_to_result_envelope_without_db_writes():
    from polling.contracts import PollingResultStatus
    from polling.snmp_executor import execute_poll_task

    result = execute_poll_task(
        _task(),
        worker_id="worker-a",
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        snmp_fetcher=lambda **kwargs: 42.0,
    )

    assert result.status == PollingResultStatus.OK
    assert result.value == {"numeric": 42.0, "text": None, "raw": 42.0}
    assert result.error == {"code": None, "message": None, "retryable": False}
    assert result.worker_id == "worker-a"
    assert result.idempotency_key.startswith("sha256:")


def test_snmp_executor_maps_no_data_and_errors_to_retryable_results():
    from polling.contracts import PollingResultStatus
    from polling.snmp_executor import execute_poll_task

    no_data = execute_poll_task(_task(), snmp_fetcher=lambda **kwargs: None)
    assert no_data.status == PollingResultStatus.NO_DATA
    assert no_data.error["code"] == "no_data"
    assert no_data.error["retryable"] is True

    def boom(**kwargs):
        raise RuntimeError("snmp exploded")

    error = execute_poll_task(_task(), snmp_fetcher=boom)
    assert error.status == PollingResultStatus.ERROR
    assert error.error["code"] == "executor_error"
    assert error.error["retryable"] is True


def test_icmp_executor_maps_ping_success_and_failure_statuses():
    from polling.contracts import PollingResultStatus
    from polling.snmp_executor import execute_poll_task

    payload = {"kind": "icmp_ping", "target": "10.0.0.1", "timeout_ms": 500, "retries": 1}
    success = execute_poll_task(_task("ICMP", payload), icmp_fetcher=lambda **kwargs: 1.0)
    failure = execute_poll_task(_task("ICMP", payload), icmp_fetcher=lambda **kwargs: 0.0)

    assert success.status == PollingResultStatus.OK
    assert success.value["numeric"] == 1.0
    assert failure.status == PollingResultStatus.CRITICAL
    assert failure.value["numeric"] == 0.0
