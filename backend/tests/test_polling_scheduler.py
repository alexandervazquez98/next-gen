from datetime import datetime, timezone
from uuid import UUID


def _records():
    return [
        {
            "node_id": "ci-icmp",
            "ip": "10.0.0.1",
            "site_id": "site-a",
            "subnet": "10.0.0.0/24",
            "metric_id": "PING-CHECK",
            "protocol": "ICMP",
            "metadata_version": "v1",
        },
        {
            "node_id": "ci-snmp",
            "ip": "10.0.0.2",
            "metric_id": "CPU",
            "protocol": "SNMP",
            "oid": "1.3.6.1.2.1.25.3.3.1.2",
            "community": "public",
            "port": 161,
            "metadata_version": "v1",
        },
        {
            "node_id": "ci-cli",
            "ip": "10.0.0.3",
            "metric_id": "CLI-CPU",
            "protocol": "CLI",
            "cli_command": "show cpu",
            "cli_target": "shell",
            "cli_credential_ref": "cred-router",
            "metadata_version": "v1",
        },
    ]


def test_scheduler_skips_icmp_sidecar_records_when_availability_exists():
    from polling.scheduler import build_cycle, build_tasks_from_records

    cycle = build_cycle(scheduled_for=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc), config_version="v1")
    records = _records() + [
        {
            "node_id": "ci-icmp",
            "ip": "10.0.0.1",
            "metric_id": "icmp_latency_ms",
            "protocol": "ICMP",
            "metric_kind": "telemetry",
            "metadata_version": "v1",
        },
        {
            "node_id": "ci-icmp",
            "ip": "10.0.0.1",
            "metric_id": "icmp_jitter_ms",
            "protocol": "ICMP",
            "metric_kind": "telemetry",
            "metadata_version": "v1",
        },
    ]

    tasks = build_tasks_from_records(records, cycle)

    assert {task["metric_id"] for task in tasks} == {"PING-CHECK", "CPU", "CLI-CPU"}
    assert all(task["metric_id"] not in {"icmp_latency_ms", "icmp_jitter_ms"} for task in tasks)


def test_scheduler_synthesizes_icmp_poll_task_from_sidecar_records_without_ping_metric():
    from polling.contracts import PollingPriority, PollingProtocol
    from polling.scheduler import build_cycle, build_tasks_from_records

    cycle = build_cycle(scheduled_for=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc), config_version="v1")
    records = [
        {
            "node_id": "ci-icmp",
            "ip": "10.0.0.1",
            "site_id": "site-a",
            "subnet": "10.0.0.0/24",
            "metric_id": "icmp_latency_ms",
            "protocol": "ICMP",
            "metric_kind": "telemetry",
            "metadata_version": "v1",
        },
        {
            "node_id": "ci-icmp",
            "ip": "10.0.0.1",
            "site_id": "site-a",
            "subnet": "10.0.0.0/24",
            "metric_id": "icmp_jitter_ms",
            "protocol": "ICMP",
            "metric_kind": "telemetry",
            "metadata_version": "v1",
        },
    ]

    tasks = build_tasks_from_records(records, cycle)

    assert len(tasks) == 1
    task = tasks[0]
    assert task["metric_id"] == "icmp_availability"
    assert task["metric_kind"] == "availability"
    assert task["protocol"] == PollingProtocol.ICMP
    assert task["priority"] == PollingPriority.ICMP_AVAILABILITY
    assert task["payload"] == {"kind": "icmp_ping", "target": "10.0.0.1", "timeout_ms": 3000, "retries": 2, "internal": True}


def test_scheduler_synthesizes_icmp_poll_task_from_ip_address_sidecar_records():
    from polling.scheduler import build_cycle, build_tasks_from_records

    cycle = build_cycle(scheduled_for=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc), config_version="v1")

    tasks = build_tasks_from_records([
        {
            "node_id": "ci-ip-address",
            "ip_address": "10.0.0.9",
            "metric_id": "icmp_latency_ms",
            "protocol": "ICMP",
            "metric_kind": "telemetry",
            "metadata_version": "v1",
        }
    ], cycle)

    assert len(tasks) == 1
    assert tasks[0]["metric_id"] == "icmp_availability"
    assert tasks[0]["internal"] is True
    assert tasks[0]["payload"]["target"] == "10.0.0.9"
    assert tasks[0]["payload"]["internal"] is True


