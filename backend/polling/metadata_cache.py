"""TTL/version metadata cache primitives for scalable polling.

The cache stores safe metadata snapshots only. Secrets are stripped before data
can be attached to envelopes or used by workers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

_SECRET_MARKERS = ("password", "secret", "token", "community")


@dataclass(frozen=True, slots=True)
class MetadataCacheConfig:
    ttl_seconds: int = 300
    defer_on_version_mismatch: bool = True

    @classmethod
    def from_settings(cls, settings: Any) -> "MetadataCacheConfig":
        return cls(ttl_seconds=int(getattr(settings, "metadata_cache_ttl_seconds", cls.ttl_seconds)))


@dataclass(frozen=True, slots=True)
class CacheEntry:
    kind: str
    key: str
    value: dict[str, Any] | None
    version: str | None
    expires_at: datetime | None
    status: str = "hit"


@dataclass(frozen=True, slots=True)
class MetadataDecision:
    action: str
    reason: str | None = None
    value: dict[str, Any] | None = None
    cache_version: str | None = None
    task_version: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _safe_metadata(value)
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    return value


def _safe_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, raw_value in value.items():
        lowered = key.lower()
        if any(marker in lowered for marker in _SECRET_MARKERS):
            continue
        safe[key] = _safe_value(raw_value)
    return safe


class MetadataCache:
    """Small in-process TTL/version cache for scheduler/worker metadata."""

    def __init__(self, config: MetadataCacheConfig | None = None):
        self.config = config or MetadataCacheConfig()
        self._entries: dict[tuple[str, str], CacheEntry] = {}

    def put(
        self,
        kind: str,
        key: str,
        value: Mapping[str, Any],
        *,
        version: str | None = None,
        now: datetime | None = None,
        ttl_seconds: int | None = None,
    ) -> CacheEntry:
        now = now or _utc_now()
        ttl = self.config.ttl_seconds if ttl_seconds is None else ttl_seconds
        entry = CacheEntry(
            kind=kind,
            key=key,
            value=_safe_metadata(value),
            version=version,
            expires_at=now + timedelta(seconds=ttl),
            status="hit",
        )
        self._entries[(kind, key)] = entry
        return entry

    def get(self, kind: str, key: str, *, now: datetime | None = None) -> CacheEntry:
        now = now or _utc_now()
        entry = self._entries.get((kind, key))
        if entry is None:
            return CacheEntry(kind=kind, key=key, value=None, version=None, expires_at=None, status="miss")
        if entry.expires_at and entry.expires_at <= now:
            return CacheEntry(kind=kind, key=key, value=entry.value, version=entry.version, expires_at=entry.expires_at, status="expired")
        return entry

    def invalidate(self, kind: str, key: str) -> None:
        self._entries.pop((kind, key), None)

    def invalidate_kind(self, kind: str) -> None:
        for entry_key in [entry_key for entry_key in self._entries if entry_key[0] == kind]:
            self._entries.pop(entry_key, None)


def assess_task_metadata(task: Mapping[str, Any], cache: MetadataCache, *, now: datetime | None = None) -> MetadataDecision:
    """Decide whether cached metadata can be used for a task.

    Stale/missing metadata returns refresh/defer decisions rather than allowing
    silent polling with unverified definitions.
    """
    kind = str(task.get("metadata_kind") or "metric")
    key = str(task.get("metadata_key") or task.get("metric_id") or task.get("ci_id") or "")
    task_version = None if task.get("metadata_version") is None else str(task.get("metadata_version"))
    entry = cache.get(kind, key, now=now)

    if entry.status == "miss":
        return MetadataDecision(action="refresh", reason="metadata_missing", task_version=task_version)
    if entry.status == "expired":
        return MetadataDecision(action="refresh", reason="metadata_expired", value=entry.value, cache_version=entry.version, task_version=task_version)
    if task_version and entry.version and task_version != entry.version:
        return MetadataDecision(
            action="defer" if cache.config.defer_on_version_mismatch else "refresh",
            reason="metadata_version_mismatch",
            value=entry.value,
            cache_version=entry.version,
            task_version=task_version,
        )
    return MetadataDecision(action="use", value=entry.value, cache_version=entry.version, task_version=task_version)
