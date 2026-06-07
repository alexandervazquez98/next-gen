from datetime import datetime, timedelta

from main import (
    _build_disk_io_status,
    _build_system_status_snapshot,
    _collect_disk_io_sample,
    _serialize_system_status_snapshot,
    _should_record_system_status_snapshot,
    _is_diskstats_device,
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
        "recorded_at": recorded_at.isoformat(),
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


def test_should_record_system_status_snapshot_honors_five_minute_throttle():
    now = datetime(2026, 1, 1, 12, 5, 0)
    latest = type("Snapshot", (), {"recorded_at": now - timedelta(minutes=4)})()
    stale = type("Snapshot", (), {"recorded_at": now - timedelta(minutes=5)})()

    assert _should_record_system_status_snapshot(None, now) is True
    assert _should_record_system_status_snapshot(latest, now) is False
    assert _should_record_system_status_snapshot(stale, now) is True
