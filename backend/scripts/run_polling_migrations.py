"""Operator command for applying polling PostgreSQL migrations.

This script is intentionally explicit: polling queue DDL is never applied on
application startup. Operators run this command during the staged rollout before
enabling `POLLING_PG_QUEUE_ENABLED=true`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from polling.migrations import POLLING_MIGRATIONS


def _load_engine():
    from postgres_db import engine

    return engine


def _run_pending_migrations(engine) -> list[str]:
    from polling.migrations import run_pending_migrations

    return run_pending_migrations(engine)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply explicit PostgreSQL migrations for the polling pipeline.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print known polling migration versions without connecting to PostgreSQL.",
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        print(json.dumps({"dry_run": True, "migrations": [m.version for m in POLLING_MIGRATIONS]}, indent=2))
        return 0

    applied = _run_pending_migrations(_load_engine())
    print(json.dumps({"dry_run": False, "applied": applied, "applied_count": len(applied)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
