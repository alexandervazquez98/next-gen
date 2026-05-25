from datetime import datetime, timedelta, timezone
from uuid import uuid4


def test_idempotency_key_is_deterministic_and_normalizes_source_and_bucket():
    from polling.idempotency import generate_idempotency_key

    cycle_id = uuid4()
    observed = datetime(2026, 5, 25, 12, 0, 42, tzinfo=timezone.utc)

    key1 = generate_idempotency_key(
        ci_id="CI-001",
        metric_id="PING-CHECK",
        protocol="icmp",
        source=" 10.0.0.1 ",
        observed_at=observed,
        cycle_id=cycle_id,
        result_kind="sample",
        bucket_seconds=60,
    )
    key2 = generate_idempotency_key(
        ci_id="CI-001",
        metric_id="PING-CHECK",
        protocol="ICMP",
        source="10.0.0.1",
        observed_at=observed + timedelta(seconds=10),
        cycle_id=cycle_id,
        result_kind="sample",
        bucket_seconds=60,
    )

    assert key1 == key2
    assert key1.startswith("sha256:")
    assert len(key1) == len("sha256:") + 64


def test_idempotency_key_changes_for_cycle_metric_source_or_result_kind():
    from polling.idempotency import generate_idempotency_key

    observed = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    base = {
        "ci_id": "CI-001",
        "metric_id": "PING-CHECK",
        "protocol": "ICMP",
        "source": "10.0.0.1",
        "observed_at": observed,
        "cycle_id": uuid4(),
        "result_kind": "sample",
    }

    key = generate_idempotency_key(**base)

    assert generate_idempotency_key(**{**base, "cycle_id": uuid4()}) != key
    assert generate_idempotency_key(**{**base, "metric_id": "CPU"}) != key
    assert generate_idempotency_key(**{**base, "source": "10.0.0.2"}) != key
    assert generate_idempotency_key(**{**base, "result_kind": "timeout"}) != key
