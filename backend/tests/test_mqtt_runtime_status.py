"""Service-level tests for runtime status transitions and stale heartbeat behavior."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from services.mqtt_runtime_status import MqttRuntimeStatusService

pytestmark = [pytest.mark.unit]


class _RuntimeRepoStub:
    def __init__(self):
        self.row = {
            "configured": False,
            "running": False,
            "connected": False,
            "subscribed_patterns": [],
            "last_message_at": None,
            "last_error": None,
            "reason_code": None,
            "mapped_writes_total": 0,
            "unmapped_skips_total": 0,
            "failed_writes_total": 0,
        }

    def get_status(self, stale_after_seconds: int = 90, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        status = dict(self.row)
        status["is_stale"] = self._is_stale(now, stale_after_seconds)

        if status["is_stale"]:
            status["running"] = False
            status["connected"] = False
            status["reason_code"] = status["reason_code"] or "STALE_HEARTBEAT"

        return status

    def _is_stale(self, now: datetime, stale_after_seconds: int) -> bool:
        last_message_at = self.row["last_message_at"]
        if last_message_at is None:
            return True
        return (now - last_message_at).total_seconds() > stale_after_seconds

    def update_status(self, **kwargs):
        clear_reason_code = kwargs.pop("clear_reason_code", False)
        clear_last_error = kwargs.pop("clear_last_error", False)
        clear_reason_code = bool(clear_reason_code)
        clear_last_error = bool(clear_last_error)

        for key in {
            "configured",
            "running",
            "connected",
            "subscribed_patterns",
            "last_message_at",
            "last_error",
            "reason_code",
        }:
            if key in kwargs and kwargs[key] is not None:
                self.row[key] = kwargs[key]

        if clear_reason_code:
            self.row["reason_code"] = None
        if clear_last_error:
            self.row["last_error"] = None

        return self.row


@pytest.fixture
def repo() -> _RuntimeRepoStub:
    return _RuntimeRepoStub()


def test_stale_heartbeat_marks_subscriber_non_running(repo):
    service = MqttRuntimeStatusService(repo=repo, stale_heartbeat_seconds=30)
    service._now = lambda: datetime(2026, 7, 1, 10, 0, tzinfo=UTC)

    service.record_heartbeat(
        running=True,
        connected=True,
        subscribed_patterns=["rtu/+/telemetry"],
        timestamp=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
    )

    status = service.get_status()
    assert status["running"] is True
    assert status["connected"] is True
    assert status["is_stale"] is False

    service._now = lambda: datetime(2026, 7, 1, 10, 1, 1, tzinfo=UTC)
    stale_status = service.get_status()
    assert stale_status["is_stale"] is True
    assert stale_status["running"] is False
    assert stale_status["connected"] is False
    assert stale_status["reason_code"] == "STALE_HEARTBEAT"


def test_default_status_reports_stale_without_heartbeat(repo):
    service = MqttRuntimeStatusService(repo=repo)
    service._now = lambda: datetime(2026, 7, 1, 10, 0, tzinfo=UTC)

    status = service.get_status()

    assert status["is_stale"] is True
    assert status["running"] is False
    assert status["connected"] is False
    assert status["reason_code"] == "STALE_HEARTBEAT"


def test_record_disconnect_updates_running_connected_and_reason(repo):
    service = MqttRuntimeStatusService(repo=repo)
    service.record_disconnect("BROKER_DISCONNECTED", "connection closed")
    service._now = lambda: datetime(2026, 7, 1, 10, 5, tzinfo=UTC)

    status = service.get_status()
    assert status["running"] is False
    assert status["connected"] is False
    assert status["reason_code"] == "BROKER_DISCONNECTED"
    assert status["last_error"] == "connection closed"
