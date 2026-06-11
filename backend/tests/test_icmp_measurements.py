from polling.icmp_measurements import (
    ICMP_JITTER_METRIC_ID,
    ICMP_LATENCY_METRIC_ID,
    ICMP_PACKET_LOSS_METRIC_ID,
    PingMeasurement,
    build_icmp_sidecar_samples,
    is_icmp_availability_metric,
    is_icmp_telemetry_metric,
    parse_ping_latency_ms,
)


def test_parse_ping_latency_ms_common_platform_outputs():
    assert parse_ping_latency_ms("64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=12.3 ms") == 12.3
    assert parse_ping_latency_ms("round-trip min/avg/max/stddev = 10.1/12.4/20.0/1.0 ms") == 12.4
    assert parse_ping_latency_ms("Reply from 10.0.0.1: bytes=32 time=12ms TTL=64\nAverage = 12ms") == 12.0
    assert parse_ping_latency_ms("Reply from 10.0.0.1: bytes=32 time<1ms TTL=64") == 0.5


def test_parse_ping_latency_ms_returns_none_for_failures():
    assert parse_ping_latency_ms("Request timed out.") is None
    assert parse_ping_latency_ms("100% packet loss") is None
    assert parse_ping_latency_ms("") is None


def test_build_icmp_sidecar_samples_success_failure_and_jitter():
    success = PingMeasurement(available=True, latency_ms=15.5, raw="ok")
    samples = build_icmp_sidecar_samples("ci-1", success, previous_latency_ms=None)
    assert samples == [
        {"node_id": "ci-1", "metric_id": ICMP_LATENCY_METRIC_ID, "value": 15.5},
        {"node_id": "ci-1", "metric_id": ICMP_PACKET_LOSS_METRIC_ID, "value": 0.0},
    ]

    with_jitter = build_icmp_sidecar_samples("ci-1", success, previous_latency_ms=10.0)
    assert with_jitter == [
        {"node_id": "ci-1", "metric_id": ICMP_LATENCY_METRIC_ID, "value": 15.5},
        {"node_id": "ci-1", "metric_id": ICMP_JITTER_METRIC_ID, "value": 5.5},
        {"node_id": "ci-1", "metric_id": ICMP_PACKET_LOSS_METRIC_ID, "value": 0.0},
    ]

    failure = PingMeasurement(available=False, latency_ms=None, raw="timeout")
    assert build_icmp_sidecar_samples("ci-1", failure, previous_latency_ms=10.0) == [
        {"node_id": "ci-1", "metric_id": ICMP_PACKET_LOSS_METRIC_ID, "value": 100.0},
    ]


def test_icmp_metric_kind_helpers_deny_sidecars_even_with_bad_availability_metadata():
    assert is_icmp_availability_metric("PING-CHECK", {"metric_kind": "availability"}) is True
    assert is_icmp_availability_metric("PING-router-a", {}) is True
    assert is_icmp_availability_metric("icmp_latency_ms", {"metric_kind": "availability"}) is False
    assert is_icmp_availability_metric("icmp_jitter_ms", {"metric_kind": "availability"}) is False
    assert is_icmp_availability_metric("packet_loss_pct", {"metric_kind": "availability"}) is False
    assert is_icmp_telemetry_metric("icmp_latency_ms", {}) is True
    assert is_icmp_telemetry_metric("icmp_jitter_ms", {"metric_kind": "availability"}) is True
    assert is_icmp_telemetry_metric("packet_loss_pct", {"metric_kind": "availability"}) is True
    assert is_icmp_telemetry_metric("PING-CHECK", {"metric_kind": "availability"}) is False
