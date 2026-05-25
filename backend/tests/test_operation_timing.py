import logging

import pytest


def test_timed_operation_logs_success_with_context(caplog):
    from services.operation_timing import timed_operation

    logger = logging.getLogger("tests.operation_timing.success")

    with caplog.at_level(logging.INFO, logger=logger.name):
        with timed_operation(logger, "metric.create", metric_id="cpu-load"):
            pass

    record = next(record for record in caplog.records if record.name == logger.name)
    assert record.operation == "metric.create"
    assert record.outcome == "success"
    assert record.metric_id == "cpu-load"
    assert isinstance(record.duration_ms, float)
    assert record.duration_ms >= 0


def test_timed_operation_logs_failure_and_reraises(caplog):
    from services.operation_timing import timed_operation

    logger = logging.getLogger("tests.operation_timing.failure")
    original = RuntimeError("boom")

    with caplog.at_level(logging.WARNING, logger=logger.name):
        with pytest.raises(RuntimeError) as exc_info:
            with timed_operation(logger, "metric.delete", metric_id="cpu-load"):
                raise original

    assert exc_info.value is original
    record = next(record for record in caplog.records if record.name == logger.name)
    assert record.operation == "metric.delete"
    assert record.outcome == "failure"
    assert record.metric_id == "cpu-load"
    assert record.exc_info is not None
    assert isinstance(record.duration_ms, float)
    assert record.duration_ms >= 0
