"""Reconstructable in-process safety counters for leased polling workers.

PR4 keeps safety decisions deterministic and dependency-free. A later slice may
replace these counters with PostgreSQL advisory locks or another shared backend
when multiple worker processes need cross-instance enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class SafetyLimitConfig:
    per_ci: int | None = 1
    per_ip: int | None = 1
    per_site: int | None = None
    per_subnet: int | None = None
    per_credential: int | None = None
    per_protocol: int | None = 8
    per_endpoint: int | None = None
    per_source: int | None = None


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    allowed: bool
    reason: str | None = None
    error_code: str | None = None
    dimension: str | None = None
    key: str | None = None
    current: int = 0
    limit: int | None = None


_DIMENSIONS = (
    ("ci_id", "per_ci"),
    ("ip_address", "per_ip"),
    ("site_id", "per_site"),
    ("subnet", "per_subnet"),
    ("credential_ref", "per_credential"),
    ("protocol", "per_protocol"),
    ("endpoint", "per_endpoint"),
    ("source", "per_source"),
)


def _get(task: Mapping[str, Any] | Any, key: str) -> Any:
    if isinstance(task, Mapping):
        return task.get(key)
    return getattr(task, key, None)


def safety_keys(task: Mapping[str, Any] | Any) -> dict[str, str]:
    """Return configured target dimensions present on a task."""
    keys: dict[str, str] = {}
    for dimension, _ in _DIMENSIONS:
        value = _get(task, dimension)
        if value is not None and value != "":
            keys[dimension] = str(value)
    return keys


class ActiveSafetyLimiter:
    """Small reconstructable counter limiter for one worker process."""

    def __init__(self, config: SafetyLimitConfig | None = None):
        self.config = config or SafetyLimitConfig()
        self._active: dict[tuple[str, str], int] = {}

    def _limit_for(self, config_name: str) -> int | None:
        limit = getattr(self.config, config_name)
        return limit if limit and limit > 0 else None

    def acquire(self, task: Mapping[str, Any] | Any) -> SafetyDecision:
        keys = safety_keys(task)
        for dimension, config_name in _DIMENSIONS:
            limit = self._limit_for(config_name)
            key = keys.get(dimension)
            if limit is None or key is None:
                continue
            current = self._active.get((dimension, key), 0)
            if current >= limit:
                return SafetyDecision(
                    allowed=False,
                    reason=f"Safety limit reached for {dimension}={key}",
                    error_code="safety_limit",
                    dimension=dimension,
                    key=key,
                    current=current,
                    limit=limit,
                )
        for dimension, key in keys.items():
            self._active[(dimension, key)] = self._active.get((dimension, key), 0) + 1
        return SafetyDecision(allowed=True)

    def release(self, task: Mapping[str, Any] | Any) -> None:
        for dimension, key in safety_keys(task).items():
            active_key = (dimension, key)
            current = self._active.get(active_key, 0)
            if current <= 1:
                self._active.pop(active_key, None)
            else:
                self._active[active_key] = current - 1
