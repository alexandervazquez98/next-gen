import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import main
from main import (
    _build_disk_io_status,
    _build_system_status_snapshot,
    _collect_disk_io_sample,
    _fetch_system_status_history,
    _is_diskstats_device,
    _is_system_status_history_stale,
    _register_system_status_snapshot_job,
    _reload_system_status_env_settings,
    _serialize_system_status_snapshot,
    _should_record_system_status_snapshot,
)


def test_collect_disk_io_sample_aggregates_supported_devices_only(tmp_path):
    diskstats = tmp_path / "diskstats"
    diskstats.write_text(
        "   8       0 sda 10 0 20 0 5 0 8 0 0 30 0 0\n"
        "   8       1 sda1 10 0 200 0 5 0 80 0 0 300 0 0\n"
        "   7       0 loop0 10 0 200 0 5 0 80 0 0 300 0 0\n"
        " 253       0 dm-0 10 0 200 0 5 0 80 0 0 300 0 0\n"
        " 259       0 nvme0n1 1 0 4 0 1 0 6 0 0 10 0 0\n",
        encoding="utf-8",
    )

    sampled_at = datetime(2026, 1, 1, 12, 0, 0)
    sample = _collect_disk_io_sample(str(diskstats), sampled_at=sampled_at)

    assert sample == {
        "read_bytes": (20 + 4) * 512,
        "write_bytes": (8 + 6) * 512,
        "busy_ms": 40,
        "sampled_at": sampled_at,
    }


def test_is_diskstats_device_supports_common_base_disk_names():
    assert _is_diskstats_device("sda") is True
    assert _is_diskstats_device("nvme0n1") is True
    assert _is_diskstats_device("mmcblk0") is True
    assert _is_diskstats_device("sda1") is False
    assert _is_diskstats_device("nvme0n1p1") is False
    assert _is_diskstats_device("mmcblk0p1") is False
    assert _is_diskstats_device("dm-0") is False


def test_build_disk_io_status_computes_rates_from_previous_sample():
    previous_time = datetime(2026, 1, 1, 12, 0, 0)
    current_time = previous_time + timedelta(seconds=2)
    previous = {
        "read_bytes": 1024,
        "write_bytes": 2048,
        "busy_ms": 100,
        "sampled_at": previous_time,
    }
    current = {
        "read_bytes": 3072,
        "write_bytes": 4096,
        "busy_ms": 300,
        "sampled_at": current_time,
    }

    status = _build_disk_io_status(current, previous)

    assert status["supported"] is True
    assert status["read_bytes_total"] == 3072
    assert status["write_bytes_total"] == 4096
    assert status["read_bytes_per_sec"] == 1024.0
    assert status["write_bytes_per_sec"] == 1024.0
    assert status["busy_percentage"] == 10.0
    assert status["sampled_at"] == current_time.isoformat()


def test_build_disk_io_status_returns_unsupported_payload_without_sample():
    status = _build_disk_io_status(None)

    assert status == {
        "supported": False,
        "read_bytes_total": None,
        "write_bytes_total": None,
        "read_bytes_per_sec": None,
        "write_bytes_per_sec": None,
        "busy_percentage": None,
        "sampled_at": None,
    }


def test_system_status_snapshot_serializes_compact_operational_history_row():
    recorded_at = datetime(2026, 1, 1, 12, 5, 0)
    status = {
        "cpu": 24.5,
        "ram": 61.2,
        "disk": 40.0,
        "disk_io": {
            "supported": True,
            "read_bytes_per_sec": 1024.0,
            "write_bytes_per_sec": 2048.0,
            "busy_percentage": 12.5,
        },
        "neo4j": "CONNECTED",
        "postgres": "CONNECTED",
        "collector": {
            "status": "RUNNING",
            "stats": {
                "cis_monitored": 8,
                "metrics_collected": 120,
                "metrics_failed": 1,
                "jobs_per_min": 44,
                "cycle_duration": 3,
            },
        },
    }

    snapshot = _build_system_status_snapshot(status, recorded_at)
    row = _serialize_system_status_snapshot(snapshot)

    assert row == {
        "recorded_at": "2026-01-01T12:05:00Z",
        "cpu": 24.5,
        "ram": 61.2,
        "disk": 40.0,
        "disk_io": {
            "supported": True,
            "read_bytes_per_sec": 1024.0,
            "write_bytes_per_sec": 2048.0,
            "busy_percentage": 12.5,
        },
        "neo4j": "CONNECTED",
        "postgres": "CONNECTED",
        "collector": {
            "status": "RUNNING",
            "stats": {
                "cis_monitored": 8,
                "metrics_collected": 120,
                "metrics_failed": 1,
                "jobs_per_min": 44.0,
                "cycle_duration": 3.0,
            },
        },
    }


