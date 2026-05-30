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

    structured_error = execute_poll_task(_task(), snmp_fetcher=lambda **kwargs: (None, "ERROR", "noSuchName at 1.2.3"))
    assert structured_error.status == PollingResultStatus.ERROR
    assert structured_error.error["code"] == "snmp_error"
    assert structured_error.error["message"] == "noSuchName at 1.2.3"

    structured_timeout = execute_poll_task(
        _task(),
        snmp_fetcher=lambda **kwargs: (None, "TIMEOUT", "No SNMP response received before timeout"),
    )
    assert structured_timeout.status == PollingResultStatus.TIMEOUT
    assert structured_timeout.error["code"] == "timeout"
    assert structured_timeout.error["retryable"] is True

    explicit_timeout_error = execute_poll_task(
        _task(),
        snmp_fetcher=lambda **kwargs: (None, "ERROR", "No SNMP response received before timeout"),
    )
    assert explicit_timeout_error.status == PollingResultStatus.TIMEOUT
    assert explicit_timeout_error.error["code"] == "timeout"
    assert explicit_timeout_error.error["retryable"] is True

    def boom(**kwargs):
        raise RuntimeError("snmp exploded")

    error = execute_poll_task(_task(), snmp_fetcher=boom)
    assert error.status == PollingResultStatus.ERROR
    assert error.error["code"] == "executor_error"
    assert error.error["retryable"] is True


def test_icmp_executor_maps_ping_success_and_failure_statuses():
    from polling.contracts import PollingResultStatus
    from polling.icmp_measurements import PingMeasurement
    from polling.snmp_executor import execute_poll_task

    payload = {"kind": "icmp_ping", "target": "10.0.0.1", "timeout_ms": 500, "retries": 1}
    success = execute_poll_task(_task("ICMP", payload), icmp_fetcher=lambda **kwargs: PingMeasurement(True, 18.25, raw="ok"))
    failure = execute_poll_task(_task("ICMP", payload), icmp_fetcher=lambda **kwargs: PingMeasurement(False, None, raw="timeout"))

    assert success.status == PollingResultStatus.OK
    assert success.value["numeric"] == 1.0
    assert success.metric_id == "PING-CHECK"
    assert success.metadata["metric_kind"] == "availability"
    assert success.metadata["icmp"]["latency_ms"] == 18.25
    assert success.metadata["icmp"]["sidecar_metric_ids"] == ["icmp_latency_ms", "icmp_jitter_ms"]
    assert failure.status == PollingResultStatus.CRITICAL
    assert failure.value["numeric"] == 0.0
    assert "latency_ms" not in failure.metadata["icmp"]


def test_icmp_executor_marks_internal_synthetic_availability_in_metadata():
    from polling.icmp_measurements import PingMeasurement
    from polling.snmp_executor import execute_poll_task

    payload = {"kind": "icmp_ping", "target": "10.0.0.1", "timeout_ms": 500, "retries": 1, "internal": True}
    result = execute_poll_task(
        _task("ICMP", payload, metric_id="icmp_availability", internal=True),
        icmp_fetcher=lambda **kwargs: PingMeasurement(True, 18.25, raw="ok"),
    )

    assert result.metadata["internal"] is True
    assert result.metadata["metric_kind"] == "availability"
    assert result.metadata["icmp"]["latency_ms"] == 18.25


def test_icmp_executor_preserves_internal_marker_on_fetcher_exception():
    from polling.contracts import PollingResultStatus
    from polling.snmp_executor import execute_poll_task

    def boom(**kwargs):
        raise RuntimeError("icmp exploded")

    payload = {"kind": "icmp_ping", "target": "10.0.0.1", "timeout_ms": 500, "retries": 1, "internal": True}
    result = execute_poll_task(
        _task("ICMP", payload, metric_id="icmp_availability", internal=True),
        icmp_fetcher=boom,
    )

    assert result.status == PollingResultStatus.ERROR
    assert result.metadata["internal"] is True


def test_icmp_executor_fetcher_exception_returns_error_envelope_without_unbound_measurement():
    from polling.contracts import PollingResultStatus
    from polling.snmp_executor import execute_poll_task

    def boom(**kwargs):
        raise RuntimeError("icmp exploded")

    payload = {"kind": "icmp_ping", "target": "10.0.0.1", "timeout_ms": 500, "retries": 1}
    result = execute_poll_task(_task("ICMP", payload), icmp_fetcher=boom)

    assert result.status == PollingResultStatus.ERROR
    assert result.error == {"code": "executor_error", "message": "icmp exploded", "retryable": True}
    assert result.value == {"numeric": None, "text": None, "raw": None}
    assert "icmp" not in result.metadata
    assert result.metadata.get("metric_kind") != "availability"


def test_icmp_executor_skips_sidecar_metric_tasks_as_telemetry_not_availability():
    from polling.contracts import PollingResultStatus
    from polling.snmp_executor import execute_poll_task

    payload = {"kind": "icmp_ping", "target": "10.0.0.1", "timeout_ms": 500, "retries": 1}
    result = execute_poll_task(
        _task("ICMP", payload, metric_id="icmp_latency_ms", metadata={"metric_kind": "telemetry"}),
        icmp_fetcher=lambda **kwargs: 1.0,
    )

    assert result.status == PollingResultStatus.OK
    assert result.value == {"numeric": None, "text": None, "raw": None}
    assert result.error == {"code": "skipped_icmp_telemetry", "message": "ICMP telemetry sidecars are derived from availability polls", "retryable": False}
    assert result.metadata["metric_kind"] == "telemetry"
    assert "icmp" not in result.metadata
