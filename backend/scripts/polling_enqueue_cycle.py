"""Operator command for enqueueing one polling cycle from explicit records.

This is a minimal, testable runtime entrypoint for the PostgreSQL queue path. It
does not discover production CI/metric definitions by itself; operators provide a
JSON array of scheduler records exported by an approved source. The command is
default-off through `POLLING_PG_QUEUE_ENABLED`.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _load_settings():
    from config import get_polling_pipeline_settings

    return get_polling_pipeline_settings()


def _load_session_factory():
    from postgres_db import SessionLocal

    return SessionLocal


def _build_cycle(*, scheduled_for: datetime, config_version: str | None, target_cycle_seconds: int):
    from polling.scheduler import build_cycle

    return build_cycle(
        scheduled_for=scheduled_for,
        config_version=config_version,
        target_cycle_seconds=target_cycle_seconds,
    )


def _build_tasks(records: list[dict[str, Any]], cycle):
    from polling.scheduler import build_tasks_from_records

    return build_tasks_from_records(records, cycle)


def _stale_metadata_indexes(records: list[dict[str, Any]], *, current_metadata_version: str | None) -> list[int]:
    from polling.scheduler import has_stale_metadata

    if not current_metadata_version:
        return []
    return [
        index
        for index, record in enumerate(records)
        if has_stale_metadata(record, current_metadata_version=current_metadata_version)
    ]


def _enqueue_cycle_tasks(db, cycle, tasks) -> None:
    from polling.scheduler import enqueue_cycle_tasks

    enqueue_cycle_tasks(db, cycle, tasks)


def _parse_datetime(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)


def _load_records(path: Path) -> list[dict[str, Any]]:
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
        raise ValueError("records file must contain a JSON array of objects")
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and enqueue one durable polling cycle from JSON records.")
    parser.add_argument("--records-file", required=True, type=Path, help="JSON array of scheduler records to enqueue.")
    parser.add_argument("--scheduled-for", help="Cycle timestamp in ISO-8601; defaults to current UTC time.")
    parser.add_argument("--config-version", help="Metadata/config version stamped on the cycle.")
    parser.add_argument(
        "--current-metadata-version",
        help="When metadata cache is enabled, reject records whose metadata_version differs from this value. Defaults to --config-version.",
    )
    parser.add_argument("--target-cycle-seconds", type=int, default=900, help="Target polling cycle duration.")
    parser.add_argument("--dry-run", action="store_true", help="Build tasks and print counts without writing queue rows.")
    args = parser.parse_args(argv)

    settings = _load_settings()
    if not getattr(settings, "pg_queue_enabled", False):
        print(json.dumps({"enabled": False, "reason": "POLLING_PG_QUEUE_ENABLED is false"}, indent=2))
        return 0

    records = _load_records(args.records_file)
    if getattr(settings, "metadata_cache_enabled", False):
        stale_indexes = _stale_metadata_indexes(
            records,
            current_metadata_version=args.current_metadata_version or args.config_version,
        )
        if stale_indexes:
            print(
                json.dumps(
                    {
                        "enabled": False,
                        "reason": "metadata_version_mismatch",
                        "stale_record_indexes": stale_indexes,
                    },
                    indent=2,
                )
            )
            return 2

    cycle = _build_cycle(
        scheduled_for=_parse_datetime(args.scheduled_for),
        config_version=args.config_version,
        target_cycle_seconds=args.target_cycle_seconds,
    )
    tasks = _build_tasks(records, cycle)
    if getattr(settings, "backpressure_enabled", False) and len(tasks) > int(getattr(settings, "backpressure_max_task_queue_depth", 100000)):
        print(
            json.dumps(
                {
                    "enabled": False,
                    "reason": "backpressure_max_task_queue_depth",
                    "task_count": len(tasks),
                    "threshold": int(getattr(settings, "backpressure_max_task_queue_depth", 100000)),
                },
                indent=2,
            )
        )
        return 2

    if not args.dry_run:
        db = _load_session_factory()()
        try:
            _enqueue_cycle_tasks(db, cycle, tasks)
        finally:
            db.close()

    print(
        json.dumps(
            {
                "enabled": True,
                "dry_run": args.dry_run,
                "cycle_id": str(cycle.cycle_id),
                "scheduled_for": cycle.scheduled_for.isoformat(),
                "task_count": len(tasks),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