def test_should_record_system_status_snapshot_honors_fifteen_minute_throttle():
    now = datetime(2026, 1, 1, 12, 15, 0)
    latest = type("Snapshot", (), {"recorded_at": now - timedelta(minutes=14)})()
    stale = type("Snapshot", (), {"recorded_at": now - timedelta(minutes=15)})()

    assert _should_record_system_status_snapshot(None, now) is True
    assert _should_record_system_status_snapshot(latest, now) is False
    assert _should_record_system_status_snapshot(stale, now) is True


def test_system_status_history_staleness_calculation():
    now = datetime(2026, 1, 1, 12, 0, 0)

    assert (
        _is_system_status_history_stale(
            now - timedelta(minutes=29), now, stale_threshold_seconds=1800
        )
        is False
    )
    assert (
        _is_system_status_history_stale(
            now - timedelta(minutes=31), now, stale_threshold_seconds=1800
        )
        is True
    )
    assert _is_system_status_history_stale(None, now, stale_threshold_seconds=1800) is True


def test_get_system_status_does_not_record_snapshot_on_request(monkeypatch):
    payload = {
        "cpu": 1.1,
        "ram": 2.2,
        "disk": 3.3,
        "disk_io": {"supported": False},
        "neo4j": "CONNECTED",
        "postgres": "CONNECTED",
        "collector": {"status": "RUNNING", "stats": {}},
        "startup_time": "startup",
    }
    record_calls = []

    monkeypatch.setattr(main, "_build_system_status_payload", lambda: payload)
    monkeypatch.setattr(
        main,
        "_record_system_status_snapshot",
        lambda *args, **kwargs: record_calls.append((args, kwargs)),
    )

    status = main.get_system_status()

    assert status == payload
    assert len(record_calls) == 0


def test_build_system_status_payload_includes_event_lock_snapshot_without_changing_service_status(
    monkeypatch,
):
    expected_event_lock = {
        "acquisitions_total": 2,
        "wait_ms": {"count": 2, "p95": 1200.0, "p99": 1200.0, "max": 1200.0},
        "alert_state": "WARNING",
        "thresholds_ms": {"info": 250, "warning_p95": 1000, "critical_p99": 5000},
        "by_writer": {"snmp_worker_icmp_latency": {"acquisitions_total": 2}},
    }

    monkeypatch.setattr(main, "verify_connection", lambda max_retries=1, retry_delay=0: None)
    monkeypatch.setattr(main, "_get_disk_io_status", lambda: {"supported": False})
    monkeypatch.setattr(main, "get_collector_status", lambda: {"status": "RUNNING", "stats": {}})
    monkeypatch.setattr(main, "_build_time_sync_status", lambda: {"status": "OK"})
    monkeypatch.setattr(
        "services.event_lock.get_event_lock_observability_snapshot",
        lambda: expected_event_lock,
    )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return None

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr("postgres_db.engine", FakeEngine())

    status = main._build_system_status_payload()

    assert status["event_lock"] == expected_event_lock
    assert status["neo4j"] == "CONNECTED"
    assert status["postgres"] == "CONNECTED"
    assert status["collector"]["status"] == "RUNNING"