def test_scheduler_ignores_icmp_sidecar_records_without_ip():
    from polling.scheduler import build_cycle, build_tasks_from_records

    cycle = build_cycle(scheduled_for=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc), config_version="v1")

    tasks = build_tasks_from_records([
        {
            "node_id": "ci-no-ip",
            "source": "stale-source-without-ip",
            "metric_id": "icmp_latency_ms",
            "protocol": "ICMP",
            "metric_kind": "telemetry",
            "metadata_version": "v1",
        }
    ], cycle)

    assert tasks == []


def test_scheduler_builds_15_minute_cycle_and_priority_ordered_tasks():
    from polling.contracts import PollingPriority, PollingProtocol
    from polling.scheduler import build_cycle, build_tasks_from_records, group_tasks_by_protocol

    scheduled_for = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    cycle = build_cycle(scheduled_for=scheduled_for, config_version="v1", target_cycle_seconds=900)
    tasks = build_tasks_from_records(_records(), cycle)

    assert cycle.scheduled_for == scheduled_for
    assert cycle.target_cycle_seconds == 900
    assert cycle.config_version == "v1"
    assert len(tasks) == 3
    assert tasks[0]["priority"] == PollingPriority.ICMP_AVAILABILITY
    assert tasks[0]["protocol"] == PollingProtocol.ICMP
    assert tasks[0]["due_at"] == scheduled_for
    assert tasks[0]["next_eligible_at"] == scheduled_for
    assert tasks[0]["metadata_version"] == "v1"
    assert isinstance(tasks[0]["task_id"], UUID)
    assert isinstance(tasks[0]["partition_key"], int)

    grouped = group_tasks_by_protocol(tasks)
    assert set(grouped) == {"ICMP", "SNMP", "CLI"}


def test_scheduler_task_ids_are_deterministic_for_duplicate_expansion():
    from polling.scheduler import build_cycle, build_tasks_from_records

    scheduled_for = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    cycle = build_cycle(scheduled_for=scheduled_for, config_version="v1")

    first = build_tasks_from_records(_records(), cycle)
    second = build_tasks_from_records(_records(), cycle)

    assert [task["task_id"] for task in first] == [task["task_id"] for task in second]
    assert [task["partition_key"] for task in first] == [task["partition_key"] for task in second]


def test_scheduler_rejects_unsupported_protocol_and_detects_stale_metadata():
    import pytest
    from polling.scheduler import build_cycle, build_tasks_from_records, has_stale_metadata

    cycle = build_cycle(
        scheduled_for=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc),
        config_version="v2",
    )

    assert has_stale_metadata({"metadata_version": "v1"}, current_metadata_version="v2") is True
    assert has_stale_metadata({"metadata_version": "v2"}, current_metadata_version="v2") is False

    with pytest.raises(ValueError, match="Unsupported polling protocol"):
        build_tasks_from_records([{"node_id": "ci", "metric_id": "bad", "protocol": "TELNET"}], cycle)


def test_scheduler_can_enqueue_cycle_and_tasks_without_runtime_wiring():
    from polling.scheduler import build_cycle, build_tasks_from_records, enqueue_cycle_tasks

    class FakeDb:
        def __init__(self):
            self.calls = []

        def execute(self, statement, params=None):
            self.calls.append((str(statement), params or {}))
            return []

        def commit(self):
            self.calls.append(("COMMIT", {}))

    cycle = build_cycle(scheduled_for=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc))
    tasks = build_tasks_from_records(_records()[:1], cycle)
    db = FakeDb()

    enqueue_cycle_tasks(db, cycle, tasks)

    executed = "\n".join(sql for sql, _ in db.calls)
    assert "INSERT INTO poll_cycles" in executed
    assert "INSERT INTO poll_task_queue" in executed
