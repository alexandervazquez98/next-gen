"""Service facade for MQTT runtime status persistence.

PR1 scope: heartbeat/status CRUD and counter helpers.
"""

from __future__ import annotations

from datetime import UTC, datetime

from repositories.mqtt_runtime_status_repo import MqttRuntimeStatusRepo


class MqttRuntimeStatusService:
    """Thin service wrapper for runtime status read/write operations."""

    def __init__(
        self,
        repo: MqttRuntimeStatusRepo | None = None,
        stale_heartbeat_seconds: int = 90,
    ):
        self._repo = repo or MqttRuntimeStatusRepo()
        self._stale_seconds = stale_heartbeat_seconds

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def get_status(self) -> dict:
        """Read current status; stale heartbeats are normalized to not-running."""
        return self._repo.get_status(stale_after_seconds=self._stale_seconds, now=self._now())

    def mark_configured(self, configured: bool) -> dict:
        """Update configured flag only."""
        return self._repo.update_status(configured=configured)

    def mark_connected(self, connected: bool) -> dict:
        """Update connection flag only."""
        return self._repo.update_status(connected=connected)

    def mark_running(self, running: bool, reason_code: str | None = None) -> dict:
        """Update running state and optional reason code."""
        return self._repo.update_status(running=running, reason_code=reason_code)

    def record_heartbeat(
        self,
        *,
        running: bool = True,
        connected: bool = True,
        subscribed_patterns: list[str] | None = None,
        timestamp: datetime | None = None,
    ) -> dict:
        """Record a subscriber heartbeat (message/activity observed)."""
        return self._repo.update_status(
            running=running,
            connected=connected,
            subscribed_patterns=subscribed_patterns,
            last_message_at=timestamp or self._now(),
            reason_code=None,
            last_error=None,
            clear_reason_code=True,
            clear_last_error=True,
        )

    def record_disconnect(self, reason_code: str, error: str | None = None) -> dict:
        """Record subscriber disconnect/error and mark subscriber as not connected."""
        return self._repo.update_status(
            connected=False,
            running=False,
            reason_code=reason_code,
            last_error=error,
        )

    def increment_counter(self, counter: str, delta: int = 1) -> dict:
        """Increment one bridge outcome counter."""
        return self._repo.increment_counter(counter, delta=delta)


# Shared singleton helper (explicitly lightweight for import-time consumers).
_status_service: MqttRuntimeStatusService | None = None


def get_mqtt_runtime_status_service(
    repo: MqttRuntimeStatusRepo | None = None,
    stale_heartbeat_seconds: int = 90,
) -> MqttRuntimeStatusService:
    global _status_service
    if _status_service is None:
        _status_service = MqttRuntimeStatusService(
            repo=repo,
            stale_heartbeat_seconds=stale_heartbeat_seconds,
        )
    return _status_service