def test_build_system_status_payload_falls_back_when_event_lock_snapshot_fails(monkeypatch, caplog):
    monkeypatch.setattr(main, "verify_connection", lambda max_retries=1, retry_delay=0: None)
    monkeypatch.setattr(main, "_get_disk_io_status", lambda: {"supported": False})
    monkeypatch.setattr(main, "get_collector_status", lambda: {"status": "RUNNING", "stats": {}})
    monkeypatch.setattr(main, "_build_time_sync_status", lambda: {"status": "OK"})

    def raise_snapshot_error():
        raise RuntimeError("snapshot unavailable")

    monkeypatch.setattr(
        "services.event_lock.get_event_lock_observability_snapshot",
        raise_snapshot_error,
    )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return None

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr("postgres_db.engine", FakeEngine())

    with caplog.at_level(logging.WARNING, logger="main"):
        status = main._build_system_status_payload()

    assert status["event_lock"] == {"alert_state": "UNKNOWN", "snapshot_error": True}
    assert status["neo4j"] == "CONNECTED"
    assert status["postgres"] == "CONNECTED"
    assert status["collector"]["status"] == "RUNNING"
    assert "Failed to build event lock observability snapshot" in caplog.text
    assert "snapshot unavailable" in caplog.text


class _FixedClock:
    def __init__(self, *values):
        self._values = list(values)

    def now(self, tz=UTC):
        value = self._values.pop(0)
        if tz is not None:
            return value.astimezone(tz) if value.tzinfo else value.replace(tzinfo=tz)
        return value


class _FakeNeo4jResult:
    def __init__(self, value):
        self._value = value

    def single(self):
        return {"neo4j_time": self._value}


class _FakeNeo4jSession:
    def __init__(self, value=None, error=None):
        self._value = value
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def run(self, query):
        assert query == "RETURN datetime() AS neo4j_time"
        if self._error:
            raise self._error
        return _FakeNeo4jResult(self._value)


class _FakeNeo4jDriver:
    def __init__(self, value=None, error=None):
        self._value = value
        self._error = error

    def session(self):
        return _FakeNeo4jSession(value=self._value, error=self._error)


def _time_sync_settings(warning_ms=1000.0, critical_ms=5000.0):
    return SimpleNamespace(warning_ms=warning_ms, critical_ms=critical_ms)


def _time_sync_status_for(neo4j_time, warning_ms=1000.0, critical_ms=5000.0):
    backend_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    clock = _FixedClock(backend_time, backend_time)
    return main._build_time_sync_status(
        driver=_FakeNeo4jDriver(neo4j_time),
        settings=_time_sync_settings(warning_ms, critical_ms),
        now_func=clock.now,
    )


def test_build_time_sync_status_reports_ok_warning_and_critical_skew():
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    ok = _time_sync_status_for(base_time + timedelta(milliseconds=500))
    warning = _time_sync_status_for(base_time + timedelta(milliseconds=1000))
    critical = _time_sync_status_for(base_time + timedelta(milliseconds=5000))

    assert ok["status"] == "OK"
    assert ok["skew_ms"] == 500.0
    assert ok["thresholds_ms"] == {"warning": 1000.0, "critical": 5000.0}
    assert ok["sources"] == {"reference": "backend", "compared": "neo4j"}
    assert ok["backend_time"] == "2026-01-01T12:00:00Z"
    assert ok["neo4j_time"] == "2026-01-01T12:00:00.500000Z"
    assert ok["error"] is None

    assert warning["status"] == "WARNING"
    assert warning["skew_ms"] == 1000.0
    assert critical["status"] == "CRITICAL"
    assert critical["skew_ms"] == 5000.0


def test_build_time_sync_status_returns_unknown_when_neo4j_time_query_fails():
    backend_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    clock = _FixedClock(backend_time)

    status = main._build_time_sync_status(
        driver=_FakeNeo4jDriver(error=RuntimeError("database unavailable")),
        settings=_time_sync_settings(),
        now_func=clock.now,
    )

    assert status["status"] == "UNKNOWN"
    assert status["skew_ms"] is None
    assert status["neo4j_time"] is None
    assert status["query_latency_ms"] is None
    assert status["thresholds_ms"] == {"warning": 1000.0, "critical": 5000.0}
    assert status["error"] == "neo4j_time_query_failed"


