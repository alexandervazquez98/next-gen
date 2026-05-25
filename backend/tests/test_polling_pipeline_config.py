import os
from unittest.mock import patch


def _reset_polling_settings_cache():
    import config as config_module
    config_module._polling_pipeline_settings = None


class TestPollingPipelineSettings:
    def test_polling_pipeline_settings_defaults_are_safe(self):
        from config import PollingPipelineSettings

        settings = PollingPipelineSettings()

        assert settings.pipeline_observe_only is False
        assert settings.pg_queue_enabled is False
        assert settings.snmp_leased_worker_enabled is False
        assert settings.db_writer_enabled is False
        assert settings.backpressure_enabled is False
        assert settings.metadata_cache_enabled is False
        assert settings.target_cycle_seconds == 900
        assert settings.worker_count == 8
        assert settings.db_writer_count == 1
        assert settings.task_batch_size == 100
        assert settings.result_batch_size == 500
        assert settings.benchmark_ci_count == 8000
        assert settings.benchmark_metrics_per_ci == 35
        assert settings.benchmark_sink == "synthetic"

    def test_polling_pipeline_settings_from_env_overrides(self):
        from config import PollingPipelineSettings

        with patch.dict(os.environ, {
            "POLLING_PIPELINE_OBSERVE_ONLY": "true",
            "POLLING_PG_QUEUE_ENABLED": "1",
            "POLLING_SNMP_LEASED_WORKER": "yes",
            "POLLING_DB_WRITER_ENABLED": "on",
            "POLLING_BACKPRESSURE_ENABLED": "true",
            "POLLING_METADATA_CACHE_ENABLED": "true",
            "POLLING_TARGET_CYCLE_SECONDS": "600",
            "POLLING_WORKERS": "16",
            "POLLING_DB_WRITERS": "3",
            "POLLING_TASK_BATCH_SIZE": "250",
            "POLLING_RESULT_BATCH_SIZE": "750",
            "POLLING_BENCHMARK_CI_COUNT": "1200",
            "POLLING_BENCHMARK_METRICS_PER_CI": "12",
            "POLLING_BENCHMARK_PROTOCOL_MIX": "ICMP:0.2,SNMP:0.8",
            "POLLING_BENCHMARK_SINK": "db",
        }, clear=True):
            settings = PollingPipelineSettings.from_env()

        assert settings.pipeline_observe_only is True
        assert settings.pg_queue_enabled is True
        assert settings.snmp_leased_worker_enabled is True
        assert settings.db_writer_enabled is True
        assert settings.backpressure_enabled is True
        assert settings.metadata_cache_enabled is True
        assert settings.target_cycle_seconds == 600
        assert settings.worker_count == 16
        assert settings.db_writer_count == 3
        assert settings.task_batch_size == 250
        assert settings.result_batch_size == 750
        assert settings.benchmark_ci_count == 1200
        assert settings.benchmark_metrics_per_ci == 12
        assert settings.benchmark_protocol_mix == "ICMP:0.2,SNMP:0.8"
        assert settings.benchmark_sink == "db"

    def test_polling_pipeline_boolean_env_false_values_remain_disabled(self):
        from config import PollingPipelineSettings

        with patch.dict(os.environ, {
            "POLLING_PIPELINE_OBSERVE_ONLY": "false",
            "POLLING_PG_QUEUE_ENABLED": "0",
            "POLLING_SNMP_LEASED_WORKER": "no",
            "POLLING_DB_WRITER_ENABLED": "off",
        }, clear=True):
            settings = PollingPipelineSettings.from_env()

        assert settings.pipeline_observe_only is False
        assert settings.pg_queue_enabled is False
        assert settings.snmp_leased_worker_enabled is False
        assert settings.db_writer_enabled is False

    def test_get_polling_pipeline_settings_returns_cached_singleton(self):
        from config import get_polling_pipeline_settings

        _reset_polling_settings_cache()
        settings1 = get_polling_pipeline_settings()
        settings2 = get_polling_pipeline_settings()

        assert settings1 is settings2
