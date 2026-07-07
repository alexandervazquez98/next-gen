"""Controlled advisory-lock load harness for event writer contention.

The harness uses PostgreSQL transaction-scoped advisory locks and a configurable
protected write delay to compare same-triplet contention against disjoint triplets.
It intentionally does not enforce timing thresholds; non-zero exits are reserved
for argument/configuration/runtime errors.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import dataclass
from queue import Empty, Queue
from pathlib import Path
from typing import Callable, Iterable, Literal, NamedTuple

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from postgres_db import SessionLocal
from services.event_lock import acquire_event_triplet_lock

Triplet = tuple[str, str, str]
WorkloadMode = Literal["same-triplet", "disjoint-triplets"]
DEFAULT_LOCK_TIMEOUT_MS = 5000
DEFAULT_STATEMENT_TIMEOUT_MS = 30000
DEFAULT_WORKLOAD_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class WorkloadConfig:
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS
    workload_timeout_s: float = DEFAULT_WORKLOAD_TIMEOUT_S


class WriteSample(NamedTuple):
    lock_wait_ms: float
    event_write_ms: float


def duration_stats(values: Iterable[float]) -> dict[str, float | int]:
    """Return stable millisecond summary stats for a sample set."""
    ordered = sorted(round(float(value), 3) for value in values)
    if not ordered:
        return {
            "count": 0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "max_ms": 0.0,
        }

    def percentile(percent: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        rank = (len(ordered) - 1) * percent
        lower = int(rank)
        upper = min(lower + 1, len(ordered) - 1)
        fraction = rank - lower
        return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 3)

    return {
        "count": len(ordered),
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
        "max_ms": ordered[-1],
    }


def triplet_for(mode: WorkloadMode, writer_index: int, iteration: int) -> Triplet:
    """Return the target event triplet for a workload sample."""
    if mode == "same-triplet":
        return ("ci-contention", "metric-contention", "THRESHOLD_BREACH")
    if mode == "disjoint-triplets":
        return (f"ci-{writer_index}", f"metric-{writer_index}", "THRESHOLD_BREACH")
    raise ValueError(f"Unsupported workload mode: {mode}")


def _default_protected_write(delay_seconds: float) -> Callable[[object, Triplet], None]:
    def write(_session: object, _triplet: Triplet) -> None:
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    return write


def _configure_session_timeouts(
    session: object,
    *,
    lock_timeout_ms: int,
    statement_timeout_ms: int,
) -> None:
    """Bound PostgreSQL lock/statement waits for the current transaction."""
    execute = getattr(session, "execute", None)
    if not callable(execute):
        return

    execute(text(f"SET LOCAL lock_timeout = '{int(lock_timeout_ms)}ms'"))
    execute(text(f"SET LOCAL statement_timeout = '{int(statement_timeout_ms)}ms'"))


def _run_one_write(
    *,
    writer_index: int,
    iteration: int,
    mode: WorkloadMode,
    session_factory: Callable[[], object],
    acquire_lock: Callable[..., None],
    protected_write: Callable[[object, Triplet], None],
    monotonic: Callable[[], float],
    config: WorkloadConfig,
) -> WriteSample:
    triplet = triplet_for(mode, writer_index, iteration)
    session = session_factory()
    try:
        _configure_session_timeouts(
            session,
            lock_timeout_ms=config.lock_timeout_ms,
            statement_timeout_ms=config.statement_timeout_ms,
        )
        lock_start = monotonic()
        acquire_lock(
            session,
            triplet[0],
            triplet[1],
            triplet[2],
            writer_context="event_writer_lock_load",
        )
        lock_wait_ms = (monotonic() - lock_start) * 1000

        write_start = monotonic()
        protected_write(session, triplet)
        event_write_ms = (monotonic() - write_start) * 1000

        commit = getattr(session, "commit", None)
        if callable(commit):
            commit()
        return WriteSample(lock_wait_ms=lock_wait_ms, event_write_ms=event_write_ms)
    except Exception:
        rollback = getattr(session, "rollback", None)
        if callable(rollback):
            rollback()
        raise
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()


def _run_writer(
    *,
    writer_index: int,
    iterations: int,
    mode: WorkloadMode,
    session_factory: Callable[[], object],
    acquire_lock: Callable[..., None],
    protected_write: Callable[[object, Triplet], None],
    monotonic: Callable[[], float],
    config: WorkloadConfig,
) -> list[WriteSample]:
    return [
        _run_one_write(
            writer_index=writer_index,
            iteration=iteration,
            mode=mode,
            session_factory=session_factory,
            acquire_lock=acquire_lock,
            protected_write=protected_write,
            monotonic=monotonic,
            config=config,
        )
        for iteration in range(iterations)
    ]


def run_workload(
    *,
    name: str,
    mode: WorkloadMode,
    writers: int,
    iterations: int,
    session_factory: Callable[[], object],
    acquire_lock: Callable[..., None] | None = None,
    protected_write: Callable[[object, Triplet], None] | None = None,
    monotonic: Callable[[], float] = time.perf_counter,
    use_threads: bool = True,
    config: WorkloadConfig | None = None,
) -> dict[str, object]:
    """Run one workload and return JSON-ready lock/write latency evidence."""
    if writers < 2:
        raise ValueError("writers must be >= 2")
    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    workload_config = config or WorkloadConfig()
    if workload_config.workload_timeout_s <= 0:
        raise ValueError("workload_timeout_s must be > 0")

    lock_acquirer = acquire_lock or acquire_event_triplet_lock
    write = protected_write or _default_protected_write(0.0)
    samples: list[WriteSample] = []

    if use_threads:
        result_queue: Queue[tuple[str, list[WriteSample] | BaseException]] = Queue()

        start_barrier = threading.Barrier(writers)

        def run_writer_thread(writer_index: int) -> None:
            try:
                start_barrier.wait()
                result_queue.put(
                    (
                        "samples",
                        _run_writer(
                            writer_index=writer_index,
                            iterations=iterations,
                            mode=mode,
                            session_factory=session_factory,
                            acquire_lock=lock_acquirer,
                            protected_write=write,
                            monotonic=monotonic,
                            config=workload_config,
                        ),
                    )
                )
            except BaseException as exc:  # pragma: no cover - re-raised in parent thread
                result_queue.put(("error", exc))

        threads = [
            threading.Thread(
                target=run_writer_thread,
                args=(writer_index,),
                name=f"event-writer-lock-load-{name}-{writer_index}",
                daemon=True,
            )
            for writer_index in range(writers)
        ]
        for thread in threads:
            thread.start()

        deadline = time.monotonic() + workload_config.workload_timeout_s
        completed = 0
        while completed < writers:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"workload '{name}' timed out after {workload_config.workload_timeout_s:g}s"
                )
            try:
                result_type, result = result_queue.get(timeout=remaining)
            except Empty as exc:
                raise TimeoutError(
                    f"workload '{name}' timed out after {workload_config.workload_timeout_s:g}s"
                ) from exc

            completed += 1
            if result_type == "error":
                raise result  # type: ignore[misc]
            samples.extend(result)  # type: ignore[arg-type]

        for thread in threads:
            thread.join(timeout=0)
    else:
        for writer_index in range(writers):
            samples.extend(
                _run_writer(
                    writer_index=writer_index,
                    iterations=iterations,
                    mode=mode,
                    session_factory=session_factory,
                    acquire_lock=lock_acquirer,
                    protected_write=write,
                    monotonic=monotonic,
                    config=workload_config,
                )
            )

    return {
        "name": name,
        "mode": mode,
        "writers": writers,
        "iterations_per_writer": iterations,
        "total_writes": len(samples),
        "lock_wait": duration_stats(sample.lock_wait_ms for sample in samples),
        "event_write": duration_stats(sample.event_write_ms for sample in samples),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare event writer advisory-lock contention workloads as JSON"
    )
    parser.add_argument("--writers", type=int, default=2, help="Concurrent writers; must be >= 2")
    parser.add_argument(
        "--iterations", type=int, default=20, help="Writes per writer for each workload"
    )
    parser.add_argument(
        "--event-write-ms",
        type=float,
        default=25.0,
        help="Simulated protected Event write duration while the advisory lock is held",
    )
    parser.add_argument(
        "--lock-timeout-ms",
        type=int,
        default=DEFAULT_LOCK_TIMEOUT_MS,
        help="PostgreSQL lock_timeout applied before each advisory lock acquisition",
    )
    parser.add_argument(
        "--statement-timeout-ms",
        type=int,
        default=DEFAULT_STATEMENT_TIMEOUT_MS,
        help="PostgreSQL statement_timeout applied before each advisory lock acquisition",
    )
    parser.add_argument(
        "--workload-timeout-s",
        type=float,
        default=DEFAULT_WORKLOAD_TIMEOUT_S,
        help=(
                "Maximum seconds the parent waits for each threaded workload; "
                "timed-out daemon workers may continue until process exit "
                f"(default: {DEFAULT_WORKLOAD_TIMEOUT_S:g})"
            ),
    )
    return parser


def _load_session_factory():
    return SessionLocal


def build_report(
    *,
    writers: int,
    iterations: int,
    event_write_ms: float,
    session_factory: Callable[[], object],
    config: WorkloadConfig | None = None,
) -> dict[str, object]:
    workload_config = config or WorkloadConfig()
    protected_write = _default_protected_write(event_write_ms / 1000)
    workloads = {
        "same_triplet": run_workload(
            name="same_triplet",
            mode="same-triplet",
            writers=writers,
            iterations=iterations,
            session_factory=session_factory,
            protected_write=protected_write,
            config=workload_config,
        ),
        "disjoint_triplets": run_workload(
            name="disjoint_triplets",
            mode="disjoint-triplets",
            writers=writers,
            iterations=iterations,
            session_factory=session_factory,
            protected_write=protected_write,
            config=workload_config,
        ),
    }
    return {
        "script": "event_writer_lock_load",
        "threshold_policy": "no timing thresholds; fail only on execution/correctness errors",
        "config": {
            "writers": writers,
            "iterations_per_writer": iterations,
            "event_write_ms": event_write_ms,
            "lock_timeout_ms": workload_config.lock_timeout_ms,
            "statement_timeout_ms": workload_config.statement_timeout_ms,
            "workload_timeout_s": workload_config.workload_timeout_s,
        },
        "workloads": workloads,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.writers < 2:
        raise SystemExit("--writers must be >= 2")
    if args.iterations < 1:
        raise SystemExit("--iterations must be >= 1")
    if args.event_write_ms < 0:
        raise SystemExit("--event-write-ms must be >= 0")
    if args.lock_timeout_ms < 1:
        raise SystemExit("--lock-timeout-ms must be >= 1")
    if args.statement_timeout_ms < 1:
        raise SystemExit("--statement-timeout-ms must be >= 1")
    if args.workload_timeout_s <= 0:
        raise SystemExit("--workload-timeout-s must be > 0")

    try:
        report = build_report(
            writers=args.writers,
            iterations=args.iterations,
            event_write_ms=args.event_write_ms,
            session_factory=_load_session_factory(),
            config=WorkloadConfig(
                lock_timeout_ms=args.lock_timeout_ms,
                statement_timeout_ms=args.statement_timeout_ms,
                workload_timeout_s=args.workload_timeout_s,
            ),
        )
    except TimeoutError as exc:
        print(f"event_writer_lock_load timed out: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"event_writer_lock_load failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
