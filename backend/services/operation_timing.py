"""Small synchronous timing helper for service hot paths."""

from __future__ import annotations

from contextlib import contextmanager
import logging
import time
from typing import Any, Iterator


@contextmanager
def timed_operation(
    logger: logging.Logger,
    operation: str,
    **context: Any,
) -> Iterator[None]:
    """Log elapsed time and outcome for a synchronous operation.

    The helper deliberately does not alter return values or exception flow.
    Context values are attached to the LogRecord via ``extra`` so tests and log
    formatters can consume structured fields without parsing message text.
    """
    started_at = time.perf_counter()
    try:
        yield
    except Exception:
        duration_ms = (time.perf_counter() - started_at) * 1000
        logger.warning(
            "%s failed in %.2f ms",
            operation,
            duration_ms,
            extra={
                "operation": operation,
                "duration_ms": duration_ms,
                "outcome": "failure",
                **context,
            },
            exc_info=True,
        )
        raise
    else:
        duration_ms = (time.perf_counter() - started_at) * 1000
        logger.info(
            "%s completed in %.2f ms",
            operation,
            duration_ms,
            extra={
                "operation": operation,
                "duration_ms": duration_ms,
                "outcome": "success",
                **context,
            },
        )
