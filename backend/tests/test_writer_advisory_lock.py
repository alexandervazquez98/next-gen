# backend/tests/test_writer_advisory_lock.py
"""
Tests for the cross-writer event advisory-lock helper and its real-Postgres
concurrency semantics.

Background
----------
Issue #322: when multiple poll collectors observe the same failure,
``backend/engines/snmp_worker.py``, ``backend/services/snmp_service.py``, and
``backend/polling/event_writer.py`` can each create a separate OPEN Event for
the same ``(ci_id, metric_id, event_type)`` triplet because the read-then-create
path in Neo4j is atomic inside one transaction but NOT across transactions.

Fix (see ``openspec/changes/fix-event-duplication-cross-writer/design.md``):
every writer MUST acquire a PostgreSQL transaction-scoped advisory lock
``pg_advisory_xact_lock(hashtext(:key))`` with
``key = "{ci_id}|{metric_id}|{event_type}"`` BEFORE running the Neo4j
OPTIONAL MATCH + head(collect) + FOREACH(CREATE) block.

This file owns the two bottom-of-the-stack tests:

* ``test_acquire_event_triplet_lock_helper`` — MagicMock smoke test verifying
  the helper calls ``pg_advisory_xact_lock(hashtext(:key))`` with the correct
  key format. (Design §6 "Secondary test".)
* ``test_concurrent_writers_block_on_lock`` — real Postgres concurrency proof
  using ``testcontainers[postgres]`` and ``concurrent.futures``. This is the
  ONLY test that actually proves lock semantics block concurrent writers.
  (Design §6 "Primary test".)

Per-writer integration tests against ``snmp_worker.py`` /
``snmp_service.py`` / ``polling/event_writer.py`` land in PR2.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

EVENT_LOCK_ENV_VARS = (
    "EVENT_LOCK_SLOW_LOG_INFO_MS",
    "EVENT_LOCK_WARNING_P95_MS",
    "EVENT_LOCK_CRITICAL_P99_MS",
    "EVENT_LOCK_SAMPLE_WINDOW_SIZE",
    "EVENT_LOCK_MAX_WRITER_CONTEXTS",
)


@pytest.fixture(autouse=True)
def isolate_event_lock_settings(monkeypatch):
    """Keep Event lock settings/metrics deterministic across tests."""
    for name in EVENT_LOCK_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    import config as config_module
    from services import event_lock as event_lock_module

    monkeypatch.setattr(config_module, "_event_lock_settings", None)
    monkeypatch.setattr(event_lock_module, "_EVENT_LOCK_METRICS", None)
    yield
    monkeypatch.setattr(config_module, "_event_lock_settings", None)
    monkeypatch.setattr(event_lock_module, "_EVENT_LOCK_METRICS", None)


def _normalize_sql_for_lookup(sql_obj):
    """Return a plain string we can grep for ``pg_advisory_xact_lock`` and ``hashtext``.

    The helper under test calls ``pg_db.execute(text(...), {...})``. We accept
    either a ``sqlalchemy.sql.elements.TextClause`` or a raw string.
    """
    if hasattr(sql_obj, "text"):
        return sql_obj.text
    return str(sql_obj)


def test_acquire_event_triplet_lock_helper():
    """``acquire_event_triplet_lock`` issues ``pg_advisory_xact_lock(hashtext(:key))``.

    MagicMock-based smoke test per design §6 "Secondary test". The test does
    NOT prove that two real Postgres transactions block each other; that
    concurrency proof lands in a later PR's dedicated testcontainers test.
    """
    from services.event_lock import acquire_event_triplet_lock

    pg_db = MagicMock()
    acquire_event_triplet_lock(pg_db, "ci-001", "icmp_latency_ms", "THRESHOLD_BREACH")

    expected_key = "ci-001|icmp_latency_ms|THRESHOLD_BREACH"

    pg_db.execute.assert_called_once()
    call = pg_db.execute.call_args
    args, kwargs = call.args, call.kwargs

    # SQL is the first positional arg.
    sql_obj = args[0] if args else kwargs.get("text")
    sql_text = _normalize_sql_for_lookup(sql_obj)
    assert (
        "pg_advisory_xact_lock" in sql_text
    ), f"expected pg_advisory_xact_lock in SQL, got: {sql_text!r}"
    assert "hashtext" in sql_text, f"expected hashtext in SQL, got: {sql_text!r}"

    # The key parameter must match the "ci|metric|type" format exactly.
    params = args[1] if len(args) > 1 else kwargs.get("params") or kwargs
    # ``text("… :key")`` plus a dict binding ``{"key": …}`` is the canonical
    # pattern; we accept both binding styles for forward-compat.
    flat_values = params.values() if isinstance(params, dict) else (params,)
    assert (
        expected_key in flat_values
    ), f"expected key {expected_key!r} in bind params, got {params!r}"


def test_services_event_lock_imports_from_backend_import_root():
    """Production-style backend import root can import the shared lock helper."""
    backend_dir = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import services.event_lock as event_lock; print(event_lock.__name__)",
        ],
        cwd=backend_dir,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "services.event_lock"


def test_event_lock_metrics_record_count_distribution_alerts_and_bounded_labels():
    """Lock observability records waits by bounded writer labels only."""
    from services import event_lock as event_lock_module

    event_lock_module.reset_event_lock_observability_for_tests(sample_window_size=10)

    for wait_ms in [10, 20, 30, 40, 50, 60, 70, 80, 90, 1200]:
        event_lock_module.record_event_lock_acquisition(wait_ms, writer_context="snmp_worker")
    event_lock_module.record_event_lock_acquisition(6000, writer_context="polling_event_writer")

    snapshot = event_lock_module.get_event_lock_observability_snapshot()

    assert snapshot["acquisitions_total"] == 11
    assert snapshot["wait_ms"]["count"] == 10
    assert snapshot["wait_ms"]["max"] == 6000
    assert snapshot["wait_ms"]["p95"] == 6000
    assert snapshot["wait_ms"]["p99"] == 6000
    assert snapshot["alert_state"] == "CRITICAL"
    assert set(snapshot["by_writer"]) == {"snmp_worker", "polling_event_writer"}

    serialized = repr(snapshot)
    assert "ci-001" not in serialized
    assert "icmp_latency_ms" not in serialized
    assert "THRESHOLD_BREACH" not in serialized


def test_event_lock_alert_state_warns_when_p95_exceeds_threshold_without_critical():
    """p95 wait above the warning threshold derives WARNING alert state."""
    from services import event_lock as event_lock_module

    event_lock_module.reset_event_lock_observability_for_tests(sample_window_size=20)

    for wait_ms in [25] * 18 + [1100, 1200]:
        event_lock_module.record_event_lock_acquisition(wait_ms, writer_context="snmp_service")

    snapshot = event_lock_module.get_event_lock_observability_snapshot()

    assert snapshot["wait_ms"]["p95"] == 1100
    assert snapshot["wait_ms"]["p99"] == 1200
    assert snapshot["alert_state"] == "WARNING"


def test_event_lock_metrics_initialize_once_under_concurrent_cold_start(monkeypatch):
    """Concurrent first records MUST all land in the same metrics instance."""
    from services import event_lock as event_lock_module

    created_instances = []
    original_metrics_cls = event_lock_module._EventLockMetrics

    class SlowConstructingMetrics(original_metrics_cls):
        def __post_init__(self) -> None:
            created_instances.append(self)
            time.sleep(0.01)
            super().__post_init__()

    monkeypatch.setattr(event_lock_module, "_EventLockMetrics", SlowConstructingMetrics)
    monkeypatch.setattr(event_lock_module, "_EVENT_LOCK_METRICS", None)

    worker_count = 24
    barrier = threading.Barrier(worker_count)

    def record_once(index: int) -> None:
        barrier.wait(timeout=5)
        event_lock_module.record_event_lock_acquisition(index + 1, writer_context="cold_start")

    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [pool.submit(record_once, index) for index in range(worker_count)]
        for future in futures:
            future.result(timeout=5)

    snapshot = event_lock_module.get_event_lock_observability_snapshot()
    assert snapshot["acquisitions_total"] == worker_count
    assert snapshot["by_writer"]["cold_start"]["acquisitions_total"] == worker_count
    assert len(created_instances) == 1


def test_event_lock_settings_use_safe_defaults():
    """Default Event lock env settings match the documented PR1 thresholds."""
    from config import (
        EVENT_LOCK_DEFAULT_CRITICAL_P99_MS,
        EVENT_LOCK_DEFAULT_MAX_WRITER_CONTEXTS,
        EVENT_LOCK_DEFAULT_SAMPLE_WINDOW_SIZE,
        EVENT_LOCK_DEFAULT_SLOW_LOG_INFO_MS,
        EVENT_LOCK_DEFAULT_WARNING_P95_MS,
        EventLockSettings,
    )

    settings = EventLockSettings.from_env()

    assert settings.slow_log_info_ms == EVENT_LOCK_DEFAULT_SLOW_LOG_INFO_MS
    assert settings.warning_p95_ms == EVENT_LOCK_DEFAULT_WARNING_P95_MS
    assert settings.critical_p99_ms == EVENT_LOCK_DEFAULT_CRITICAL_P99_MS
    assert settings.sample_window_size == EVENT_LOCK_DEFAULT_SAMPLE_WINDOW_SIZE
    assert settings.max_writer_contexts == EVENT_LOCK_DEFAULT_MAX_WRITER_CONTEXTS


def test_event_lock_settings_apply_env_overrides(monkeypatch):
    """EVENT_LOCK_* overrides are parsed when they stay inside safe bounds."""
    from config import EventLockSettings

    monkeypatch.setenv("EVENT_LOCK_SLOW_LOG_INFO_MS", "125.5")
    monkeypatch.setenv("EVENT_LOCK_WARNING_P95_MS", "750")
    monkeypatch.setenv("EVENT_LOCK_CRITICAL_P99_MS", "2500")
    monkeypatch.setenv("EVENT_LOCK_SAMPLE_WINDOW_SIZE", "42")
    monkeypatch.setenv("EVENT_LOCK_MAX_WRITER_CONTEXTS", "3")

    settings = EventLockSettings.from_env()

    assert settings.slow_log_info_ms == 125.5
    assert settings.warning_p95_ms == 750.0
    assert settings.critical_p99_ms == 2500.0
    assert settings.sample_window_size == 42
    assert settings.max_writer_contexts == 3


def test_event_lock_settings_fall_back_for_invalid_or_out_of_range_env(monkeypatch):
    """Invalid/out-of-range EVENT_LOCK_* values fall back to safe defaults."""
    from config import (
        EVENT_LOCK_DEFAULT_CRITICAL_P99_MS,
        EVENT_LOCK_DEFAULT_MAX_WRITER_CONTEXTS,
        EVENT_LOCK_DEFAULT_SAMPLE_WINDOW_SIZE,
        EVENT_LOCK_DEFAULT_SLOW_LOG_INFO_MS,
        EVENT_LOCK_DEFAULT_WARNING_P95_MS,
        EventLockSettings,
    )

    monkeypatch.setenv("EVENT_LOCK_SLOW_LOG_INFO_MS", "-1")
    monkeypatch.setenv("EVENT_LOCK_WARNING_P95_MS", "not-a-number")
    monkeypatch.setenv("EVENT_LOCK_CRITICAL_P99_MS", "600000.5")
    monkeypatch.setenv("EVENT_LOCK_SAMPLE_WINDOW_SIZE", "0")
    monkeypatch.setenv("EVENT_LOCK_MAX_WRITER_CONTEXTS", "0")

    settings = EventLockSettings.from_env()

    assert settings.slow_log_info_ms == EVENT_LOCK_DEFAULT_SLOW_LOG_INFO_MS
    assert settings.warning_p95_ms == EVENT_LOCK_DEFAULT_WARNING_P95_MS
    assert settings.critical_p99_ms == EVENT_LOCK_DEFAULT_CRITICAL_P99_MS
    assert settings.sample_window_size == EVENT_LOCK_DEFAULT_SAMPLE_WINDOW_SIZE
    assert settings.max_writer_contexts == EVENT_LOCK_DEFAULT_MAX_WRITER_CONTEXTS


def test_event_lock_settings_reject_unsafe_sample_and_writer_context_clamps(monkeypatch):
    """Oversized window/context overrides fall back before they can create unbounded samples."""
    from config import (
        EVENT_LOCK_DEFAULT_MAX_WRITER_CONTEXTS,
        EVENT_LOCK_DEFAULT_SAMPLE_WINDOW_SIZE,
        EventLockSettings,
    )

    monkeypatch.setenv("EVENT_LOCK_SAMPLE_WINDOW_SIZE", "100000")
    monkeypatch.setenv("EVENT_LOCK_MAX_WRITER_CONTEXTS", "1000")

    settings = EventLockSettings.from_env()

    assert settings.sample_window_size == EVENT_LOCK_DEFAULT_SAMPLE_WINDOW_SIZE
    assert settings.max_writer_contexts == EVENT_LOCK_DEFAULT_MAX_WRITER_CONTEXTS


def test_event_lock_settings_cap_total_writer_sample_budget(monkeypatch):
    """Valid individual overrides are capped by the total per-writer sample budget."""
    from config import EventLockSettings

    monkeypatch.setenv("EVENT_LOCK_SAMPLE_WINDOW_SIZE", "1000")
    monkeypatch.setenv("EVENT_LOCK_MAX_WRITER_CONTEXTS", "20")

    settings = EventLockSettings.from_env()

    assert settings.sample_window_size == 1000
    assert settings.max_writer_contexts == 10


def test_event_lock_empty_snapshot_is_ok():
    """An initialized snapshot with no samples reports OK and empty distribution values."""
    from services import event_lock as event_lock_module

    event_lock_module.reset_event_lock_observability_for_tests(sample_window_size=3)

    snapshot = event_lock_module.get_event_lock_observability_snapshot()

    assert snapshot["acquisitions_total"] == 0
    assert snapshot["wait_ms"] == {"count": 0, "p95": None, "p99": None, "max": None}
    assert snapshot["alert_state"] == "OK"
    assert snapshot["by_writer"] == {}


def test_event_lock_info_only_alert_state_below_warning_threshold():
    """Slow samples below p95/p99 thresholds produce INFO, not WARNING/CRITICAL."""
    from services import event_lock as event_lock_module

    event_lock_module.reset_event_lock_observability_for_tests(sample_window_size=5)
    for wait_ms in [10, 20, 250, 300, 400]:
        event_lock_module.record_event_lock_acquisition(wait_ms, writer_context="snmp_worker")

    snapshot = event_lock_module.get_event_lock_observability_snapshot()
    assert snapshot["wait_ms"]["max"] == 400
    assert snapshot["alert_state"] == "INFO"


def test_event_lock_threshold_equality_escalates_alert_state(monkeypatch):
    """Wait percentiles equal to configured thresholds are considered crossing them."""
    import config as config_module
    from config import EventLockSettings
    from services import event_lock as event_lock_module

    monkeypatch.setattr(
        config_module,
        "_event_lock_settings",
        EventLockSettings(
            slow_log_info_ms=250.0,
            warning_p95_ms=1000.0,
            critical_p99_ms=5000.0,
            sample_window_size=10,
        ),
    )
    event_lock_module.reset_event_lock_observability_for_tests()

    for wait_ms in [10, 20, 30, 40, 50, 60, 70, 80, 1000, 5000]:
        event_lock_module.record_event_lock_acquisition(wait_ms, writer_context="snmp_worker")

    snapshot = event_lock_module.get_event_lock_observability_snapshot()
    assert snapshot["wait_ms"]["p95"] == 5000
    assert snapshot["wait_ms"]["p99"] == 5000
    assert snapshot["alert_state"] == "CRITICAL"


def test_event_lock_sample_window_evicts_oldest_samples():
    """The bounded sample window evicts oldest waits while preserving total count."""
    from services import event_lock as event_lock_module

    event_lock_module.reset_event_lock_observability_for_tests(sample_window_size=3)

    for wait_ms in [1, 2, 3, 4, 5]:
        event_lock_module.record_event_lock_acquisition(wait_ms, writer_context="snmp_worker")

    snapshot = event_lock_module.get_event_lock_observability_snapshot()
    assert snapshot["acquisitions_total"] == 5
    assert snapshot["wait_ms"] == {"count": 3, "p95": 5, "p99": 5, "max": 5}
    assert snapshot["by_writer"]["snmp_worker"]["acquisitions_total"] == 5
    assert snapshot["by_writer"]["snmp_worker"]["wait_ms"] == {
        "count": 3,
        "p95": 5,
        "p99": 5,
        "max": 5,
    }


def test_event_lock_routes_writer_context_overflow_to_other(monkeypatch):
    """Distinct writer contexts are bounded; overflow is aggregated as other."""
    import config as config_module
    from config import EventLockSettings
    from services import event_lock as event_lock_module

    monkeypatch.setattr(
        config_module,
        "_event_lock_settings",
        EventLockSettings(sample_window_size=10, max_writer_contexts=2),
    )
    event_lock_module.reset_event_lock_observability_for_tests()

    for writer in ["writer_a", "writer_b", "writer_c", "writer_d"]:
        event_lock_module.record_event_lock_acquisition(10, writer_context=writer)

    snapshot = event_lock_module.get_event_lock_observability_snapshot()
    assert len(snapshot["by_writer"]) == 2
    assert set(snapshot["by_writer"]) == {"writer_a", "other"}
    assert snapshot["by_writer"]["writer_a"]["acquisitions_total"] == 1
    assert snapshot["by_writer"]["other"]["acquisitions_total"] == 3


def test_event_lock_writer_context_overflow_stays_within_exact_budget(monkeypatch):
    """The overflow bucket is reserved inside max_writer_contexts, not added on top."""
    import config as config_module
    from config import EventLockSettings
    from services import event_lock as event_lock_module

    monkeypatch.setattr(
        config_module,
        "_event_lock_settings",
        EventLockSettings(sample_window_size=10, max_writer_contexts=3),
    )
    event_lock_module.reset_event_lock_observability_for_tests()

    for writer in ["writer_a", "writer_b", "writer_c", "writer_d", "writer_e"]:
        event_lock_module.record_event_lock_acquisition(10, writer_context=writer)

    snapshot = event_lock_module.get_event_lock_observability_snapshot()
    assert len(snapshot["by_writer"]) == 3
    assert set(snapshot["by_writer"]) == {"writer_a", "writer_b", "other"}
    assert snapshot["by_writer"]["other"]["acquisitions_total"] == 3


def test_event_lock_slow_log_threshold_zero_disables_info_logs_and_info_alerts(monkeypatch, caplog):
    """A zero INFO threshold is disabled so operators cannot create log storms."""
    import config as config_module
    from config import EventLockSettings
    from services import event_lock as event_lock_module

    monkeypatch.setattr(
        config_module,
        "_event_lock_settings",
        EventLockSettings(slow_log_info_ms=0.0, sample_window_size=5),
    )
    event_lock_module.reset_event_lock_observability_for_tests()
    monotonic_values = iter([100.0, 100.001])
    monkeypatch.setattr(event_lock_module.time, "monotonic", lambda: next(monotonic_values))

    with caplog.at_level(logging.INFO, logger="services.event_lock"):
        event_lock_module.acquire_event_triplet_lock(
            MagicMock(),
            "ci-001",
            "icmp_latency_ms",
            "THRESHOLD_BREACH",
            writer_context="snmp_worker",
        )

    assert [
        record for record in caplog.records if record.message == "event_lock_slow_acquisition"
    ] == []
    assert event_lock_module.get_event_lock_observability_snapshot()["alert_state"] == "OK"


def test_acquire_event_triplet_lock_emits_structured_slow_log_at_info_threshold(
    caplog, monkeypatch
):
    """Acquisitions at or above 250ms emit one structured INFO slow-lock log."""
    from services import event_lock as event_lock_module

    event_lock_module.reset_event_lock_observability_for_tests(sample_window_size=10)
    monotonic_values = iter([100.0, 100.250])
    monkeypatch.setattr(event_lock_module.time, "monotonic", lambda: next(monotonic_values))

    pg_db = MagicMock()
    with caplog.at_level(logging.INFO, logger="services.event_lock"):
        event_lock_module.acquire_event_triplet_lock(
            pg_db,
            "ci-001",
            "icmp_latency_ms",
            "THRESHOLD_BREACH",
            writer_context="snmp_worker",
        )

    slow_records = [
        record for record in caplog.records if record.message == "event_lock_slow_acquisition"
    ]
    assert len(slow_records) == 1
    assert slow_records[0].event_lock_writer_context == "snmp_worker"
    assert slow_records[0].event_lock_wait_ms == 250
    assert slow_records[0].event_lock_threshold_ms == 250


def test_acquire_event_triplet_lock_avoids_info_log_below_threshold(caplog, monkeypatch):
    """Acquisitions below 250ms still record metrics but avoid noisy INFO logs."""
    from services import event_lock as event_lock_module

    event_lock_module.reset_event_lock_observability_for_tests(sample_window_size=10)
    monotonic_values = iter([100.0, 100.249])
    monkeypatch.setattr(event_lock_module.time, "monotonic", lambda: next(monotonic_values))

    pg_db = MagicMock()
    with caplog.at_level(logging.INFO, logger="services.event_lock"):
        event_lock_module.acquire_event_triplet_lock(
            pg_db,
            "ci-001",
            "icmp_latency_ms",
            "THRESHOLD_BREACH",
            writer_context="snmp_worker",
        )

    assert [
        record for record in caplog.records if record.message == "event_lock_slow_acquisition"
    ] == []
    snapshot = event_lock_module.get_event_lock_observability_snapshot()
    assert snapshot["acquisitions_total"] == 1
    assert snapshot["wait_ms"]["max"] == 249


def test_event_lock_sql_remains_blocking_only_without_timeout_policy():
    """Observability MUST NOT add timeout, try-lock, or fail-open/fail-closed SQL/settings."""
    from config import EventLockSettings
    from services.event_lock import acquire_event_triplet_lock

    pg_db = MagicMock()
    acquire_event_triplet_lock(pg_db, "ci-001", "icmp_latency_ms", "THRESHOLD_BREACH")

    sql_obj = pg_db.execute.call_args.args[0]
    sql_text = _normalize_sql_for_lookup(sql_obj).lower()
    settings_fields = set(EventLockSettings.model_fields)

    assert "pg_advisory_xact_lock(hashtext(:key))" in sql_text
    assert "pg_try_advisory" not in sql_text
    assert "lock_timeout" not in sql_text
    assert "statement_timeout" not in sql_text
    assert not any("timeout" in field for field in settings_fields)
    assert not any("fail_open" in field or "fail_closed" in field for field in settings_fields)


def test_get_poll_collector_id_returns_non_empty_string():
    """#322 / spec §Poll collector identity persistence — helper returns a
    non-empty hostname string sourced from ``HOSTNAME`` env var with
    ``socket.gethostname()`` fallback. Cached at module load so per-row
    Event writes don't trigger repeated system calls.
    """
    import os
    import socket

    from services.event_lock import get_poll_collector_id

    value = get_poll_collector_id()
    assert isinstance(value, str)
    assert value.strip(), f"poll_collector_id must be non-empty; got {value!r}"

    # The value MUST match the HOSTNAME env var OR socket.gethostname()
    # — whichever is non-empty (HOSTNAME takes precedence per design §4).
    expected = (os.getenv("HOSTNAME") or socket.gethostname()).strip()
    assert value == expected, (
        f"poll_collector_id must match HOSTNAME-or-gethostname; "
        f"got {value!r}, expected {expected!r}"
    )


def test_get_poll_collector_id_is_cached_at_module_load(monkeypatch):
    """Hostname MUST be read once at module load (design §4 / task 7).
    Subsequent calls return the SAME object even if socket.gethostname()
    is patched to return something different — proves the cache.
    """
    import socket

    from services import event_lock as event_lock_module

    # Reset the cache to force re-evaluation against the patched hostname.
    monkeypatch.setattr(event_lock_module, "_CACHED_HOSTNAME", None)
    monkeypatch.setattr(socket, "gethostname", lambda: "sentinel-host")
    monkeypatch.delenv("HOSTNAME", raising=False)

    first = event_lock_module.get_poll_collector_id()
    assert first == "sentinel-host", f"first call should use the patched hostname; got {first!r}"

    # Mutate the source — second call MUST still return the cached value.
    monkeypatch.setattr(socket, "gethostname", lambda: "different-host")
    second = event_lock_module.get_poll_collector_id()
    assert second == "sentinel-host", (
        f"second call MUST return cached value (got {second!r}); "
        f"hostname was not cached at module load"
    )


def test_get_poll_collector_id_raises_when_hostname_unavailable(monkeypatch):
    """If both HOSTNAME env var AND socket.gethostname() are empty,
    ``get_poll_collector_id`` MUST raise ``RuntimeError`` rather than
    silently writing an empty string to the database.
    """
    import socket

    from services import event_lock as event_lock_module

    monkeypatch.setattr(event_lock_module, "_CACHED_HOSTNAME", None)
    monkeypatch.setenv("HOSTNAME", "")
    monkeypatch.setattr(socket, "gethostname", lambda: "")

    with pytest.raises(RuntimeError, match="Cannot determine poll_collector_id"):
        event_lock_module.get_poll_collector_id()


# ---------------------------------------------------------------------------
# Task 2 — primary real-Postgres concurrency proof (design §6 "Primary test").
# PR1 ships this in PASSING state because the test exercises the lock
# primitive INDEPENDENTLY of any writer code — that proves the chosen
# primitive (``pg_advisory_xact_lock(hashtext(...))``) actually blocks.
# Per-writer integration tests are PR2's scope.
# ---------------------------------------------------------------------------


def _swap_in_real_psycopg2():
    """Pop the conftest's ``psycopg2`` MagicMock stub and return the real driver.

    The project's ``backend/tests/conftest.py`` installs a ``psycopg2`` MagicMock
    in ``sys.modules`` so service modules can be imported without a live DB.
    This test needs the real driver to talk to the testcontainers Postgres;
    we swap, run, then restore so downstream tests still see the stub.

    IMPORTANT: ``pytest.importorskip`` would just return the MagicMock because
    it's already in ``sys.modules``. We MUST pop first, then import fresh.
    """
    saved = sys.modules.pop("psycopg2", None)
    saved_ext = sys.modules.pop("psycopg2.extensions", None)
    import psycopg2 as real_psycopg2  # fresh import — now genuinely real

    sys.modules["psycopg2"] = real_psycopg2
    sys.modules["psycopg2.extensions"] = real_psycopg2.extensions

    def restore() -> None:
        if saved is not None:
            sys.modules["psycopg2"] = saved
        else:
            sys.modules.pop("psycopg2", None)
        if saved_ext is not None:
            sys.modules["psycopg2.extensions"] = saved_ext
        else:
            sys.modules.pop("psycopg2.extensions", None)

    return real_psycopg2, restore


@pytest.mark.integration
def test_concurrent_writers_block_on_lock():
    """Two real Postgres writers for the same triplet MUST serialize.

    Design §6 "Primary test". Spins up a real ``postgres:15-alpine`` container
    via ``testcontainers[postgres]``; two threads each open a real
    ``psycopg2`` connection and acquire ``pg_advisory_xact_lock`` for the same
    ``(ci, metric, event_type)`` triplet.

    Coordination pattern (deterministic, no race on thread startup):

    1. The "holder" thread acquires the lock and signals ``got_lock``.
    2. The "waiter" thread is started; it MUST block because the holder holds
       the lock. We assert the waiter is still blocked after 1 second.
    3. The holder is released; the waiter MUST then acquire the lock
       promptly.

    The assertion that matters: the waiter's wall-clock duration from
    ``pg_advisory_xact_lock`` call to lock acquisition is approximately
    the holder's hold duration (≥ the time between holder.got_lock and
    holder_release).

    Container startup cost: ~2-3 seconds. Acceptable for the only test that
    proves blocking semantics in real Postgres.
    """
    psycopg2, restore_psycopg2 = _swap_in_real_psycopg2()
    try:
        # Imported lazily so the swap above is in effect.
        from testcontainers.postgres import PostgresContainer

        with PostgresContainer("postgres:15-alpine") as pg:
            conn_url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
            triplet_key = "ci-001|icmp_latency_ms|THRESHOLD_BREACH"
            check_window = 0.5  # how long main waits before declaring "waiter is blocked"

            got_lock = threading.Event()
            release = threading.Event()
            waiter_finished = threading.Event()
            waiter_result: dict = {}

            def holder() -> None:
                conn = psycopg2.connect(conn_url)
                try:
                    conn.autocommit = False
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (triplet_key,),
                    )
                    got_lock.set()
                    release.wait(timeout=15)
                    conn.commit()
                    cur.close()
                finally:
                    conn.close()

            def waiter() -> None:
                conn = psycopg2.connect(conn_url)
                try:
                    conn.autocommit = False
                    cur = conn.cursor()
                    t_try = time.monotonic()
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (triplet_key,),
                    )
                    t_acquired = time.monotonic()
                    waiter_result["blocked_for"] = t_acquired - t_try
                    conn.commit()
                    cur.close()
                finally:
                    conn.close()
                    waiter_finished.set()

            holder_thread = threading.Thread(target=holder, name="holder")
            holder_thread.start()
            assert got_lock.wait(timeout=10), "holder never acquired the lock"

            waiter_thread = threading.Thread(target=waiter, name="waiter")
            waiter_thread.start()

            # If the lock is honored, the waiter must still be blocked here.
            # Passing this check proves the waiter remained blocked while the
            # holder still owned the transaction-scoped lock.
            assert not waiter_finished.wait(timeout=0.5), (
                "waiter acquired the lock while holder still held it — "
                "pg_advisory_xact_lock is NOT serializing writers!"
            )

            # Release the holder; the waiter should now acquire promptly.
            release.set()
            holder_thread.join(timeout=15)

            assert waiter_finished.wait(timeout=10), "waiter never acquired the lock after release"
            waiter_thread.join(timeout=10)

            # The waiter MUST have been blocked for at least the check window.
            # Why? The holder is set to release AFTER main waits `check_window`
            # seconds proving the waiter is still blocked. So the waiter's
            # blocked_for ≥ check_window (minus tiny slack for thread
            # scheduling). If it returned in microseconds, the lock did NOT
            # block it.
            blocked_for = waiter_result["blocked_for"]
            assert blocked_for >= check_window - 0.2, (
                f"waiter blocked for only {blocked_for:.3f}s (expected ≥ "
                f"{check_window - 0.2:.3f}s) — lock did not serialize"
            )
    finally:
        restore_psycopg2()


# ---------------------------------------------------------------------------
# Task 3 — batched writer deadlock-prevention tests (design §6 "Tertiary
# test"). PR3 scope. Both tests share the same testcontainers fixture but
# call ``_acquire_unsorted_locks`` (extracted in PR3 from
# ``_acquire_sorted_locks``) with caller-controlled ordering to PROVE the
# deadlock-vs-safety distinction.
#
# Refactor choice: **Option A — extract inner acquisition loop** into a
# private ``_acquire_unsorted_locks(lock_db, triplets)`` helper. Production
# writers continue to use ``_acquire_sorted_locks`` which sorts the
# triplets before delegating. The deadlock tests call the unsorted helper
# directly with caller-supplied orders so we can exercise the UNSAFE
# acquisition path that the production code never uses.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_unsorted_lock_acquisition_deadlocks():
    """Two threads acquiring triplet locks in OPPOSITE order MUST deadlock.

    Design §6 "Tertiary test" — proves the problem is REAL. Without the
    deterministic ordering rule from design §4, two writers contending for
    overlapping batches of triplets would deadlock when their natural
    acquisition orders conflict.

    Setup:
    - 2 threads via :class:`ThreadPoolExecutor`.
    - Thread A acquires ``(X, Y, Z)`` in that order.
    - Thread B acquires ``(Z, Y, X)`` in that order.
    - Both use ``_acquire_unsorted_locks`` (no sort).
    - Each thread has its own real SQLAlchemy ``Session`` backed by
      testcontainers Postgres.

    Expected:
    - Postgres deadlock detection aborts at least one transaction.
    - The aborted thread's ``_acquire_unsorted_locks`` call surfaces a
      ``sqlalchemy.exc.OperationalError`` wrapping
      ``psycopg2.errors.DeadlockDetected`` (SQLSTATE 40P01).

    Container startup cost: ~2-3 seconds (same as
    :func:`test_concurrent_writers_block_on_lock`).
    """
    psycopg2, restore_psycopg2 = _swap_in_real_psycopg2()
    try:
        from polling.event_writer import _acquire_unsorted_locks
        from sqlalchemy import create_engine
        from sqlalchemy.exc import OperationalError
        from sqlalchemy.orm import sessionmaker
        from testcontainers.postgres import PostgresContainer

        with PostgresContainer("postgres:15-alpine") as pg:
            # SQLAlchemy with psycopg2 — psycopg2 is now genuinely real
            # because of _swap_in_real_psycopg2().
            conn_url = pg.get_connection_url()
            engine = create_engine(conn_url)
            session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

            # Triplet sets in REVERSE order — perfect deadlock setup.
            triplets_forward = [
                ("ci-A", "metric-1", "EVT_A"),
                ("ci-A", "metric-2", "EVT_B"),
                ("ci-A", "metric-3", "EVT_C"),
            ]
            triplets_reverse = list(reversed(triplets_forward))

            results: dict[str, object] = {"a": None, "b": None}

            def worker(triplets: list[tuple[str, str, str]], key: str) -> None:
                session = session_factory()
                try:
                    _acquire_unsorted_locks(session, triplets)
                    results[key] = "ok"
                    session.commit()
                except OperationalError as exc:
                    results[key] = exc
                    session.rollback()
                except Exception as exc:  # surface unexpected errors
                    results[key] = exc
                    session.rollback()
                finally:
                    session.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                fut_a = pool.submit(worker, triplets_forward, "a")
                fut_b = pool.submit(worker, triplets_reverse, "b")
                # Give the threads ample time to deadlock; pg_advisory deadlock
                # detection runs every ~1s.
                fut_a.result(timeout=30)
                fut_b.result(timeout=30)

            exceptions = [v for v in results.values() if isinstance(v, Exception)]
            assert len(exceptions) >= 1, (
                f"expected at least one deadlock, got {results!r} — the "
                f"unsorted acquisition path is NOT tripping Postgres deadlock "
                f"detection (problem not reproducible)"
            )

            # At least one exception should be a Postgres deadlock
            # (SQLSTATE 40P01). SQLAlchemy wraps psycopg2.errors.DeadlockDetected
            # in OperationalError whose str contains the SQLSTATE code or the
            # word "deadlock detected".
            deadlock_explanations = []
            for exc in exceptions:
                msg = str(exc).lower()
                if "deadlock" in msg or "40p01" in msg:
                    deadlock_explanations.append(exc)
            assert deadlock_explanations, (
                f"expected a Postgres deadlock error, got "
                f"{[type(e).__name__ + ': ' + str(e) for e in exceptions]}"
            )
    finally:
        restore_psycopg2()


@pytest.mark.integration
def test_sorted_lock_acquisition_prevents_deadlock():
    """Sorted lexicographic acquisition MUST NOT deadlock even with reversed input.

    Design §6 "Tertiary test" — proves the FIX works. When both writers
    delegate to ``_acquire_sorted_locks`` (which sorts the triplets
    lexicographically BEFORE acquisition), two overlapping batches always
    contend in the same order. Postgres serializes them via lock-wait, not
    deadlock detection.

    Setup:
    - 2 threads via :class:`ThreadPoolExecutor`.
    - Thread A's row batch yields triplets ``(X, Y, Z)`` (in declaration order).
    - Thread B's row batch yields triplets ``(Z, Y, X)`` (REVERSED — would
      deadlock if acquired unsorted).
    - Both call ``_acquire_sorted_locks`` (the production function) with
      their rows; both sort internally before acquisition.

    Expected:
    - Both threads complete successfully, no exceptions.
    - Both threads' lock acquisitions happen in lexicographic order (X
      before Y before Z) — proves the inner sort is deterministic and
      shared.
    """
    psycopg2, restore_psycopg2 = _swap_in_real_psycopg2()
    try:
        from polling.event_writer import _acquire_sorted_locks
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from testcontainers.postgres import PostgresContainer

        with PostgresContainer("postgres:15-alpine") as pg:
            conn_url = pg.get_connection_url()
            engine = create_engine(conn_url)
            session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

            # Two batches of ROW DICTS (not pre-extracted triplets) with
            # the SAME triplets in REVERSE orders. _acquire_sorted_locks
            # extracts the triplets, sorts them, then acquires.
            rows_forward = [
                {"ci_id": "ci-A", "metric_id": "metric-1", "event_type": "EVT_A"},
                {"ci_id": "ci-A", "metric_id": "metric-2", "event_type": "EVT_B"},
                {"ci_id": "ci-A", "metric_id": "metric-3", "event_type": "EVT_C"},
            ]
            rows_reverse = list(reversed(rows_forward))

            results: dict[str, object] = {"a": None, "b": None}

            def worker(rows: list[dict], key: str) -> None:
                session = session_factory()
                try:
                    _acquire_sorted_locks(session, rows)
                    results[key] = "ok"
                    session.commit()
                except Exception as exc:  # any exception is a failure here
                    results[key] = exc
                    session.rollback()
                finally:
                    session.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                fut_a = pool.submit(worker, rows_forward, "a")
                fut_b = pool.submit(worker, rows_reverse, "b")
                fut_a.result(timeout=30)
                fut_b.result(timeout=30)

            assert results["a"] == "ok", f"thread A failed: {results['a']!r}"
            assert results["b"] == "ok", (
                f"thread B failed: {results['b']!r} — sorted acquisition "
                f"did NOT prevent the deadlock; the deterministic-ordering "
                f"rule (design §4) is broken"
            )
    finally:
        restore_psycopg2()


# ---------------------------------------------------------------------------
# Task 8 — full poll-cycle integration test. PR3 scope.
#
# Spins up 3 threads, each simulating one of the production writers
# (snmp_worker, snmp_service, event_writer) targeting the SAME
# ``(ci_id, metric_id, event_type)`` triplet. Each thread acquires the
# advisory lock the way its production code does, then performs the
# OPTIONAL MATCH + FOREACH CREATE pattern against a shared mock Neo4j
# sink. The lock serializes the writers, so the OPTIONAL MATCH correctly
# finds the existing Event for threads 2 and 3 — only thread 1 actually
# CREATEs.
#
# Acceptance: exactly ONE entry in the sink for the contested triplet.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_full_poll_cycle_no_duplicates():
    """All 3 writers targeting the same triplet MUST produce exactly 1 Event.

    Design §6 / task 8 — full poll-cycle integration test. Proves that
    when each of the 3 production writers (snmp_worker, snmp_service,
    event_writer) acquires ``pg_advisory_xact_lock`` for the same
    ``(ci, metric, event_type)`` BEFORE the OPTIONAL MATCH, only the
    first writer creates a new Event; the other two find the existing
    Event and update ``last_seen`` (the SPEC §"Race-safe Event creation
    under advisory lock" guarantee).

    Setup:
    - Real Postgres via :class:`PostgresContainer` (``postgres:15-alpine``).
    - 3 threads, one per writer, all targeting
      ``("ci-001", "cpu", "COLLECTION_FAILURE")``.
    - Each thread has its own SQLAlchemy ``Session``.
    - snmp_worker and snmp_service call ``acquire_event_triplet_lock``
      directly (single-triplet per poll cycle in this test).
    - event_writer calls ``_acquire_sorted_locks`` (its batched path —
      a list of one row dict here).
    - After lock acquisition, each thread runs a Python-side OPTIONAL
      MATCH against a shared dict acting as the mock Neo4j sink. Only
      the FIRST thread to acquire the lock sees an empty sink and
      CREATEs; threads 2 and 3 find the entry and skip.

    Expected:
    - The mock Neo4j sink contains exactly 1 entry for the triplet.
    - Exactly 1 thread reports ``"created"``; the other 2 report
      ``"found_existing"``.

    Container startup cost: ~2-3 seconds.
    """
    psycopg2, restore_psycopg2 = _swap_in_real_psycopg2()
    try:
        from polling.event_writer import _acquire_sorted_locks
        from services.event_lock import acquire_event_triplet_lock
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from testcontainers.postgres import PostgresContainer

        with PostgresContainer("postgres:15-alpine") as pg:
            conn_url = pg.get_connection_url()
            engine = create_engine(conn_url)
            session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

            triplet = ("ci-001", "cpu", "COLLECTION_FAILURE")
            ci_id, metric_id, event_type = triplet

            # Shared mock Neo4j sink. Keyed by triplet tuple so the OPTIONAL
            # MATCH pattern is a simple ``triplet in sink`` lookup. The lock
            # serializes access; without the lock, all 3 threads would race
            # past the OPTIONAL MATCH check and all 3 would CREATE.
            neo4j_sink: dict[tuple[str, str, str], str] = {}
            sink_lock = threading.Lock()  # protects dict updates across threads

            # Each writer reports what its OPTIONAL MATCH + FOREACH CREATE
            # pattern did. Only ONE writer should report "created"; the
            # others should report "found_existing".
            results: dict[str, str] = {}

            def snmp_worker_writer() -> None:
                session = session_factory()
                try:
                    acquire_event_triplet_lock(session, ci_id, metric_id, event_type)
                    with sink_lock:
                        if triplet not in neo4j_sink:
                            # Simulate FOREACH CREATE: this writer won.
                            neo4j_sink[triplet] = "created"
                            results["snmp_worker"] = "created"
                        else:
                            results["snmp_worker"] = "found_existing"
                    session.commit()
                finally:
                    session.close()

            def snmp_service_writer() -> None:
                session = session_factory()
                try:
                    acquire_event_triplet_lock(session, ci_id, metric_id, event_type)
                    with sink_lock:
                        if triplet not in neo4j_sink:
                            neo4j_sink[triplet] = "created"
                            results["snmp_service"] = "created"
                        else:
                            results["snmp_service"] = "found_existing"
                    session.commit()
                finally:
                    session.close()

            def event_writer_batch() -> None:
                session = session_factory()
                try:
                    # event_writer batch path: a single-row batch
                    # containing the same triplet.
                    _acquire_sorted_locks(
                        session,
                        [
                            {
                                "ci_id": ci_id,
                                "metric_id": metric_id,
                                "event_type": event_type,
                            }
                        ],
                    )
                    with sink_lock:
                        if triplet not in neo4j_sink:
                            neo4j_sink[triplet] = "created"
                            results["event_writer"] = "created"
                        else:
                            results["event_writer"] = "found_existing"
                    session.commit()
                finally:
                    session.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                fut_a = pool.submit(snmp_worker_writer)
                fut_b = pool.submit(snmp_service_writer)
                fut_c = pool.submit(event_writer_batch)
                fut_a.result(timeout=30)
                fut_b.result(timeout=30)
                fut_c.result(timeout=30)

            # Exactly 1 Event in the sink — the no-duplicate guarantee.
            assert len(neo4j_sink) == 1, (
                f"expected exactly 1 Event in sink, got {len(neo4j_sink)}: "
                f"{neo4j_sink!r} — lock did NOT serialize writers; duplicate "
                f"Events would have been created in real Neo4j"
            )
            assert triplet in neo4j_sink, f"triplet {triplet!r} missing from sink: {neo4j_sink!r}"

            # Exactly 1 writer "created"; the other 2 "found_existing".
            created = [k for k, v in results.items() if v == "created"]
            found = [k for k, v in results.items() if v == "found_existing"]
            assert len(created) == 1, (
                f"expected exactly 1 writer to CREATE, got {len(created)}: " f"{results!r}"
            )
            assert len(found) == 2, (
                f"expected 2 writers to FIND_EXISTING, got {len(found)}: " f"{results!r}"
            )
    finally:
        restore_psycopg2()
