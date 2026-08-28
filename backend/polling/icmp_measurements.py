"""Shared ICMP ping measurement helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

ICMP_AVAILABILITY_METRIC_ID = "icmp_availability"
ICMP_LATENCY_METRIC_ID = "icmp_latency_ms"
ICMP_JITTER_METRIC_ID = "icmp_jitter_ms"
ICMP_PACKET_LOSS_METRIC_ID = "packet_loss_pct"
ICMP_SIDECAR_METRIC_IDS = [
    ICMP_LATENCY_METRIC_ID,
    ICMP_JITTER_METRIC_ID,
    ICMP_PACKET_LOSS_METRIC_ID,
]


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
_RTT_RE = re.compile(
    r"(?:round-trip|rtt)[^=]*=\s*\d+(?:\.\d+)?/(?P<avg>\d+(?:\.\d+)?)/", re.IGNORECASE
)


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
    """Build derived ICMP telemetry samples from a recorded ping result."""
    packet_loss = 0.0 if measurement.available else 100.0
    packet_loss_sample = {
        "node_id": node_id,
        "metric_id": ICMP_PACKET_LOSS_METRIC_ID,
        "value": packet_loss,
    }
    if not measurement.available or measurement.latency_ms is None:
        samples = [packet_loss_sample]
        if observed_at is not None:
            samples[0]["time"] = observed_at
        return samples
    samples: list[dict[str, Any]] = [
        {
            "node_id": node_id,
            "metric_id": ICMP_LATENCY_METRIC_ID,
            "value": float(measurement.latency_ms),
        }
    ]
    if previous_latency_ms is not None:
        samples.append(
            {
                "node_id": node_id,
                "metric_id": ICMP_JITTER_METRIC_ID,
                "value": abs(float(measurement.latency_ms) - float(previous_latency_ms)),
            }
        )
    samples.append(packet_loss_sample)
    if observed_at is not None:
        for sample in samples:
            sample["time"] = observed_at
    return samples


def icmp_metadata(measurement: PingMeasurement) -> dict[str, Any]:
    metadata: dict[str, Any] = {"sidecar_metric_ids": list(ICMP_SIDECAR_METRIC_IDS)}
    if measurement.available and measurement.latency_ms is not None:
        metadata["latency_ms"] = float(measurement.latency_ms)
    return metadata


def latency_threshold_metadata(*, warning_ms: float, critical_ms: float) -> dict[str, Any]:
    """Build MetricDef-compatible threshold metadata for ICMP latency."""
    return {
        "warning": float(warning_ms),
        "critical": float(critical_ms),
        "operator": ">=",
        "criticality": 3,
        "metric_kind": "telemetry",
        "name": "ICMP Latency",
    }


def jitter_threshold_metadata(*, warning_ms: float, critical_ms: float) -> dict[str, Any]:
    """Build MetricDef-compatible threshold metadata for ICMP jitter."""
    return {
        "warning": float(warning_ms),
        "critical": float(critical_ms),
        "operator": ">=",
        "criticality": 2,
        "metric_kind": "telemetry",
        "name": "ICMP Jitter",
    }


def packet_loss_threshold_metadata(*, warning_pct: float, critical_pct: float) -> dict[str, Any]:
    """Build MetricDef-compatible threshold metadata for ICMP packet loss."""
    return {
        "warning": float(warning_pct),
        "critical": float(critical_pct),
        "operator": ">=",
        "criticality": 3,
        "metric_kind": "telemetry",
        "name": "ICMP Packet Loss",
    }


def evaluate_latency_status(
    latency_ms: float | None, *, warning_ms: float, critical_ms: float
) -> str:
    """Evaluate ICMP latency against warning/critical thresholds.

    Missing data fails closed to CRITICAL — operators must investigate why a
    CI stopped reporting latency instead of seeing a silent OK that masks a
    degraded sidecar.
    """
    if latency_ms is None:
        return "CRITICAL"
    latency = float(latency_ms)
    if latency >= float(critical_ms):
        return "CRITICAL"
    if latency >= float(warning_ms):
        return "WARNING"
    return "OK"


def evaluate_jitter_status(
    jitter_ms: float | None, *, warning_ms: float, critical_ms: float
) -> str:
    """Evaluate ICMP jitter against warning/critical thresholds.

    Missing data fails closed to CRITICAL — mirrors ``evaluate_latency_status``
    so every sidecar metric treats absent samples the same way.
    """
    if jitter_ms is None:
        return "CRITICAL"
    jitter = float(jitter_ms)
    if jitter >= float(critical_ms):
        return "CRITICAL"
    if jitter >= float(warning_ms):
        return "WARNING"
    return "OK"


def evaluate_packet_loss_status(
    packet_loss_pct: float | None, *, warning_pct: float, critical_pct: float
) -> str:
    """Evaluate ICMP packet loss against warning/critical thresholds.

    Missing data fails closed to CRITICAL — a CI with no packet-loss sample is
    as actionable as a CI with 100% loss.
    """
    if packet_loss_pct is None:
        return "CRITICAL"
    pct = float(packet_loss_pct)
    if pct >= float(critical_pct):
        return "CRITICAL"
    if pct >= float(warning_pct):
        return "WARNING"
    return "OK"


def is_icmp_telemetry_metric(metric_id: str, metadata: dict[str, Any] | None = None) -> bool:
    """Return true for ICMP sidecar telemetry metrics that are derived, not polled."""
    value = str(metric_id or "")
    return value in ICMP_SIDECAR_METRIC_IDS or bool(
        metadata and metadata.get("metric_kind") == "telemetry"
    )


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
    return (
        value == ICMP_AVAILABILITY_METRIC_ID or value == "PING-CHECK" or value.startswith("PING-")
    )
