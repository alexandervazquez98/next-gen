"""Entry-point smoke tests for the dedicated MQTT subscriber runtime process."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock


class _StatusService:
    """Minimal status service spy for entrypoint lifecycle assertions."""

    def __init__(self, fail_configured: bool = False):
        self.calls: list[tuple[str, tuple, dict]] = []
        self.fail_configured = fail_configured

    def mark_configured(self, configured):
        self.calls.append(("mark_configured", (configured,), {}))
        if self.fail_configured:
            raise RuntimeError("status store unavailable")

    def mark_running(self, running, reason_code=None):
        self.calls.append(("mark_running", (running,), {"reason_code": reason_code}))

    def record_disconnect(self, reason_code: str, error: str | None = None):
        self.calls.append(("record_disconnect", (reason_code,), {"error": error}))


def test_runtime_settings_env_contract_prefers_subscriber_stale_alias(monkeypatch):
    import config

    monkeypatch.setenv("MQTT_SUBSCRIBER_STALE_HEARTBEAT_SECONDS", "30")
    monkeypatch.setenv("MQTT_MAPPING_BRIDGE_MISSED_HEARTBEAT_SECONDS", "120")
    monkeypatch.setenv("MQTT_MAPPING_BRIDGE_ENABLED", "false")
    monkeypatch.setenv("ENABLE_MQTT_SUBSCRIBER", "true")

    settings = config.MQTTRuntimeSettings.from_env()

    assert settings.missed_heartbeat_seconds == 30
    assert settings.bridge_enabled is False
    assert settings.run_subscriber_in_process is True


def test_runtime_settings_env_contract_supports_legacy_stale_alias(monkeypatch):
    import config

    monkeypatch.delenv("MQTT_SUBSCRIBER_STALE_HEARTBEAT_SECONDS", raising=False)
    monkeypatch.setenv("MQTT_MAPPING_BRIDGE_MISSED_HEARTBEAT_SECONDS", "45")

    settings = config.MQTTRuntimeSettings.from_env()

    assert settings.missed_heartbeat_seconds == 45


def test_entrypoint_main_runs_shared_loop(monkeypatch):
    from scripts import mqtt_subscriber

    status = _StatusService()
    monkeypatch.setattr(mqtt_subscriber, "get_mqtt_runtime_status_service", lambda: status)
    loop = AsyncMock()
    monkeypatch.setattr(mqtt_subscriber, "mqtt_subscriber_loop", loop)

    assert mqtt_subscriber.main([]) == 0

    loop.assert_awaited_once()
    assert status.calls[0] == ("mark_configured", (True,), {})
    assert status.calls[1] == ("record_disconnect", ("SHUTDOWN",), {"error": None})


def test_entrypoint_status_store_failure_does_not_block_loop(monkeypatch):
    from scripts import mqtt_subscriber

    status = _StatusService(fail_configured=True)
    monkeypatch.setattr(mqtt_subscriber, "get_mqtt_runtime_status_service", lambda: status)
    loop = AsyncMock()
    monkeypatch.setattr(mqtt_subscriber, "mqtt_subscriber_loop", loop)

    assert mqtt_subscriber.main([]) == 0

    # Entry-point status updates to configure may fail, but the shared loop should
    # still start and shutdown should still be recorded best-effort.
    loop.assert_awaited_once()
    assert any(call[0] == "record_disconnect" and call[1] == ("SHUTDOWN",) for call in status.calls)


def test_backend_embedded_subscriber_is_disabled_by_default(monkeypatch):
    import main

    scheduled = []
    monkeypatch.setattr(
        main,
        "get_mqtt_runtime_settings",
        lambda: SimpleNamespace(run_subscriber_in_process=False),
    )

    main._start_embedded_mqtt_subscriber(task_factory=scheduled.append)

    assert scheduled == []


def test_backend_embedded_subscriber_starts_only_when_enabled(monkeypatch):
    import main

    scheduled = []
    monkeypatch.setattr(
        main,
        "get_mqtt_runtime_settings",
        lambda: SimpleNamespace(run_subscriber_in_process=True),
    )

    main._start_embedded_mqtt_subscriber(task_factory=scheduled.append)

    assert len(scheduled) == 1
    scheduled[0].close()


def test_entrypoint_main_records_failure_and_returns_one(monkeypatch):
    from scripts import mqtt_subscriber

    status = _StatusService()
    monkeypatch.setattr(mqtt_subscriber, "get_mqtt_runtime_status_service", lambda: status)
    monkeypatch.setattr(
        mqtt_subscriber,
        "mqtt_subscriber_loop",
        AsyncMock(side_effect=RuntimeError("broker connection failed")),
    )

    assert mqtt_subscriber.main([]) == 1

    assert status.calls[0] == ("mark_configured", (True,), {})
    assert status.calls[1][0] == "record_disconnect" and status.calls[1][1] == ("SHUTDOWN",)
    assert status.calls[2] == (
        "record_disconnect",
        ("RUNTIME_ERROR",),
        {"error": "broker connection failed"},
    )
