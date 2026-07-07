"""Repository tests for shared MQTT runtime status persistence.

RED phase: validates heartbeat CRUD semantics and stale detection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = [pytest.mark.unit]


class _FakeQueryResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def first(self):
        return self._row

    def one_or_none(self):
        return self._row

    def scalar_one_or_none(self):
        return self._row

    def mappings(self):
        return self


class _FakeSession:
    """Minimal SQLAlchemy-like session used for offline deterministic repository tests."""

    def __init__(self):
        self.calls = []
        self._row = None

    @staticmethod
    def _to_list(value):
        if value is None:
            return None
        if isinstance(value, str):
            try:
                from json import loads

                parsed = loads(value)
                if isinstance(parsed, list):
                    return list(parsed)
            except Exception:
                pass
            return [x.strip() for x in value.split(",") if x.strip()]
        return list(value)

    def execute(self, statement, params=None):
        params = params or {}
        sql = str(statement)
        self.calls.append((sql, params))
        sql_lower = sql.lower()

        if "create table if not exists mqtt_runtime_status" in sql_lower:
            return _FakeQueryResult(None)

        if sql_lower.startswith("select") and "mqtt_runtime_status" in sql_lower:
            return _FakeQueryResult(self._row)

        if sql_lower.startswith("insert into mqtt_runtime_status"):
            self._row = self._default_row()
            for key, value in params.items():
                if key == "subscribed_patterns" and isinstance(value, str):
                    self._row[key] = self._to_list(value)
                elif value is not None:
                    self._row[key] = value
            return _FakeQueryResult(self._row)

        if "update mqtt_runtime_status" in sql_lower:
            if self._row is None:
                self._row = self._default_row()

            mapped_delta = params.pop("mapped_writes_delta", None)
            unmapped_delta = params.pop("unmapped_skips_total_delta", None)
            failed_delta = params.pop("failed_writes_total_delta", None)
            clear_last_error = bool(params.pop("clear_last_error", False))
            clear_reason_code = bool(params.pop("clear_reason_code", False))

            for key, value in params.items():
                if key in {"clear_last_error", "clear_reason_code", "mapped_writes_delta", "unmapped_skips_total_delta", "failed_writes_total_delta", "service_name"}:
                    continue
                if value is None:
                    continue
                if key == "subscribed_patterns" and isinstance(value, str):
                    self._row[key] = self._to_list(value)
                else:
                    self._row[key] = value

            if clear_last_error:
                self._row["last_error"] = None
            if clear_reason_code:
                self._row["reason_code"] = None

            if mapped_delta is not None:
                self._row["mapped_writes_total"] = int(self._row.get("mapped_writes_total", 0)) + mapped_delta
            if unmapped_delta is not None:
                self._row["unmapped_skips_total"] = int(self._row.get("unmapped_skips_total", 0)) + unmapped_delta
            if failed_delta is not None:
                self._row["failed_writes_total"] = int(self._row.get("failed_writes_total", 0)) + failed_delta

            return _FakeQueryResult(self._row)

        raise AssertionError(f"Unhandled SQL statement: {sql}")

    def _default_row(self):
        return {
            "service_name": "mqtt-subscriber",
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
            "updated_at": datetime(2026, 7, 1, 9, 30, tzinfo=UTC),
        }

    def commit(self):
        self.calls.append(("COMMIT", {}))

    def rollback(self):
        self.calls.append(("ROLLBACK", {}))

    def close(self):
        self.calls.append(("CLOSE", {}))


@pytest.fixture
def fake_session():
    return _FakeSession()


@pytest.fixture
def repo(fake_session):
    from repositories.mqtt_runtime_status_repo import MqttRuntimeStatusRepo

    return MqttRuntimeStatusRepo(
        service_name="mqtt-subscriber",
        session_factory=lambda: fake_session,
    )


def test_status_defaults_are_initialized_and_readable(repo):
    """First read initializes a default row and returns heartbeat-safe defaults."""
    status = repo.get_status()

    assert status["service_name"] == "mqtt-subscriber"
    assert status["configured"] is False
    assert status["running"] is False
    assert status["connected"] is False
    assert status["subscribed_patterns"] == []
    assert status["mapped_writes_total"] == 0
    assert status["unmapped_skips_total"] == 0
    assert status["failed_writes_total"] == 0
    assert status["is_stale"] is True
    assert status["reason_code"] == "STALE_HEARTBEAT"


def test_heartbeat_updates_connection_and_last_message(repo):
    """Marking heartbeat updates runtime heartbeat and keeps subscriber running."""
    now = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)

    repo.update_status(running=True, connected=True, last_message_at=now, subscribed_patterns=["rtu/+/+/telemetry"])
    status = repo.get_status(stale_after_seconds=120, now=now)

    assert status["running"] is True
    assert status["connected"] is True
    assert status["last_message_at"] == now
    assert status["subscribed_patterns"] == ["rtu/+/+/telemetry"]
    assert status["reason_code"] is None


def test_counters_increment_atomically(repo):
    """Counter deltas update totals independently and cumulatively."""
    repo.increment_counter("mapped_writes_total", 3)
    repo.increment_counter("unmapped_skips_total", 2)
    repo.increment_counter("failed_writes_total", 1)

    status = repo.get_status()

    assert status["mapped_writes_total"] == 3
    assert status["unmapped_skips_total"] == 2
    assert status["failed_writes_total"] == 1


def test_error_state_is_cleared_when_heartbeat_resumes(repo):
    """A healthy heartbeat should clear prior error metadata and stale reason fields."""
    disconnected_at = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    resumed_at = disconnected_at + timedelta(minutes=1)

    repo.update_status(
        running=False,
        connected=False,
        reason_code="DISCONNECTED",
        last_error="broker timeout",
        last_message_at=disconnected_at,
    )
    repo.update_status(
        running=True,
        connected=True,
        last_message_at=resumed_at,
        clear_last_error=True,
        clear_reason_code=True,
    )
    status = repo.get_status(stale_after_seconds=120, now=resumed_at)

    assert status["running"] is True
    assert status["connected"] is True
    assert status["reason_code"] is None
    assert status["last_error"] is None
    assert status["is_stale"] is False


def test_stale_status_marks_running_false_and_reason(repo):
    """Reading status older than threshold must return non-running + stale reason."""
    observed_at = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    stale_at = observed_at - timedelta(minutes=10)

    repo.update_status(running=True, connected=True, last_message_at=stale_at)
    status = repo.get_status(stale_after_seconds=60, now=observed_at)

    assert status["running"] is False
    assert status["is_stale"] is True
    assert status["reason_code"] == "STALE_HEARTBEAT"


def test_error_state_is_recorded_and_not_stale_when_recent(repo):
    """Errors are persisted as metadata and do not force stale status if heartbeat is recent."""
    now = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)

    repo.update_status(
        running=False,
        connected=False,
        reason_code="DISCONNECTED",
        last_error="broker timeout",
        last_message_at=now,
    )
    status = repo.get_status(stale_after_seconds=30, now=now)

    assert status["running"] is False
    assert status["connected"] is False
    assert status["last_error"] == "broker timeout"
    assert status["reason_code"] == "DISCONNECTED"
    assert status["is_stale"] is False
