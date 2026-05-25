from datetime import datetime, timezone
from uuid import uuid4

import pytest


def test_polling_protocols_include_mqtt_stub_only_extension_point():
    from polling.contracts import PollingProtocol

    assert PollingProtocol.ICMP.value == "ICMP"
    assert PollingProtocol.SNMP.value == "SNMP"
    assert PollingProtocol.CLI.value == "CLI"
    assert PollingProtocol.REST.value == "REST"
    assert PollingProtocol.MQTT_STUB.value == "MQTT_STUB"


def test_poll_task_validates_required_identity_and_priority_defaults():
    from polling.contracts import PollTask, PollingPriority, PollingProtocol, PollingTaskStatus

    task = PollTask(
        task_id=uuid4(),
        cycle_id=uuid4(),
        ci_id="CI-001",
        metric_id="PING-CHECK",
        protocol=PollingProtocol.ICMP,
        source="10.0.0.1",
    )

    assert task.priority == PollingPriority.ICMP_AVAILABILITY
    assert task.status == PollingTaskStatus.AVAILABLE
    assert task.protocol == PollingProtocol.ICMP
    assert task.log_context()["ci_id"] == "CI-001"
    assert task.log_context()["metric_id"] == "PING-CHECK"
    assert task.log_context()["protocol"] == "ICMP"


def test_poll_task_rejects_unknown_protocol():
    from polling.contracts import PollTask

    with pytest.raises(ValueError):
        PollTask(
            task_id=uuid4(),
            cycle_id=uuid4(),
            ci_id="CI-001",
            metric_id="CPU",
            protocol="TELNET",
            source="10.0.0.1",
        )


def test_poll_result_envelope_exposes_required_observability_fields():
    from polling.contracts import PollResultEnvelope, PollingProtocol, PollingResultStatus

    envelope = PollResultEnvelope(
        result_id=uuid4(),
        task_id=uuid4(),
        cycle_id=uuid4(),
        idempotency_key="idem-1",
        ci_id="CI-001",
        metric_id="PING-CHECK",
        protocol=PollingProtocol.ICMP,
        source="10.0.0.1",
        observed_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
        status=PollingResultStatus.OK,
        worker_id="worker-1",
        value={"numeric": 1.0},
    )

    assert envelope.log_context() == {
        "cycle_id": str(envelope.cycle_id),
        "task_id": str(envelope.task_id),
        "result_id": str(envelope.result_id),
        "idempotency_key": "idem-1",
        "ci_id": "CI-001",
        "metric_id": "PING-CHECK",
        "protocol": "ICMP",
        "worker_id": "worker-1",
    }
