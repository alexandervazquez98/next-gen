"""Shared ICMP ping measurement helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

ICMP_AVAILABILITY_METRIC_ID = "icmp_availability"
ICMP_LATENCY_METRIC_ID = "icmp_latency_ms"
ICMP_JITTER_METRIC_ID = "icmp_jitter_ms"
ICMP_SIDECAR_METRIC_IDS = [ICMP_LATENCY_METRIC_ID, ICMP_JITTER_METRIC_ID]


@dataclass(frozen=True)
class PingMeasurement:
    available: bool
    latency_ms: float | None = None
    raw: str | None = None
    error: str | None = None

    @property
    def availability_value(self) -> float:
        return 1.0 if self.available else 0.0


_TIME_RE = re.compile(r"time\s*[=<]\s*(?P<value>\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)
_AVERAGE_RE = re.compile(r"Average\s*=\s*(?P<value>\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)
_RTT_RE = re.compile(r"(?:round-trip|rtt)[^=]*=\s*\d+(?:\.\d+)?/(?P<avg>\d+(?:\.\d+)?)/", re.IGNORECASE)


def parse_ping_latency_ms(output: str | None) -> float | None:
    """Parse a round-trip latency in milliseconds from common ping outputs."""
    if not output:
        return None
    text = str(output)
    for regex, group in ((_TIME_RE, "value"), (_AVERAGE_RE, "value"), (_RTT_RE, "avg")):
        match = regex.search(text)
        if match:
            value = float(match.group(group))
            if "time<" in match.group(0).lower():
                return 0.5 if value <= 1 else value / 2
            return value
    return None


def coerce_ping_measurement(raw: Any) -> PingMeasurement:
    """Normalize legacy float/bool or structured ping fetcher output."""
    if isinstance(raw, PingMeasurement):
        return raw
    if isinstance(raw, tuple) and len(raw) >= 2:
        available = bool(raw[0])
        latency = None if raw[1] is None else float(raw[1])
        return PingMeasurement(available=available, latency_ms=latency)
    numeric = float(raw or 0.0)
    return PingMeasurement(available=numeric > 0)


def build_icmp_sidecar_samples(
    node_id: str,
    measurement: PingMeasurement,
    *,
    previous_latency_ms: float | None = None,
    observed_at: Any | None = None,
) -> list[dict[str, Any]]:
    """Build latency and optional jitter sidecar samples for a successful ping."""
    if not measurement.available or measurement.latency_ms is None:
        return []
    samples: list[dict[str, Any]] = [{
        "node_id": node_id,
        "metric_id": ICMP_LATENCY_METRIC_ID,
        "value": float(measurement.latency_ms),
    }]
    if previous_latency_ms is not None:
        samples.append({
            "node_id": node_id,
            "metric_id": ICMP_JITTER_METRIC_ID,
            "value": abs(float(measurement.latency_ms) - float(previous_latency_ms)),
        })
    if observed_at is not None:
        for sample in samples:
            sample["time"] = observed_at
    return samples


def icmp_metadata(measurement: PingMeasurement) -> dict[str, Any]:
    metadata: dict[str, Any] = {"sidecar_metric_ids": list(ICMP_SIDECAR_METRIC_IDS)}
    if measurement.available and measurement.latency_ms is not None:
        metadata["latency_ms"] = float(measurement.latency_ms)
    return metadata


def is_icmp_telemetry_metric(metric_id: str, metadata: dict[str, Any] | None = None) -> bool:
    """Return true for ICMP sidecar telemetry metrics that are derived, not polled."""
    value = str(metric_id or "")
    return value in ICMP_SIDECAR_METRIC_IDS or bool(metadata and metadata.get("metric_kind") == "telemetry")


def is_icmp_availability_metric(metric_id: str, metadata: dict[str, Any] | None = None) -> bool:
    """Return true only for ICMP binary availability metrics.

    Sidecar telemetry IDs are denied first so bad upstream metadata cannot turn
    latency or jitter samples into availability events.
    """
    if is_icmp_telemetry_metric(metric_id, metadata):
        return False
    if metadata and metadata.get("metric_kind") == "availability":
        return True
    value = str(metric_id or "")
    return value == ICMP_AVAILABILITY_METRIC_ID or value == "PING-CHECK" or value.startswith("PING-")
