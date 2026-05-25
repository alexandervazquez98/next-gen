import threading

import pytest


def test_same_metric_second_acquire_raises_and_release_allows_retry():
    from services.metric_operation_guard import (
        MetricOperationInProgress,
        _lock_registry_size,
        metric_operation_guard,
    )

    with metric_operation_guard("cpu-load"):
        with pytest.raises(MetricOperationInProgress) as exc_info:
            with metric_operation_guard("cpu-load"):
                pass

    assert exc_info.value.metric_id == "cpu-load"

    with metric_operation_guard("cpu-load"):
        pass

    assert _lock_registry_size() == 0


def test_lock_releases_after_exception():
    from services.metric_operation_guard import _lock_registry_size, metric_operation_guard

    with pytest.raises(RuntimeError):
        with metric_operation_guard("cpu-load"):
            raise RuntimeError("boom")

    with metric_operation_guard("cpu-load"):
        pass

    assert _lock_registry_size() == 0


def test_different_metric_ids_can_run_concurrently():
    from services.metric_operation_guard import _lock_registry_size, metric_operation_guard

    entered_other_metric = threading.Event()
    release = threading.Event()

    def hold_other_metric():
        with metric_operation_guard("memory-used"):
            entered_other_metric.set()
            release.wait(timeout=2)

    with metric_operation_guard("cpu-load"):
        thread = threading.Thread(target=hold_other_metric)
        thread.start()
        try:
            assert entered_other_metric.wait(timeout=1)
        finally:
            release.set()
            thread.join(timeout=1)

    assert not thread.is_alive()
    assert _lock_registry_size() == 0
