# backend/config.py
"""Application configuration — centralized settings loaded from environment.

This module provides Pydantic BaseSettings for type-safe env var access.
Currently covers MQTT configuration. Expand as needed for other subsystems.
"""

from __future__ import annotations

import os

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


def _env_int_bounded(name: str, default: int, *, minimum: int, maximum: int) -> int:
    """Parse a bounded integer environment variable with a safe fallback."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if minimum <= value <= maximum:
        return value
    return default


# ---------------------------------------------------------------------------
# Event Lock Observability Settings
# ---------------------------------------------------------------------------


EVENT_LOCK_DEFAULT_SAMPLE_WINDOW_SIZE = 500
EVENT_LOCK_DEFAULT_MAX_WRITER_CONTEXTS = 20
EVENT_LOCK_DEFAULT_SLOW_LOG_INFO_MS = 250.0
EVENT_LOCK_DEFAULT_WARNING_P95_MS = 1000.0
EVENT_LOCK_DEFAULT_CRITICAL_P99_MS = 5000.0
EVENT_LOCK_MIN_THRESHOLD_MS = 0.0
EVENT_LOCK_MAX_SLOW_LOG_INFO_MS = 60_000.0
EVENT_LOCK_MAX_ALERT_THRESHOLD_MS = 600_000.0
EVENT_LOCK_MIN_SAMPLE_WINDOW_SIZE = 1
EVENT_LOCK_MAX_SAMPLE_WINDOW_SIZE = 10_000
EVENT_LOCK_MIN_WRITER_CONTEXTS = 1
EVENT_LOCK_MAX_WRITER_CONTEXTS = 100
EVENT_LOCK_TOTAL_WRITER_SAMPLE_BUDGET = 10_000

TIME_SYNC_DEFAULT_WARNING_MS = 1000.0
TIME_SYNC_DEFAULT_CRITICAL_MS = 5000.0
TIME_SYNC_DEFAULT_QUERY_TIMEOUT_S = 1.0
TIME_SYNC_MIN_THRESHOLD_MS = 0.0
TIME_SYNC_MAX_THRESHOLD_MS = 600_000.0
TIME_SYNC_MIN_QUERY_TIMEOUT_S = 0.05
TIME_SYNC_MAX_QUERY_TIMEOUT_S = 30.0


class TimeSyncSettings(BaseModel):
    """Runtime thresholds for backend-vs-database clock-skew telemetry."""

    warning_ms: float = Field(default=TIME_SYNC_DEFAULT_WARNING_MS, ge=0)
    critical_ms: float = Field(default=TIME_SYNC_DEFAULT_CRITICAL_MS, gt=0)
    query_timeout_s: float = Field(default=TIME_SYNC_DEFAULT_QUERY_TIMEOUT_S, gt=0)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> TimeSyncSettings:
        if self.warning_ms >= self.critical_ms:
            raise ValueError("TIME_SYNC_WARNING_MS must be less than TIME_SYNC_CRITICAL_MS")
        return self

    @classmethod
    def from_env(cls) -> TimeSyncSettings:
        """Load time-sync skew thresholds from environment variables."""
        warning_ms = _env_float_bounded(
            "TIME_SYNC_WARNING_MS",
            TIME_SYNC_DEFAULT_WARNING_MS,
            minimum=TIME_SYNC_MIN_THRESHOLD_MS,
            maximum=TIME_SYNC_MAX_THRESHOLD_MS,
        )
        critical_ms = _env_float_bounded(
            "TIME_SYNC_CRITICAL_MS",
            TIME_SYNC_DEFAULT_CRITICAL_MS,
            minimum=TIME_SYNC_MIN_THRESHOLD_MS,
            maximum=TIME_SYNC_MAX_THRESHOLD_MS,
        )
        query_timeout_s = _env_float_bounded(
            "TIME_SYNC_QUERY_TIMEOUT_S",
            TIME_SYNC_DEFAULT_QUERY_TIMEOUT_S,
            minimum=TIME_SYNC_MIN_QUERY_TIMEOUT_S,
            maximum=TIME_SYNC_MAX_QUERY_TIMEOUT_S,
        )
        try:
            return cls(
                warning_ms=warning_ms,
                critical_ms=critical_ms,
                query_timeout_s=query_timeout_s,
            )
        except Exception:
            return cls()


_time_sync_settings: TimeSyncSettings | None = None


def get_time_sync_settings() -> TimeSyncSettings:
    """Return cached time-sync skew settings (singleton)."""
    global _time_sync_settings
    if _time_sync_settings is None:
        _time_sync_settings = TimeSyncSettings.from_env()
    return _time_sync_settings


class EventLockSettings(BaseModel):
    """Runtime observability thresholds for Event advisory-lock acquisition."""

    slow_log_info_ms: float = Field(default=EVENT_LOCK_DEFAULT_SLOW_LOG_INFO_MS, ge=0)
    warning_p95_ms: float = Field(default=EVENT_LOCK_DEFAULT_WARNING_P95_MS, ge=0)
    critical_p99_ms: float = Field(default=EVENT_LOCK_DEFAULT_CRITICAL_P99_MS, ge=0)
    sample_window_size: int = Field(
        default=EVENT_LOCK_DEFAULT_SAMPLE_WINDOW_SIZE,
        ge=EVENT_LOCK_MIN_SAMPLE_WINDOW_SIZE,
        le=EVENT_LOCK_MAX_SAMPLE_WINDOW_SIZE,
    )
    max_writer_contexts: int = Field(
        default=EVENT_LOCK_DEFAULT_MAX_WRITER_CONTEXTS,
        ge=EVENT_LOCK_MIN_WRITER_CONTEXTS,
        le=EVENT_LOCK_MAX_WRITER_CONTEXTS,
    )

    @classmethod
    def from_env(cls) -> EventLockSettings:
        """Load Event lock observability settings from environment variables."""
        sample_window_size = _env_int_bounded(
            "EVENT_LOCK_SAMPLE_WINDOW_SIZE",
            EVENT_LOCK_DEFAULT_SAMPLE_WINDOW_SIZE,
            minimum=EVENT_LOCK_MIN_SAMPLE_WINDOW_SIZE,
            maximum=EVENT_LOCK_MAX_SAMPLE_WINDOW_SIZE,
        )
        max_writer_contexts = _env_int_bounded(
            "EVENT_LOCK_MAX_WRITER_CONTEXTS",
            EVENT_LOCK_DEFAULT_MAX_WRITER_CONTEXTS,
            minimum=EVENT_LOCK_MIN_WRITER_CONTEXTS,
            maximum=EVENT_LOCK_MAX_WRITER_CONTEXTS,
        )
        max_contexts_for_budget = max(
            EVENT_LOCK_MIN_WRITER_CONTEXTS,
            EVENT_LOCK_TOTAL_WRITER_SAMPLE_BUDGET // sample_window_size,
        )
        return cls(
            slow_log_info_ms=_env_float_bounded(
                "EVENT_LOCK_SLOW_LOG_INFO_MS",
                EVENT_LOCK_DEFAULT_SLOW_LOG_INFO_MS,
                minimum=EVENT_LOCK_MIN_THRESHOLD_MS,
                maximum=EVENT_LOCK_MAX_SLOW_LOG_INFO_MS,
            ),
            warning_p95_ms=_env_float_bounded(
                "EVENT_LOCK_WARNING_P95_MS",
                EVENT_LOCK_DEFAULT_WARNING_P95_MS,
                minimum=EVENT_LOCK_MIN_THRESHOLD_MS,
                maximum=EVENT_LOCK_MAX_ALERT_THRESHOLD_MS,
            ),
            critical_p99_ms=_env_float_bounded(
                "EVENT_LOCK_CRITICAL_P99_MS",
                EVENT_LOCK_DEFAULT_CRITICAL_P99_MS,
                minimum=EVENT_LOCK_MIN_THRESHOLD_MS,
                maximum=EVENT_LOCK_MAX_ALERT_THRESHOLD_MS,
            ),
            sample_window_size=sample_window_size,
            max_writer_contexts=min(max_writer_contexts, max_contexts_for_budget),
        )


_event_lock_settings: EventLockSettings | None = None


def get_event_lock_settings() -> EventLockSettings:
    """Return cached Event lock observability settings (singleton)."""
    global _event_lock_settings
    if _event_lock_settings is None:
        _event_lock_settings = EventLockSettings.from_env()
    return _event_lock_settings


# ---------------------------------------------------------------------------
# Event Batch Pruner Settings
# ---------------------------------------------------------------------------


class EventBatchSettings(BaseModel):
    """Batch processing settings for the event batch pruner."""

    batch_size: int = 500
    batch_delay_ms: int = 100
    batch_timeout_s: int = 30

    @classmethod
    def from_env(cls) -> EventBatchSettings:
        """Load event batch settings from environment variables."""
        return cls(
            batch_size=int(os.getenv("EVENT_BATCH_SIZE", "500")),
            batch_delay_ms=int(os.getenv("EVENT_BATCH_DELAY_MS", "100")),
            batch_timeout_s=int(os.getenv("EVENT_BATCH_TIMEOUT_S", "30")),
        )


_event_batch_settings: EventBatchSettings | None = None


def get_event_batch_settings() -> EventBatchSettings:
    """Return cached event batch settings (singleton)."""
    global _event_batch_settings
    if _event_batch_settings is None:
        _event_batch_settings = EventBatchSettings.from_env()
    return _event_batch_settings


# ---------------------------------------------------------------------------
# Event Prune Auto-Scheduler Settings (fix-423 PR #2)
# ---------------------------------------------------------------------------


# Default values for EventPruneSettings — mirror design.md §Observability
# (REQ-PRUNE-003, REQ-OBS-PRUNE-001).
EVENT_PRUNE_DEFAULT_INTERVAL_SECONDS = 3600
EVENT_PRUNE_DEFAULT_STALE_AFTER_SECONDS = 3600
EVENT_PRUNE_DEFAULT_BATCH_SIZE = 500
EVENT_PRUNE_MIN_INTERVAL_SECONDS = 60
EVENT_PRUNE_MIN_STALE_AFTER_SECONDS = 60
EVENT_PRUNE_MIN_BATCH_SIZE = 1


class EventPruneSettings(BaseModel):
    """Runtime settings for the auto-prune scheduler on ``backup_scheduler``.

    Driven by environment variables; the scheduler registration code in
    ``backend/main.py:_register_event_prune_job`` reads these on startup.

    Fields
    ------
    enabled:
        Kill-switch. Defaults to True. ``EVENT_PRUNE_ENABLED=false`` skips
        registration entirely (mirrors ``SYSTEM_STATUS_SNAPSHOTS_ENABLED``).
    interval_seconds:
        How often the APScheduler ``IntervalTrigger`` fires. Default 1h.
        Min 60s to avoid hammering Neo4j.
    batch_size:
        Max RECOVERED rows to close per tick. Default borrows from
        :class:`EventBatchSettings` (``EVENT_BATCH_SIZE``, default 500).
        ``EVENT_PRUNE_BATCH_SIZE`` overrides.
    stale_after_seconds:
        Age threshold for ``events_recovered_stale_total`` (REQ-OBS-PRUNE-001).
        Default 1h; ``EVENT_PRUNE_STALE_AFTER_SECONDS`` overrides.
    """

    enabled: bool = True
    interval_seconds: int = Field(
        default=EVENT_PRUNE_DEFAULT_INTERVAL_SECONDS,
        ge=EVENT_PRUNE_MIN_INTERVAL_SECONDS,
    )
    batch_size: int = Field(
        default=EVENT_PRUNE_DEFAULT_BATCH_SIZE,
        ge=EVENT_PRUNE_MIN_BATCH_SIZE,
    )
    stale_after_seconds: int = Field(
        default=EVENT_PRUNE_DEFAULT_STALE_AFTER_SECONDS,
        ge=EVENT_PRUNE_MIN_STALE_AFTER_SECONDS,
    )

    @classmethod
    def from_env(cls) -> EventPruneSettings:
        """Load auto-prune scheduler settings from environment variables.

        Invalid values fall back to defaults without raising — mirrors
        ``_parse_system_status_int`` / ``_parse_system_status_bool`` in
        ``main.py:45-71``. An invalid bool falls back to True (safe default).
        """

        def _int(name: str, default: int) -> int:
            raw = os.getenv(name)
            if raw is None:
                return default
            try:
                value = int(raw.strip())
            except ValueError:
                return default
            return value if value > 0 else default

        enabled_raw = os.getenv("EVENT_PRUNE_ENABLED")
        if enabled_raw is None:
            enabled = True
        else:
            normalized = enabled_raw.strip().lower()
            # Invalid values (anything not in the truthy set and not in the
            # explicit falsy set) fall back to True — mirrors
            # ``_parse_system_status_bool`` in main.py:45-50 which returns
            # None on invalid input and main.py then defaults to True with a
            # warning log. This keeps the scheduler safe by default.
            if normalized in {"1", "true", "yes", "on"}:
                enabled = True
            elif normalized in {"0", "false", "no", "off"}:
                enabled = False
            else:
                enabled = True

        # Borrow batch-size default from EventBatchSettings so the two
        # knobs stay aligned by default.
        try:
            default_batch_size = EventBatchSettings().batch_size
        except Exception:
            default_batch_size = EVENT_PRUNE_DEFAULT_BATCH_SIZE

        return cls(
            enabled=enabled,
            interval_seconds=_int(
                "EVENT_PRUNE_INTERVAL_SECONDS", EVENT_PRUNE_DEFAULT_INTERVAL_SECONDS
            ),
            batch_size=_int("EVENT_PRUNE_BATCH_SIZE", default_batch_size),
            stale_after_seconds=_int(
                "EVENT_PRUNE_STALE_AFTER_SECONDS", EVENT_PRUNE_DEFAULT_STALE_AFTER_SECONDS
            ),
        )


# ---------------------------------------------------------------------------
# MQTT Settings
# ---------------------------------------------------------------------------


class MQTTSettings(BaseModel):
    """MQTT broker connection settings."""

    broker_url: str = "mqtt://localhost:1883"
    username: str | None = None
    password: str | None = None
    client_id: str = "rtu-telemetry-subscriber"
    wildcard_topic: str = "rtu/+/+/telemetry"
    qos: int = 1

    @classmethod
    def from_env(cls) -> MQTTSettings:
        """Load MQTT settings from environment variables."""
        return cls(
            broker_url=os.getenv("MQTT_BROKER_URL", "mqtt://localhost:1883"),
            username=os.getenv("MQTT_USERNAME"),
            password=os.getenv("MQTT_PASSWORD"),
            client_id=os.getenv("MQTT_CLIENT_ID", "rtu-telemetry-subscriber"),
            wildcard_topic=os.getenv("MQTT_WILDCARD_TOPIC", "rtu/+/+/telemetry"),
            qos=int(os.getenv("MQTT_QOS", "1")),
        )


class MQTTRuntimeSettings(BaseModel):
    """Runtime topology flags for MQTT subscriber and bridge behavior."""

    bridge_enabled: bool = True
    missed_heartbeat_seconds: int = 90
    run_subscriber_in_process: bool = False

    @classmethod
    def from_env(cls) -> MQTTRuntimeSettings:
        """Load MQTT runtime settings from environment variables.

        ``MQTT_SUBSCRIBER_STALE_HEARTBEAT_SECONDS`` is the preferred
        primary key. ``MQTT_MAPPING_BRIDGE_MISSED_HEARTBEAT_SECONDS`` remains
        supported for backward compatibility.
        """

        missed_heartbeat_seconds = _env_int_bounded(
            "MQTT_SUBSCRIBER_STALE_HEARTBEAT_SECONDS",
            default=90,
            minimum=1,
            maximum=86_400,
        )

        if os.getenv("MQTT_SUBSCRIBER_STALE_HEARTBEAT_SECONDS") is None:
            missed_heartbeat_seconds = _env_int_bounded(
                "MQTT_MAPPING_BRIDGE_MISSED_HEARTBEAT_SECONDS",
                default=missed_heartbeat_seconds,
                minimum=1,
                maximum=86_400,
            )

        return cls(
            bridge_enabled=_env_bool("MQTT_MAPPING_BRIDGE_ENABLED", default=True),
            missed_heartbeat_seconds=missed_heartbeat_seconds,
            run_subscriber_in_process=_env_bool("ENABLE_MQTT_SUBSCRIBER", default=False),
        )


# Singleton instance (lazy-loaded)
_mqtt_settings: MQTTSettings | None = None
_mqtt_runtime_settings: MQTTRuntimeSettings | None = None


def get_mqtt_settings() -> MQTTSettings:
    """Return cached MQTT settings (singleton)."""
    global _mqtt_settings
    if _mqtt_settings is None:
        _mqtt_settings = MQTTSettings.from_env()
    return _mqtt_settings


def get_mqtt_runtime_settings() -> MQTTRuntimeSettings:
    """Return cached MQTT runtime settings (singleton)."""
    global _mqtt_runtime_settings
    if _mqtt_runtime_settings is None:
        _mqtt_runtime_settings = MQTTRuntimeSettings.from_env()
    return _mqtt_runtime_settings


# ---------------------------------------------------------------------------
# CLI Credentials Settings
# ---------------------------------------------------------------------------


class CLICredentialsSettings(BaseModel):
    """CLI credential settings for network device access."""

    default_user: str | None = None
    default_pass: str | None = None
    enable_pass: str | None = None

    @classmethod
    def from_env(cls) -> CLICredentialsSettings:
        """Load CLI credentials from environment variables."""
        return cls(
            default_user=os.getenv("CLI_DEFAULT_USER"),
            default_pass=os.getenv("CLI_DEFAULT_PASS"),
            enable_pass=os.getenv("CLI_ENABLE_PASS"),
        )


_cli_credentials_settings: CLICredentialsSettings | None = None


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
    # Topology-based root-cause analysis on the production snmp-engine write path
    # (fix #310). When true, poll_snmp() builds a per-cycle open-parent cache and
    # tags dependent events as PROPAGATED. When false, every event is ROOT —
    # identical to pre-fix behaviour. Operator kill-switch: toggle + restart the
    # snmp-engine container, no code redeploy required.
    enable_topology_rca: bool = True

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
    def from_env(cls) -> PollingPipelineSettings:
        """Load polling pipeline settings from environment variables."""
        return cls(
            pipeline_observe_only=_env_bool("POLLING_PIPELINE_OBSERVE_ONLY"),
            pg_queue_enabled=_env_bool("POLLING_PG_QUEUE_ENABLED"),
            snmp_leased_worker_enabled=_env_bool("POLLING_SNMP_LEASED_WORKER"),
            db_writer_enabled=_env_bool("POLLING_DB_WRITER_ENABLED"),
            backpressure_enabled=_env_bool("POLLING_BACKPRESSURE_ENABLED"),
            metadata_cache_enabled=_env_bool("POLLING_METADATA_CACHE_ENABLED"),
            enable_topology_rca=_env_bool("ENABLE_TOPOLOGY_RCA", default=True),
            target_cycle_seconds=int(os.getenv("POLLING_TARGET_CYCLE_SECONDS", "900")),
            worker_count=int(os.getenv("POLLING_WORKERS", "8")),
            db_writer_count=int(os.getenv("POLLING_DB_WRITERS", "1")),
            task_batch_size=int(os.getenv("POLLING_TASK_BATCH_SIZE", "100")),
            result_batch_size=int(os.getenv("POLLING_RESULT_BATCH_SIZE", "500")),
            backpressure_max_task_queue_depth=int(
                os.getenv("POLLING_BACKPRESSURE_MAX_TASK_QUEUE_DEPTH", "100000")
            ),
            backpressure_max_writer_lag_seconds=int(
                os.getenv("POLLING_BACKPRESSURE_MAX_WRITER_LAG_SECONDS", "120")
            ),
            backpressure_retry_max_attempts=int(
                os.getenv("POLLING_BACKPRESSURE_RETRY_MAX_ATTEMPTS", "5")
            ),
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


_polling_pipeline_settings: PollingPipelineSettings | None = None


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
    jitter_warning_ms: float = Field(default=50.0, ge=0)
    jitter_critical_ms: float = Field(default=150.0, gt=0)
    packet_loss_warning_pct: float = Field(default=10.0, ge=0, le=100)
    packet_loss_critical_pct: float = Field(default=50.0, ge=0, le=100)

    @model_validator(mode="after")
    def validate_latency_thresholds(self) -> ICMPSettings:
        if self.latency_warning_ms >= self.latency_critical_ms:
            raise ValueError("ICMP_LATENCY_WARNING_MS must be less than ICMP_LATENCY_CRITICAL_MS")
        return self

    @model_validator(mode="after")
    def validate_jitter_thresholds(self) -> ICMPSettings:
        if self.jitter_warning_ms >= self.jitter_critical_ms:
            raise ValueError("ICMP_JITTER_WARNING_MS must be less than ICMP_JITTER_CRITICAL_MS")
        return self

    @model_validator(mode="after")
    def validate_packet_loss_thresholds(self) -> ICMPSettings:
        if self.packet_loss_warning_pct >= self.packet_loss_critical_pct:
            raise ValueError(
                "ICMP_PACKET_LOSS_WARNING_PCT must be less than ICMP_PACKET_LOSS_CRITICAL_PCT"
            )
        return self

    @classmethod
    def from_env(cls) -> ICMPSettings:
        """Load ICMP settings from environment variables."""
        return cls(
            timeout_ms=int(os.getenv("ICMP_TIMEOUT_MS", "3000")),
            retries=int(os.getenv("ICMP_RETRIES", "2")),
            debounce_count=int(os.getenv("ICMP_DEBOUNCE_COUNT", "3")),
            latency_warning_ms=float(os.getenv("ICMP_LATENCY_WARNING_MS", "100")),
            latency_critical_ms=float(os.getenv("ICMP_LATENCY_CRITICAL_MS", "500")),
            jitter_warning_ms=float(os.getenv("ICMP_JITTER_WARNING_MS", "50")),
            jitter_critical_ms=float(os.getenv("ICMP_JITTER_CRITICAL_MS", "150")),
            packet_loss_warning_pct=float(os.getenv("ICMP_PACKET_LOSS_WARNING_PCT", "10")),
            packet_loss_critical_pct=float(os.getenv("ICMP_PACKET_LOSS_CRITICAL_PCT", "50")),
        )


_icmp_settings: ICMPSettings | None = None


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
    def from_env(cls) -> LMStudioSettings:
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
    def from_env(cls) -> AIPromptsSettings:
        """Load the AI prompts folder from the environment."""
        return cls(prompts_dir=os.getenv("AI_PROMPTS_DIR", "").strip())


def get_ai_prompts_settings() -> AIPromptsSettings:
    """Return fresh AI prompts settings so tests and env changes are respected."""
    return AIPromptsSettings.from_env()
