from collections import Counter

import pytest


def test_default_simulator_models_roadmap_task_count_without_materializing_all_tasks():
    from polling.simulator import SimulationConfig

    config = SimulationConfig()

    assert config.ci_count == 8000
    assert config.metrics_per_ci == 35
    assert config.total_tasks == 280000
    assert config.target_cycle_seconds == 900


def test_simulator_generates_protocol_mix_and_mqtt_stub_only_records():
    from polling.contracts import PollingProtocol
    from polling.simulator import SimulationConfig, generate_metric_records, parse_protocol_mix

    mix = parse_protocol_mix("ICMP:0.25,SNMP:0.25,CLI:0.25,REST:0.15,MQTT_STUB:0.10")
    config = SimulationConfig(ci_count=10, metrics_per_ci=4, protocol_mix=mix)
    records = list(generate_metric_records(config))

    assert len(records) == 40
    protocols = Counter(record["protocol"] for record in records)
    assert set(protocols) == {"ICMP", "SNMP", "CLI", "REST", "MQTT_STUB"}
    assert protocols["MQTT_STUB"] == 4
    assert all(record["protocol"] != "MQTT" for record in records)
    assert all(isinstance(record["protocol_enum"], PollingProtocol) for record in records)


def test_production_mqtt_is_rejected_in_protocol_mix():
    from polling.simulator import parse_protocol_mix

    with pytest.raises(ValueError, match="MQTT_STUB"):
        parse_protocol_mix("MQTT:1.0")


def test_simulation_report_includes_latency_failure_backpressure_and_resource_hints():
    from polling.simulator import SimulationConfig, run_simulation

    config = SimulationConfig(
        ci_count=20,
        metrics_per_ci=5,
        protocol_mix="ICMP:0.2,SNMP:0.6,REST:0.2",
        worker_count=10,
        db_writer_count=2,
        failure_rate=0.10,
        timeout_rate=0.05,
        inject_backpressure=True,
        max_task_queue_depth=50,
    )

    report = run_simulation(config)

    assert report.total_tasks == 100
    assert report.deferred_count > 0
    assert report.dead_letter_count >= 0
    assert report.p95_latency_ms >= report.p50_latency_ms
    assert report.p99_latency_ms >= report.p95_latency_ms
    assert report.worker_throughput_per_second > 0
    assert report.queue_depth >= 0
    assert report.queue_oldest_age_seconds >= 0
    assert report.writer_lag_seconds >= 0
    assert report.db_write_latency_ms >= 0
    assert report.resource_hints
    assert "backpressure" in report.bottlenecks
