"""CLI host benchmark for the polling simulator.

Synthetic mode is the default and only safe mode for local/prod shells. DB mode
must be explicitly acknowledged by callers and is not used by tests.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import get_polling_pipeline_settings
from polling.simulator import SimulationConfig, run_simulation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run synthetic polling load benchmark")
    parser.add_argument("--ci-count", type=int)
    parser.add_argument("--metrics-per-ci", type=int)
    parser.add_argument("--protocol-mix")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--db-writers", type=int)
    parser.add_argument("--sink", choices=["synthetic", "db"])
    parser.add_argument("--allow-db", action="store_true", help="Required for DB-backed mode")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser


def _config_from_args(args: argparse.Namespace) -> SimulationConfig:
    config = SimulationConfig.from_settings(get_polling_pipeline_settings())
    return SimulationConfig(
        ci_count=args.ci_count or config.ci_count,
        metrics_per_ci=args.metrics_per_ci or config.metrics_per_ci,
        protocol_mix=args.protocol_mix or config.protocol_mix,
        target_cycle_seconds=config.target_cycle_seconds,
        duration_seconds=config.duration_seconds,
        worker_count=args.workers or config.worker_count,
        db_writer_count=args.db_writers or config.db_writer_count,
        task_batch_size=config.task_batch_size,
        result_batch_size=config.result_batch_size,
        sink=args.sink or config.sink,
        max_task_queue_depth=config.max_task_queue_depth,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_simulation(_config_from_args(args), allow_db_sink=args.allow_db)
    if args.json:
        print(report.to_json())
    else:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
