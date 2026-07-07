"""Service tests for MQTT runtime status heartbeat behavior."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from services.mqtt_runtime_status import MqttRuntimeStatusService

pytestmark = [pytest.mark.unit]


class _RuntimeRepoStub:
    def __init__(self):
        self.last_update_kwargs: dict[str, object] | None = None

    def update_status(self, **kwargs):
        self.last_update_kwargs = kwargs
        return kwargs



def test_record_heartbeat_clears_error_metadata():
    """record_heartbeat must ask repository to clear reason/error metadata."""
    repo = _RuntimeRepoStub()
    service = MqttRuntimeStatusService(repo=repo)

    observed_at = datetime(2026, 7, 1, 10, 30, tzinfo=UTC)

    service.record_heartbeat(
        running=False,
        connected=False,
        subscribed_patterns=["rtu/+/telemetry"],
        timestamp=observed_at,
    )

    assert repo.last_update_kwargs is not None
    assert repo.last_update_kwargs["running"] is False
    assert repo.last_update_kwargs["connected"] is False
    assert repo.last_update_kwargs["subscribed_patterns"] == ["rtu/+/telemetry"]
    assert repo.last_update_kwargs["last_message_at"] == observed_at
    assert repo.last_update_kwargs["reason_code"] is None
    assert repo.last_update_kwargs["last_error"] is None
    assert repo.last_update_kwargs["clear_reason_code"] is True
    assert repo.last_update_kwargs["clear_last_error"] is True
