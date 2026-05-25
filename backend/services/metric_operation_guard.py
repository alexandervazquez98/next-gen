"""Process-local same-metric mutation guard."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import threading
from typing import Iterator


class MetricOperationInProgress(RuntimeError):
    """Raised when a same-metric create/delete mutation is already running."""

    def __init__(self, metric_id: str):
        self.metric_id = metric_id
        super().__init__(f"Metric operation already in progress: {metric_id}")


@dataclass
class _LockEntry:
    lock: threading.Lock
    users: int = 0


_locks_guard = threading.Lock()
_metric_locks: dict[str, _LockEntry] = {}


def _entry_for(metric_id: str) -> _LockEntry:
    with _locks_guard:
        entry = _metric_locks.get(metric_id)
        if entry is None:
            entry = _LockEntry(lock=threading.Lock())
            _metric_locks[metric_id] = entry
        entry.users += 1
        return entry


def _release_entry(metric_id: str, entry: _LockEntry) -> None:
    with _locks_guard:
        entry.users -= 1
        if entry.users == 0 and not entry.lock.locked() and _metric_locks.get(metric_id) is entry:
            _metric_locks.pop(metric_id, None)


def _lock_registry_size() -> int:
    """Return current registry size for tests and diagnostics."""
    with _locks_guard:
        return len(_metric_locks)


@contextmanager
def metric_operation_guard(metric_id: str) -> Iterator[None]:
    """Acquire a non-blocking process-local lock for one metric id."""
    entry = _entry_for(metric_id)
    acquired = entry.lock.acquire(blocking=False)
    if not acquired:
        _release_entry(metric_id, entry)
        raise MetricOperationInProgress(metric_id)

    try:
        yield
    finally:
        entry.lock.release()
        _release_entry(metric_id, entry)
