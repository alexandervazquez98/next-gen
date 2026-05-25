"""Operator command for one polling result-writer pass.

The command is default-off through `POLLING_DB_WRITER_ENABLED`. It is intended
for supervised process managers to invoke in a loop or on a schedule once the
queue pipeline has been staged and validated.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _load_settings():
    from config import get_polling_pipeline_settings

    return get_polling_pipeline_settings()


def _load_session_factory():
    from postgres_db import SessionLocal

    return SessionLocal


def _load_neo4j_driver():
    from database import get_db

    return get_db()


def _run_writer_once(queue_db, timescale_db, neo4j_driver, *, settings, worker_id: str, lease_ttl_seconds: int, writer_partitions: list[int] | None):
    from polling.writer_pool import run_writer_once

    return run_writer_once(
        queue_db,
        timescale_db,
        neo4j_driver,
        settings=settings,
        worker_id=worker_id,
        lease_ttl_seconds=lease_ttl_seconds,
        writer_partitions=writer_partitions,
    )


def _partitions(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def _default_worker_id() -> str:
    return f"polling-writer-{socket.gethostname()}-{os.getpid()}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one gated polling result-writer batch.")
    parser.add_argument("--worker-id", default=_default_worker_id(), help="Lease owner ID written to poll_result_queue.")
    parser.add_argument("--lease-ttl-seconds", type=int, default=60, help="Result lease TTL for this writer pass.")
    parser.add_argument("--writer-partitions", help="Optional comma-separated partition IDs for this writer.")
    args = parser.parse_args(argv)

    settings = _load_settings()
    if not getattr(settings, "db_writer_enabled", False):
        print(json.dumps({"enabled": False, "reason": "POLLING_DB_WRITER_ENABLED is false"}, indent=2))
        return 0

    session_factory = _load_session_factory()
    queue_db = None
    timescale_db = None
    try:
        queue_db = session_factory()
        timescale_db = session_factory()
        stats = _run_writer_once(
            queue_db,
            timescale_db,
            _load_neo4j_driver(),
            settings=settings,
            worker_id=args.worker_id,
            lease_ttl_seconds=args.lease_ttl_seconds,
            writer_partitions=_partitions(args.writer_partitions),
        )
    finally:
        if queue_db is not None:
            queue_db.close()
        if timescale_db is not None:
            timescale_db.close()

    print(json.dumps({"enabled": True, "worker_id": args.worker_id, "stats": stats}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