def test_build_time_sync_status_returns_unknown_for_invalid_temporal_value():
    status = _time_sync_status_for("not-a-date")

    assert status["status"] == "UNKNOWN"
    assert status["skew_ms"] is None
    assert status["neo4j_time"] is None
    assert status["error"] == "invalid_neo4j_time"


def test_build_system_status_payload_includes_time_sync_without_changing_service_fields(
    monkeypatch,
):
    neo4j_time = datetime(2026, 1, 1, 12, 0, 0, 500000, tzinfo=UTC)
    backend_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    clock = _FixedClock(backend_time, backend_time)

    monkeypatch.setattr(main, "verify_connection", lambda max_retries=1, retry_delay=0: None)
    monkeypatch.setattr(main, "_get_disk_io_status", lambda: {"supported": False})
    monkeypatch.setattr(main, "get_collector_status", lambda: {"status": "RUNNING", "stats": {}})
    monkeypatch.setattr(main, "get_db", lambda: _FakeNeo4jDriver(neo4j_time))
    monkeypatch.setattr(main, "get_time_sync_settings", lambda: _time_sync_settings())
    monkeypatch.setattr(main, "_utc_now", clock.now)
    monkeypatch.setattr(
        "services.event_lock.get_event_lock_observability_snapshot",
        lambda: {"alert_state": "OK"},
    )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return None

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr("postgres_db.engine", FakeEngine())

    status = main._build_system_status_payload()

    assert status["time_sync"]["status"] == "OK"
    assert status["time_sync"]["skew_ms"] == 500.0
    assert status["neo4j"] == "CONNECTED"
    assert status["postgres"] == "CONNECTED"
    assert status["collector"] == {"status": "RUNNING", "stats": {}}
    assert status["event_lock"] == {"alert_state": "OK"}


def test_get_system_status_returns_event_lock_snapshot_without_recording_history(monkeypatch):
    payload = {
        "cpu": 1.1,
        "ram": 2.2,
        "disk": 3.3,
        "disk_io": {"supported": False},
        "neo4j": "CONNECTED",
        "postgres": "CONNECTED",
        "collector": {"status": "RUNNING", "stats": {}},
        "event_lock": {"alert_state": "CRITICAL"},
        "startup_time": "startup",
    }
    record_calls = []

    monkeypatch.setattr(main, "_build_system_status_payload", lambda: payload)
    monkeypatch.setattr(
        main,
        "_record_system_status_snapshot",
        lambda *args, **kwargs: record_calls.append((args, kwargs)),
    )

    status = main.get_system_status()

    assert status["event_lock"] == {"alert_state": "CRITICAL"}
    assert status["neo4j"] == "CONNECTED"
    assert len(record_calls) == 0


def _patch_status_history_rows(monkeypatch, rows):
    class FakeQuery:
        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def all(self):
            return rows

    class FakeDb:
        def query(self, *_args, **_kwargs):
            return FakeQuery()

        def close(self):
            pass

    monkeypatch.setattr("postgres_db.SessionLocal", lambda: FakeDb())


def test_fetch_system_status_history_includes_freshness_metadata(monkeypatch):
    snapshot = type(
        "Snapshot",
        (),
        {
            "recorded_at": datetime(2026, 1, 1, 11, 31, 0),
            "cpu": 24.5,
            "ram": 61.2,
            "disk": 40.0,
            "disk_io_supported": True,
            "disk_read_bytes_per_sec": 1024.0,
            "disk_write_bytes_per_sec": 2048.0,
            "disk_busy_percentage": 12.5,
            "neo4j_status": "CONNECTED",
            "postgres_status": "CONNECTED",
            "collector_status": "RUNNING",
            "collector_cis_monitored": 8,
            "collector_metrics_collected": 120,
            "collector_metrics_failed": 1,
            "collector_jobs_per_min": 44.0,
            "collector_cycle_duration": 3.0,
        },
    )()
    _patch_status_history_rows(monkeypatch, [snapshot])
    monkeypatch.setattr(main, "_SYSTEM_STATUS_HISTORY_MIN_INTERVAL_SECONDS", 900)
    monkeypatch.setattr(main, "_SYSTEM_STATUS_HISTORY_STALE_THRESHOLD_SECONDS", 1800)

    history = _fetch_system_status_history(
        hours=168,
        limit=500,
        now=datetime(2026, 1, 1, 12, 0, 0),
    )

    assert history["snapshot_interval_seconds"] == 900
    assert history["stale_threshold_seconds"] == 1800
    assert history["latest_recorded_at"] == "2026-01-01T11:31:00Z"
    assert history["is_stale"] is False
    assert history["rows"][0]["recorded_at"] == "2026-01-01T11:31:00Z"


