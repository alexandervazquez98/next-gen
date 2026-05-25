from uuid import uuid4


def _task(**overrides):
    base = {
        "task_id": uuid4(),
        "cycle_id": uuid4(),
        "ci_id": "ci-1",
        "metric_id": "PING-CHECK",
        "protocol": "ICMP",
        "ip_address": "10.0.0.1",
        "site_id": "site-a",
        "subnet": "10.0.0.0/24",
        "credential_ref": "cred-a",
        "endpoint": "10.0.0.1",
        "source": "10.0.0.1",
    }
    base.update(overrides)
    return base


def test_safety_limiter_blocks_same_ci_without_blocking_unrelated_targets():
    from polling.safety_limits import ActiveSafetyLimiter, SafetyLimitConfig

    limiter = ActiveSafetyLimiter(SafetyLimitConfig(per_ci=1, per_protocol=4))

    first = _task(task_id="task-1")
    second_same_ci = _task(task_id="task-2", ip_address="10.0.0.2", source="10.0.0.2")
    unrelated = _task(task_id="task-3", ci_id="ci-2", ip_address="10.0.0.3", source="10.0.0.3")

    assert limiter.acquire(first).allowed is True
    denied = limiter.acquire(second_same_ci)
    assert denied.allowed is False
    assert denied.dimension == "ci_id"
    assert limiter.acquire(unrelated).allowed is True

    limiter.release(first)
    assert limiter.acquire(second_same_ci).allowed is True


def test_safety_limiter_checks_all_configured_dimensions():
    from polling.safety_limits import ActiveSafetyLimiter, SafetyLimitConfig

    dimensions = {
        "per_ci": ("ci_id", "ci-1"),
        "per_ip": ("ip_address", "10.0.0.1"),
        "per_site": ("site_id", "site-a"),
        "per_subnet": ("subnet", "10.0.0.0/24"),
        "per_credential": ("credential_ref", "cred-a"),
        "per_protocol": ("protocol", "ICMP"),
        "per_endpoint": ("endpoint", "10.0.0.1"),
        "per_source": ("source", "10.0.0.1"),
    }

    disabled = {name: None for name in dimensions}
    for config_name, (dimension, expected_key) in dimensions.items():
        limiter = ActiveSafetyLimiter(SafetyLimitConfig(**{**disabled, config_name: 1}))
        assert limiter.acquire(_task(task_id=f"{dimension}-1")).allowed is True
        denied = limiter.acquire(_task(task_id=f"{dimension}-2"))
        assert denied.allowed is False
        assert denied.dimension == dimension
        assert denied.key == expected_key
