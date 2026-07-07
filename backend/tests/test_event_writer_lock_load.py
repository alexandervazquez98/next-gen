import json
import threading
from collections import deque

import pytest

from scripts import event_writer_lock_load as load


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class RecordingSession(FakeSession):
    def __init__(self):
        super().__init__()
        self.executed = []

    def execute(self, statement, params=None):
        self.executed.append((str(statement), params))


def test_duration_stats_include_required_percentiles():
    stats = load.duration_stats([1.0, 2.0, 3.0, 4.0])

    assert stats == {
        "count": 4,
        "p50_ms": 2.5,
        "p95_ms": 3.85,
        "p99_ms": 3.97,
        "max_ms": 4.0,
    }


def test_workload_report_records_same_triplet_lock_and_write_stats():
    sessions = []
    clock_values = deque([0.00, 0.01, 0.01, 0.03, 0.10, 0.12, 0.12, 0.15])
    acquired = []

    def session_factory():
        session = FakeSession()
        sessions.append(session)
        return session

    def acquire_lock(session, ci_id, metric_id, event_type, *, writer_context):
        acquired.append((ci_id, metric_id, event_type, writer_context, session.closed))

    report = load.run_workload(
        name="same_triplet",
        mode="same-triplet",
        writers=2,
        iterations=1,
        session_factory=session_factory,
        acquire_lock=acquire_lock,
        protected_write=lambda session, triplet: None,
        monotonic=lambda: clock_values.popleft(),
        use_threads=False,
    )

    assert report["name"] == "same_triplet"
    assert report["mode"] == "same-triplet"
    assert report["writers"] == 2
    assert report["iterations_per_writer"] == 1
    assert report["total_writes"] == 2
    assert report["lock_wait"]["count"] == 2
    assert report["event_write"]["count"] == 2
    assert report["lock_wait"]["max_ms"] == 20.0
    assert report["event_write"]["max_ms"] == 30.0
    assert {item[:3] for item in acquired} == {("ci-contention", "metric-contention", "THRESHOLD_BREACH")}
    assert all(session.commits == 1 and session.closed for session in sessions)


def test_disjoint_triplet_workload_gives_each_writer_a_distinct_triplet():
    acquired = []

    def acquire_lock(session, ci_id, metric_id, event_type, *, writer_context):
        acquired.append((ci_id, metric_id, event_type))

    load.run_workload(
        name="disjoint_triplets",
        mode="disjoint-triplets",
        writers=3,
        iterations=1,
        session_factory=FakeSession,
        acquire_lock=acquire_lock,
        protected_write=lambda session, triplet: None,
        monotonic=lambda: 0.0,
        use_threads=False,
    )

    assert len(set(acquired)) == 3


def test_threaded_workload_runs_each_writer_iterations_serially():
    active_writers = set()
    overlap_detected = []
    release_slow_writer = threading.Event()

    def acquire_lock(session, ci_id, metric_id, event_type, *, writer_context):
        writer_index = int(ci_id.removeprefix("ci-"))
        if writer_index in active_writers:
            overlap_detected.append(writer_index)
            release_slow_writer.set()
        active_writers.add(writer_index)

    def protected_write(session, triplet):
        writer_index = int(triplet[0].removeprefix("ci-"))
        if writer_index == 0:
            release_slow_writer.wait(timeout=0.2)
        active_writers.remove(writer_index)

    load.run_workload(
        name="disjoint_triplets",
        mode="disjoint-triplets",
        writers=2,
        iterations=2,
        session_factory=FakeSession,
        acquire_lock=acquire_lock,
        protected_write=protected_write,
        monotonic=lambda: 0.0,
        use_threads=True,
    )

    assert overlap_detected == []


def test_threaded_workload_uses_start_barrier(monkeypatch):
    barrier_waits = []

    class SpyBarrier:
        def __init__(self, parties):
            self.parties = parties

        def wait(self):
            barrier_waits.append(self.parties)

    monkeypatch.setattr(load.threading, "Barrier", SpyBarrier)

    load.run_workload(
        name="same_triplet",
        mode="same-triplet",
        writers=2,
        iterations=1,
        session_factory=FakeSession,
        acquire_lock=lambda *args, **kwargs: None,
        protected_write=lambda session, triplet: None,
        monotonic=lambda: 0.0,
        use_threads=True,
    )

    assert barrier_waits == [2, 2]


