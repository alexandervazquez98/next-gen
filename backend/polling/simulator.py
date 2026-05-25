"""Synthetic load simulator for the scalable polling pipeline.

The simulator is non-production by default: it models task mix, latency,
failures, writer lag, and backpressure without polling devices or writing DBs.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

from polling.contracts import PollingProtocol

DEFAULT_MIX = "ICMP:0.15,SNMP:0.55,CLI:0.15,REST:0.10,MQTT_STUB:0.05"
BASE_LATENCY_MS = {
    "ICMP": 20,
    "SNMP": 350,
    "CLI": 800,
    "REST": 120,
    "MQTT_STUB": 5,
}


def parse_protocol_mix(value: str | Mapping[str, float] | None = None) -> dict[str, float]:
    """Parse and normalize protocol mix strings like `SNMP:0.5,ICMP:0.5`."""
    if value is None:
        value = DEFAULT_MIX
    raw_items = value.items() if isinstance(value, Mapping) else (
        part.split(":", 1) for part in str(value).split(",") if part.strip()
    )
    mix: dict[str, float] = {}
    for proto_raw, weight_raw in raw_items:
        proto = str(proto_raw).strip().upper()
        if proto == "MQTT":
            raise ValueError("Production MQTT is out of scope; use MQTT_STUB for simulator sizing")
        try:
            protocol = PollingProtocol(proto)
        except ValueError as exc:
            raise ValueError(f"Unsupported simulator protocol: {proto}") from exc
        weight = float(weight_raw)
        if weight < 0:
            raise ValueError("Protocol weights must be non-negative")
        mix[protocol.value] = mix.get(protocol.value, 0.0) + weight
    total = sum(mix.values())
    if total <= 0:
        raise ValueError("Protocol mix must have positive total weight")
    return {protocol: weight / total for protocol, weight in mix.items()}


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    ci_count: int = 8000
    metrics_per_ci: int = 35
    protocol_mix: str | Mapping[str, float] = DEFAULT_MIX
    target_cycle_seconds: int = 900
    duration_seconds: int | None = None
    worker_count: int = 8
    db_writer_count: int = 1
    task_batch_size: int = 100
    result_batch_size: int = 500
    sink: str = "synthetic"
    failure_rate: float = 0.02
    timeout_rate: float = 0.01
    inject_backpressure: bool = False
    max_task_queue_depth: int = 100_000
    db_write_latency_ms: int = 50
    latency_ms_by_protocol: Mapping[str, int] = field(default_factory=lambda: BASE_LATENCY_MS)

    @property
    def total_tasks(self) -> int:
        return self.ci_count * self.metrics_per_ci

    @property
    def normalized_mix(self) -> dict[str, float]:
        return parse_protocol_mix(self.protocol_mix)

    @classmethod
    def from_settings(cls, settings: Any) -> "SimulationConfig":
        return cls(
            ci_count=int(getattr(settings, "benchmark_ci_count", 8000)),
            metrics_per_ci=int(getattr(settings, "benchmark_metrics_per_ci", 35)),
            protocol_mix=getattr(settings, "benchmark_protocol_mix", DEFAULT_MIX),
            target_cycle_seconds=int(getattr(settings, "target_cycle_seconds", 900)),
            duration_seconds=(int(getattr(settings, "benchmark_duration_seconds", 0)) or int(os.getenv("POLLING_BENCHMARK_DURATION_SECONDS", "0")) or None),
            worker_count=int(getattr(settings, "worker_count", 8)),
            db_writer_count=int(getattr(settings, "db_writer_count", 1)),
            task_batch_size=int(getattr(settings, "task_batch_size", 100)),
            result_batch_size=int(getattr(settings, "result_batch_size", 500)),
            sink=str(getattr(settings, "benchmark_sink", "synthetic")),
            max_task_queue_depth=int(getattr(settings, "backpressure_max_task_queue_depth", 100_000)),
        )


@dataclass(frozen=True, slots=True)
class SimulationReport:
    total_tasks: int
    protocol_counts: dict[str, int]
    sink: str
    cycle_duration_estimate_seconds: float
    queue_depth: int
    queue_oldest_age_seconds: int
    worker_throughput_per_second: float
    writer_rows_per_second: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    writer_lag_seconds: float
    db_write_latency_ms: int
    deferred_count: int
    dead_letter_count: int
    failed_count: int
    timeout_count: int
    bottlenecks: list[str]
    resource_hints: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


def _protocol_counts(config: SimulationConfig) -> dict[str, int]:
    total = config.total_tasks
    mix = config.normalized_mix
    counts = {protocol: int(total * weight) for protocol, weight in mix.items()}
    remainder = total - sum(counts.values())
    for protocol in sorted(mix, key=lambda item: mix[item], reverse=True)[:remainder]:
        counts[protocol] += 1
    return counts


def generate_metric_records(config: SimulationConfig) -> Iterable[dict[str, Any]]:
    """Yield deterministic synthetic CI/metric records for scheduler-style tests."""
    counts = _protocol_counts(config)
    emitted = 0
    for protocol, count in counts.items():
        for index in range(count):
            ci_index = emitted // max(config.metrics_per_ci, 1)
            metric_index = emitted % max(config.metrics_per_ci, 1)
            ip = f"10.{ci_index // 65536}.{(ci_index // 256) % 256}.{ci_index % 256}"
            yield {
                "node_id": f"CI-{ci_index:05d}",
                "metric_id": "PING-CHECK" if protocol == "ICMP" else f"{protocol.lower()}-{metric_index:02d}",
                "protocol": protocol,
                "protocol_enum": PollingProtocol(protocol),
                "ip": ip,
                "oid": f"1.3.6.1.4.1.{metric_index + 1}",
                "endpoint": f"https://api.example/{ci_index}/{metric_index}",
                "cli_command": "show status",
                "cli_credential_ref": "cli-default",
                "site_id": f"site-{ci_index % 10}",
                "subnet": f"10.{ci_index // 65536}.{(ci_index // 256) % 256}.0/24",
                "metadata_version": "sim-v1",
            }
            emitted += 1


def _latencies(config: SimulationConfig, counts: Mapping[str, int]) -> list[float]:
    values: list[float] = []
    timeout_every = int(1 / config.timeout_rate) if config.timeout_rate > 0 else 0
    for protocol, count in counts.items():
        base = int(config.latency_ms_by_protocol.get(protocol, BASE_LATENCY_MS.get(protocol, 100)))
        for idx in range(count):
            latency = base + (idx % 100) * base / 100
            if timeout_every and idx % timeout_every == 0:
                latency += base * 8
            values.append(float(latency))
    return values or [0.0]


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 2)


def run_simulation(config: SimulationConfig, *, allow_db_sink: bool = False) -> SimulationReport:
    """Run a deterministic synthetic simulation and return an operator report."""
    sink = config.sink.lower()
    if sink != "synthetic" and not allow_db_sink:
        raise ValueError("DB-backed benchmark sink requires explicit allow_db_sink=True")

    counts = _protocol_counts(config)
    total = config.total_tasks
    latencies = _latencies(config, counts)
    worker_count = max(config.worker_count, 1)
    writer_count = max(config.db_writer_count, 1)
    worker_seconds = sum(latencies) / 1000 / worker_count
    writer_rows_per_second = writer_count * max(config.result_batch_size, 1) / max(config.db_write_latency_ms / 1000, 0.001)
    writer_seconds = total / max(writer_rows_per_second, 1)
    cycle_seconds = round(max(worker_seconds, writer_seconds), 2)
    failures = int(total * max(config.failure_rate, 0.0))
    timeouts = int(total * max(config.timeout_rate, 0.0))
    pressure_depth = max(0, total - config.max_task_queue_depth)
    deferred = pressure_depth if config.inject_backpressure or pressure_depth else 0
    dead_letters = int(failures * 0.05)
    writer_lag = max(0.0, round(cycle_seconds - config.target_cycle_seconds, 2))
    bottlenecks: list[str] = []
    if deferred:
        bottlenecks.append("backpressure")
    if writer_seconds >= worker_seconds:
        bottlenecks.append("writer")
    else:
        bottlenecks.append("workers")
    if timeouts:
        bottlenecks.append("protocol_timeout")

    return SimulationReport(
        total_tasks=total,
        protocol_counts=counts,
        sink=sink,
        cycle_duration_estimate_seconds=cycle_seconds,
        queue_depth=deferred,
        queue_oldest_age_seconds=min(config.target_cycle_seconds, int(deferred / max(config.task_batch_size, 1))) if deferred else 0,
        worker_throughput_per_second=round(total / max(worker_seconds, 0.001), 2),
        writer_rows_per_second=round(writer_rows_per_second, 2),
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        p99_latency_ms=_percentile(latencies, 0.99),
        writer_lag_seconds=writer_lag,
        db_write_latency_ms=config.db_write_latency_ms,
        deferred_count=deferred,
        dead_letter_count=dead_letters,
        failed_count=failures,
        timeout_count=timeouts,
        bottlenecks=bottlenecks,
        resource_hints=[
            f"target_cycle_seconds={config.target_cycle_seconds}",
            f"workers={config.worker_count}",
            f"db_writers={config.db_writer_count}",
            "synthetic-only by default; DB-backed mode requires explicit acknowledgement",
        ],
    )
