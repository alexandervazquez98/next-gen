"""Deterministic idempotency helpers for polling result storage."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from polling.contracts import PollingProtocol


def _utc_bucket(observed_at: datetime, bucket_seconds: int) -> str:
    if bucket_seconds < 1:
        raise ValueError("bucket_seconds must be >= 1")
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    observed_utc = observed_at.astimezone(timezone.utc)
    bucket_epoch = int(observed_utc.timestamp()) // bucket_seconds * bucket_seconds
    return datetime.fromtimestamp(bucket_epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_source(source: str) -> str:
    return str(source or "").strip().lower()


def generate_idempotency_key(
    *,
    ci_id: str,
    metric_id: str,
    protocol: PollingProtocol | str,
    source: str,
    observed_at: datetime,
    cycle_id: UUID | str,
    result_kind: str = "sample",
    bucket_seconds: int = 60,
) -> str:
    """Return a stable SHA-256 key for one scheduled polling result bucket."""
    protocol_value = protocol.value if isinstance(protocol, PollingProtocol) else str(protocol).upper()
    parts = [
        str(ci_id).strip(),
        str(metric_id).strip(),
        protocol_value,
        _normalize_source(source),
        _utc_bucket(observed_at, bucket_seconds),
        str(cycle_id),
        str(result_kind or "sample").strip().lower(),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