def test_database_timeouts_are_configured_before_lock_acquisition():
    sessions = []
    lock_seen_after_timeouts = []

    def session_factory():
        session = RecordingSession()
        sessions.append(session)
        return session

    def acquire_lock(session_arg, ci_id, metric_id, event_type, *, writer_context):
        lock_seen_after_timeouts.append(len(session_arg.executed) == 2)

    load.run_workload(
        name="same_triplet",
        mode="same-triplet",
        writers=2,
        iterations=1,
        session_factory=session_factory,
        acquire_lock=acquire_lock,
        protected_write=lambda session, triplet: None,
        monotonic=lambda: 0.0,
        use_threads=False,
        config=load.WorkloadConfig(lock_timeout_ms=123, statement_timeout_ms=456),
    )

    assert lock_seen_after_timeouts == [True, True]
    assert [session.executed for session in sessions] == [
        [
            ("SELECT set_config('lock_timeout', :value, true)", {"value": "123ms"}),
            ("SELECT set_config('statement_timeout', :value, true)", {"value": "456ms"}),
        ],
        [
            ("SELECT set_config('lock_timeout', :value, true)", {"value": "123ms"}),
            ("SELECT set_config('statement_timeout', :value, true)", {"value": "456ms"}),
        ],
    ]


@pytest.mark.parametrize(
    "args, message",
    [
        (["--lock-timeout-ms", "0"], "--lock-timeout-ms must be >= 1"),
        (["--statement-timeout-ms", "0"], "--statement-timeout-ms must be >= 1"),
        (["--workload-timeout-s", "0"], "--workload-timeout-s must be > 0"),
    ],
)
def test_main_rejects_invalid_timeout_boundaries(args, message):
    with pytest.raises(SystemExit, match=message):
        load.main(["--writers", "2", "--iterations", "1", *args])


@pytest.mark.parametrize(
    "config_kwargs, message",
    [
        ({"lock_timeout_ms": 0}, "lock_timeout_ms must be >= 1"),
        ({"statement_timeout_ms": 0}, "statement_timeout_ms must be >= 1"),
        ({"workload_timeout_s": 0}, "workload_timeout_s must be > 0"),
    ],
)
def test_workload_config_rejects_invalid_timeout_boundaries(config_kwargs, message):
    with pytest.raises(ValueError, match=message):
        load.WorkloadConfig(**config_kwargs)


def test_build_report_resolves_default_lock_acquirer_at_call_time(monkeypatch):
    acquired = []

    def acquire_lock(session, ci_id, metric_id, event_type, *, writer_context):
        acquired.append((ci_id, metric_id, event_type, writer_context))

    monkeypatch.setattr(load, "acquire_event_triplet_lock", acquire_lock)
    monkeypatch.setattr(load.time, "sleep", lambda seconds: None)

    report = load.build_report(
        writers=2,
        iterations=1,
        event_write_ms=0,
        session_factory=FakeSession,
    )

    assert report["workloads"]["same_triplet"]["total_writes"] == 2
    assert report["workloads"]["disjoint_triplets"]["total_writes"] == 2
    assert len(acquired) == 4


def test_threaded_workload_times_out_when_a_worker_blocks():
    release_worker = threading.Event()

    def protected_write(session, triplet):
        if triplet[0] == "ci-0":
            release_worker.wait(timeout=2)

    try:
        try:
            load.run_workload(
                name="disjoint_triplets",
                mode="disjoint-triplets",
                writers=2,
                iterations=1,
                session_factory=FakeSession,
                acquire_lock=lambda *args, **kwargs: None,
                protected_write=protected_write,
                monotonic=lambda: 0.0,
                use_threads=True,
                config=load.WorkloadConfig(workload_timeout_s=0.05),
            )
        except TimeoutError as exc:
            assert "timed out after 0.05s" in str(exc)
        else:
            raise AssertionError("run_workload should time out when a worker blocks")
    finally:
        release_worker.set()


def test_main_returns_nonzero_when_workload_times_out(monkeypatch, capsys):
    def raise_timeout(**kwargs):
        raise TimeoutError("simulated workload timeout")

    monkeypatch.setattr(load, "run_workload", raise_timeout)
    monkeypatch.setattr(load, "_load_session_factory", lambda: FakeSession)

    assert load.main(["--writers", "2", "--iterations", "1", "--event-write-ms", "0"]) == 1
    assert "event_writer_lock_load timed out: simulated workload timeout" in capsys.readouterr().err


def test_main_emits_machine_readable_comparison_json(monkeypatch, capsys):
    monkeypatch.setattr(load, "_load_session_factory", lambda: FakeSession)
    monkeypatch.setattr(load, "acquire_event_triplet_lock", lambda *args, **kwargs: None)
    monkeypatch.setattr(load.time, "sleep", lambda seconds: None)

    assert load.main(["--writers", "2", "--iterations", "1", "--event-write-ms", "0"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["script"] == "event_writer_lock_load"
    assert set(payload["workloads"]) == {"same_triplet", "disjoint_triplets"}
    for workload in payload["workloads"].values():
        assert workload["lock_wait"]["count"] == 2
        assert workload["event_write"]["count"] == 2
        assert set(workload["lock_wait"]) >= {"count", "p50_ms", "p95_ms", "p99_ms", "max_ms"}
