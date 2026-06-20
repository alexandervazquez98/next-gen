# backend/config.py
"""Application configuration — centralized settings loaded from environment.

This module provides Pydantic BaseSettings for type-safe env var access.
Currently covers MQTT configuration. Expand as needed for other subsystems.
"""

from __future__ import annotations

import os
from typing import Optional
from pydantic import BaseModel, Field, model_validator


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable with conservative defaults."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float_bounded(name: str, default: float, *, minimum: float, maximum: float) -> float:
    """Parse a bounded float environment variable with a safe fallback."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if minimum <= value <= maximum:
        return value
    return default


# ---------------------------------------------------------------------------
# Event Batch Pruner Settings
# ---------------------------------------------------------------------------


class EventBatchSettings(BaseModel):
    """Batch processing settings for the event batch pruner."""

    batch_size: int = 500
    batch_delay_ms: int = 100
    batch_timeout_s: int = 30

    @classmethod
    def from_env(cls) -> "EventBatchSettings":
        """Load event batch settings from environment variables."""
        return cls(
            batch_size=int(os.getenv("EVENT_BATCH_SIZE", "500")),
            batch_delay_ms=int(os.getenv("EVENT_BATCH_DELAY_MS", "100")),
            batch_timeout_s=int(os.getenv("EVENT_BATCH_TIMEOUT_S", "30")),
        )


_event_batch_settings: Optional[EventBatchSettings] = None


def get_event_batch_settings() -> EventBatchSettings:
    """Return cached event batch settings (singleton)."""
    global _event_batch_settings
    if _event_batch_settings is None:
        _event_batch_settings = EventBatchSettings.from_env()
    return _event_batch_settings


# ---------------------------------------------------------------------------
# MQTT Settings
# ---------------------------------------------------------------------------


class MQTTSettings(BaseModel):
    """MQTT broker connection settings."""

    broker_url: str = "mqtt://localhost:1883"
    username: Optional[str] = None
    password: Optional[str] = None
    client_id: str = "rtu-telemetry-subscriber"
    wildcard_topic: str = "rtu/+/+/telemetry"
    qos: int = 1

    @classmethod
    def from_env(cls) -> "MQTTSettings":
        """Load MQTT settings from environment variables."""
        return cls(
            broker_url=os.getenv("MQTT_BROKER_URL", "mqtt://localhost:1883"),
            username=os.getenv("MQTT_USERNAME"),
            password=os.getenv("MQTT_PASSWORD"),
            client_id=os.getenv("MQTT_CLIENT_ID", "rtu-telemetry-subscriber"),
            wildcard_topic=os.getenv("MQTT_WILDCARD_TOPIC", "rtu/+/+/telemetry"),
            qos=int(os.getenv("MQTT_QOS", "1")),
        )


# Singleton instance (lazy-loaded)
_mqtt_settings: Optional[MQTTSettings] = None


def get_mqtt_settings() -> MQTTSettings:
    """Return cached MQTT settings (singleton)."""
    global _mqtt_settings
    if _mqtt_settings is None:
        _mqtt_settings = MQTTSettings.from_env()
    return _mqtt_settings


# ---------------------------------------------------------------------------
# CLI Credentials Settings
# ---------------------------------------------------------------------------


class CLICredentialsSettings(BaseModel):
    """CLI credential settings for network device access."""

    default_user: Optional[str] = None
    default_pass: Optional[str] = None
    enable_pass: Optional[str] = None

    @classmethod
    def from_env(cls) -> "CLICredentialsSettings":
        """Load CLI credentials from environment variables."""
        return cls(
            default_user=os.getenv("CLI_DEFAULT_USER"),
            default_pass=os.getenv("CLI_DEFAULT_PASS"),
            enable_pass=os.getenv("CLI_ENABLE_PASS"),
        )


_cli_credentials_settings: Optional[CLICredentialsSettings] = None


def get_cli_credentials_settings() -> CLICredentialsSettings:
    """Return cached CLI credentials settings (singleton)."""
    global _cli_credentials_settings
    if _cli_credentials_settings is None:
        _cli_credentials_settings = CLICredentialsSettings.from_env()
    return _cli_credentials_settings


# ---------------------------------------------------------------------------
# Polling Pipeline Settings
# ---------------------------------------------------------------------------


class PollingPipelineSettings(BaseModel):
    """Feature flags and safe defaults for the scalable polling pipeline.

    PR 1 only introduces observe-only/configuration contracts. Runtime behavior
    remains legacy unless later slices explicitly enable queue, leased worker,
    writer, backpressure, or cache flags.
    """

    pipeline_observe_only: bool = False
    pg_queue_enabled: bool = False
    snmp_leased_worker_enabled: bool = False
    db_writer_enabled: bool = False
    backpressure_enabled: bool = False
    metadata_cache_enabled: bool = False

    target_cycle_seconds: int = Field(default=900, ge=1)
    worker_count: int = Field(default=8, ge=1)
    db_writer_count: int = Field(default=1, ge=1)
    task_batch_size: int = Field(default=100, ge=1)
    result_batch_size: int = Field(default=500, ge=1)

    # PR6 policy defaults: conservative throttling with ICMP protected first.
    backpressure_max_task_queue_depth: int = Field(default=100000, ge=1)
    backpressure_max_writer_lag_seconds: int = Field(default=120, ge=1)
    backpressure_retry_max_attempts: int = Field(default=5, ge=1)
    metadata_cache_ttl_seconds: int = Field(default=300, ge=1)

    benchmark_ci_count: int = Field(default=8000, ge=1)
    benchmark_metrics_per_ci: int = Field(default=35, ge=1)
    benchmark_duration_seconds: int = Field(default=0, ge=0)
    benchmark_protocol_mix: str = "ICMP:0.15,SNMP:0.55,CLI:0.15,REST:0.10,MQTT_STUB:0.05"
    benchmark_sink: str = "synthetic"

    @classmethod
    def from_env(cls) -> "PollingPipelineSettings":
        """Load polling pipeline settings from environment variables."""
        return cls(
            pipeline_observe_only=_env_bool("POLLING_PIPELINE_OBSERVE_ONLY"),
            pg_queue_enabled=_env_bool("POLLING_PG_QUEUE_ENABLED"),
            snmp_leased_worker_enabled=_env_bool("POLLING_SNMP_LEASED_WORKER"),
            db_writer_enabled=_env_bool("POLLING_DB_WRITER_ENABLED"),
            backpressure_enabled=_env_bool("POLLING_BACKPRESSURE_ENABLED"),
            metadata_cache_enabled=_env_bool("POLLING_METADATA_CACHE_ENABLED"),
            target_cycle_seconds=int(os.getenv("POLLING_TARGET_CYCLE_SECONDS", "900")),
            worker_count=int(os.getenv("POLLING_WORKERS", "8")),
            db_writer_count=int(os.getenv("POLLING_DB_WRITERS", "1")),
            task_batch_size=int(os.getenv("POLLING_TASK_BATCH_SIZE", "100")),
            result_batch_size=int(os.getenv("POLLING_RESULT_BATCH_SIZE", "500")),
            backpressure_max_task_queue_depth=int(os.getenv("POLLING_BACKPRESSURE_MAX_TASK_QUEUE_DEPTH", "100000")),
            backpressure_max_writer_lag_seconds=int(os.getenv("POLLING_BACKPRESSURE_MAX_WRITER_LAG_SECONDS", "120")),
            backpressure_retry_max_attempts=int(os.getenv("POLLING_BACKPRESSURE_RETRY_MAX_ATTEMPTS", "5")),
            metadata_cache_ttl_seconds=int(os.getenv("POLLING_METADATA_CACHE_TTL_SECONDS", "300")),
            benchmark_ci_count=int(os.getenv("POLLING_BENCHMARK_CI_COUNT", "8000")),
            benchmark_metrics_per_ci=int(os.getenv("POLLING_BENCHMARK_METRICS_PER_CI", "35")),
            benchmark_duration_seconds=int(os.getenv("POLLING_BENCHMARK_DURATION_SECONDS", "0")),
            benchmark_protocol_mix=os.getenv(
                "POLLING_BENCHMARK_PROTOCOL_MIX",
                "ICMP:0.15,SNMP:0.55,CLI:0.15,REST:0.10,MQTT_STUB:0.05",
            ),
            benchmark_sink=os.getenv("POLLING_BENCHMARK_SINK", "synthetic"),
        )


_polling_pipeline_settings: Optional[PollingPipelineSettings] = None


def get_polling_pipeline_settings() -> PollingPipelineSettings:
    """Return cached polling pipeline settings (singleton)."""
    global _polling_pipeline_settings
    if _polling_pipeline_settings is None:
        _polling_pipeline_settings = PollingPipelineSettings.from_env()
    return _polling_pipeline_settings


# ---------------------------------------------------------------------------
# ICMP Settings
# ---------------------------------------------------------------------------


class ICMPSettings(BaseModel):
    """ICMP polling settings for timeout, retry, debounce, and latency thresholds."""

    timeout_ms: int = Field(default=3000, ge=1)
    retries: int = Field(default=2, ge=0)
    debounce_count: int = Field(default=3, ge=1)
    latency_warning_ms: float = Field(default=100.0, ge=0)
    latency_critical_ms: float = Field(default=500.0, gt=0)

    @model_validator(mode="after")
    def validate_latency_thresholds(self) -> "ICMPSettings":
        if self.latency_warning_ms >= self.latency_critical_ms:
            raise ValueError("ICMP_LATENCY_WARNING_MS must be less than ICMP_LATENCY_CRITICAL_MS")
        return self

    @classmethod
    def from_env(cls) -> "ICMPSettings":
        """Load ICMP settings from environment variables."""
        return cls(
            timeout_ms=int(os.getenv("ICMP_TIMEOUT_MS", "3000")),
            retries=int(os.getenv("ICMP_RETRIES", "2")),
            debounce_count=int(os.getenv("ICMP_DEBOUNCE_COUNT", "3")),
            latency_warning_ms=float(os.getenv("ICMP_LATENCY_WARNING_MS", "100")),
            latency_critical_ms=float(os.getenv("ICMP_LATENCY_CRITICAL_MS", "500")),
        )


_icmp_settings: Optional[ICMPSettings] = None


def get_icmp_settings() -> ICMPSettings:
    """Return cached ICMP settings (singleton)."""
    global _icmp_settings
    if _icmp_settings is None:
        _icmp_settings = ICMPSettings.from_env()
    return _icmp_settings


# ---------------------------------------------------------------------------
# LM Studio AI Chat Settings
# ---------------------------------------------------------------------------


class LMStudioSettings(BaseModel):
    """Server-side LM Studio proxy settings."""

    enabled: bool = False
    base_url: str = "http://localhost:1234/v1"
    model: str = "local-model"
    timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    max_tokens: int = Field(default=800, gt=0, le=4096)

    @classmethod
    def from_env(cls) -> "LMStudioSettings":
        """Load LM Studio settings from environment variables."""
        return cls(
            enabled=_env_bool("LM_STUDIO_ENABLED", default=False),
            base_url=os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1").rstrip("/"),
            model=os.getenv("LM_STUDIO_MODEL", "local-model"),
            timeout_seconds=_env_float_bounded(
                "LM_STUDIO_TIMEOUT_SECONDS",
                15.0,
                minimum=0.000001,
                maximum=120.0,
            ),
            max_tokens=int(
                _env_float_bounded(
                    "LM_STUDIO_MAX_TOKENS",
                    800.0,
                    minimum=1.0,
                    maximum=4096.0,
                )
            ),
        )


def get_lm_studio_settings() -> LMStudioSettings:
    """Return fresh LM Studio settings so tests and env changes are respected."""
    return LMStudioSettings.from_env()


# ---------------------------------------------------------------------------
# AI Prompts Settings
# ---------------------------------------------------------------------------


class AIPromptsSettings(BaseModel):
    """User-overridable AI prompts folder.

    When ``prompts_dir`` is empty the loaders read the bundled defaults
    in-place (legacy behavior). When set, it points at a runtime data folder
    that is seeded once from the bundled tree and then treated as a frozen
    snapshot owned by the operator.
    """

    prompts_dir: str = ""

    @classmethod
    def from_env(cls) -> "AIPromptsSettings":
        """Load the AI prompts folder from the environment."""
        return cls(prompts_dir=os.getenv("AI_PROMPTS_DIR", "").strip())


def get_ai_prompts_settings() -> AIPromptsSettings:
    """Return fresh AI prompts settings so tests and env changes are respected."""
    return AIPromptsSettings.from_env()