def test_fetch_system_status_history_marks_missing_rows_stale(monkeypatch):
    _patch_status_history_rows(monkeypatch, [])

    history = _fetch_system_status_history(
        hours=168,
        limit=500,
        now=datetime(2026, 1, 1, 12, 0, 0),
    )

    assert history["latest_recorded_at"] is None
    assert history["is_stale"] is True
    assert history["rows"] == []


def test_reload_system_status_env_settings_uses_safe_defaults(monkeypatch):
    monkeypatch.setenv("SYSTEM_STATUS_SNAPSHOTS_ENABLED", "off")
    monkeypatch.setenv("SYSTEM_STATUS_SNAPSHOT_INTERVAL_SECONDS", "30")
    monkeypatch.setenv("SYSTEM_STATUS_HISTORY_RETENTION_DAYS", "invalid")
    monkeypatch.setenv("SYSTEM_STATUS_HISTORY_STALE_THRESHOLD_SECONDS", "1801")

    _reload_system_status_env_settings()

    assert main._SYSTEM_STATUS_SNAPSHOTS_ENABLED is False
    assert main._SYSTEM_STATUS_HISTORY_MIN_INTERVAL_SECONDS == 900
    assert main._SYSTEM_STATUS_HISTORY_RETENTION_DAYS == 7
    assert main._SYSTEM_STATUS_HISTORY_STALE_THRESHOLD_SECONDS == 1801

    monkeypatch.setenv("SYSTEM_STATUS_SNAPSHOTS_ENABLED", "true")
    monkeypatch.setenv("SYSTEM_STATUS_SNAPSHOT_INTERVAL_SECONDS", "900")
    monkeypatch.setenv("SYSTEM_STATUS_HISTORY_RETENTION_DAYS", "7")
    monkeypatch.setenv("SYSTEM_STATUS_HISTORY_STALE_THRESHOLD_SECONDS", "1800")
    _reload_system_status_env_settings()


def test_register_system_status_snapshot_job_is_noop_when_disabled(monkeypatch):
    fake_scheduler = MagicMock()
    monkeypatch.setattr(main, "backup_scheduler", fake_scheduler)
    monkeypatch.setattr(main, "_SYSTEM_STATUS_SNAPSHOTS_ENABLED", False)

    result = _register_system_status_snapshot_job()

    assert result is False
    fake_scheduler.add_job.assert_not_called()


def test_register_system_status_snapshot_job_registers_interval_job(monkeypatch):
    fake_scheduler = MagicMock()
    monkeypatch.setattr(main, "backup_scheduler", fake_scheduler)
    monkeypatch.setattr(main, "_SYSTEM_STATUS_SNAPSHOTS_ENABLED", True)
    monkeypatch.setattr(main, "_SYSTEM_STATUS_HISTORY_MIN_INTERVAL_SECONDS", 900)

    result = _register_system_status_snapshot_job()

    assert result is True
    fake_scheduler.add_job.assert_called_once()
    _, kwargs = fake_scheduler.add_job.call_args
    assert kwargs["id"] == "system_status_snapshot"
    assert kwargs["replace_existing"] is True
    assert kwargs["max_instances"] == 1
    assert kwargs["coalesce"] is True
    trigger = kwargs["trigger"]
    assert trigger.interval.total_seconds() == 900
