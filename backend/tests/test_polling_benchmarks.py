import json
import os
import runpy
from pathlib import Path
from unittest.mock import patch

import pytest


def test_simulation_config_reads_existing_polling_settings_and_env_duration():
    from config import PollingPipelineSettings
    from polling.simulator import SimulationConfig

    settings = PollingPipelineSettings(
        benchmark_ci_count=120,
        benchmark_metrics_per_ci=7,
        benchmark_protocol_mix="ICMP:0.5,SNMP:0.5",
        benchmark_duration_seconds=120,
        benchmark_sink="synthetic",
        target_cycle_seconds=900,
        worker_count=12,
        db_writer_count=3,
        task_batch_size=250,
        result_batch_size=1000,
    )
    with patch.dict(os.environ, {}, clear=False):
        config = SimulationConfig.from_settings(settings)

    assert config.total_tasks == 840
    assert config.duration_seconds == 120
    assert config.worker_count == 12
    assert config.db_writer_count == 3
    assert config.task_batch_size == 250
    assert config.result_batch_size == 1000


def test_db_backed_sink_requires_explicit_acknowledgement():
    from polling.simulator import SimulationConfig, run_simulation

    with pytest.raises(ValueError, match="explicit"):
        run_simulation(SimulationConfig(ci_count=1, metrics_per_ci=1, sink="db"))


def test_synthetic_host_benchmark_returns_json_report(capsys):
    from scripts.polling_host_benchmark import main

    rc = main([
        "--ci-count", "4",
        "--metrics-per-ci", "5",
        "--protocol-mix", "ICMP:0.5,SNMP:0.5",
        "--sink", "synthetic",
        "--json",
    ])

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 0
    assert data["total_tasks"] == 20
    assert data["sink"] == "synthetic"
    assert data["protocol_counts"] == {"ICMP": 10, "SNMP": 10}


def test_load_simulator_script_does_not_run_on_import(monkeypatch):
    monkeypatch.setattr("sys.argv", ["polling_load_simulator.py", "--ci-count", "1"])
    script = Path(__file__).resolve().parents[1] / "scripts" / "polling_load_simulator.py"
    namespace = runpy.run_path(str(script), run_name="not_main")

    assert "main" in namespace
