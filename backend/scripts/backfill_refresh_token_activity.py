"""Batched deployment-time backfill for ``refresh_tokens.last_activity_at IS NULL``.

Part of PR0 (DB-only) for fix #287 / `fix-287-session-keep-alive`. The legacy
schema declared the column NOT NULL but historical deployments may have rows
inserted before the column existed or before the runtime started populating it.
This script fills those rows with ``now()`` in bounded batches with a short
sleep between batches so that operators can run it during a low-traffic window
without taking a long lock on the ``refresh_tokens`` table.

The script is intentionally DB-only: it MUST NOT change login, refresh, logout,
audit, or frontend runtime behavior. It also MUST be idempotent — running it
twice is safe and the second run is a no-op.

Usage:
    python backend/scripts/backfill_refresh_token_activity.py
    python backend/scripts/backfill_refresh_token_activity.py --batch-size 500 --sleep-seconds 0.05

Live evidence (run before/after on production PostgreSQL):
    SELECT count(*) FROM refresh_tokens WHERE last_activity_at IS NULL;
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

# Allow running this script directly from the repository root or from inside
# backend/scripts without requiring PYTHONPATH manipulation by callers.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# Raw SQL keeps this script free of ORM model imports so `python ... --help`
# works on hosts that do not have psycopg2 / the backend models importable.
# The bounded subquery keeps each UPDATE under ``batch_size`` rows so the lock
# window stays short even when many legacy rows exist.
BACKFILL_SQL = text(
    """
    UPDATE refresh_tokens
    SET last_activity_at = NOW()
    WHERE id IN (
        SELECT id FROM refresh_tokens
        WHERE last_activity_at IS NULL
        LIMIT :batch_size
    )
    """
)


def backfill_refresh_token_activity(
    db: "Session",
    *,
    batch_size: int = 1000,
    sleep_seconds: float = 0.1,
) -> int:
    """Update legacy ``refresh_tokens`` rows where ``last_activity_at IS NULL``.

    Iterates bounded UPDATE batches (default 1000 rows) with ``sleep_seconds``
    of pause between batches. Returns the total number of rows updated. The
    function is idempotent: once no NULL rows remain the loop exits cleanly
    and returns ``0`` on subsequent calls.

    Uses raw SQL with ``NOW()`` so the timestamp comes from the database clock
    and avoids any app-server / Postgres clock-skew risk.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if sleep_seconds < 0:
        raise ValueError("sleep_seconds must be non-negative")

    total = 0

    while True:
        result = db.execute(BACKFILL_SQL, {"batch_size": batch_size})
        rowcount = result.rowcount or 0
        if rowcount == 0:
            break
        total += rowcount
        # Commit each batch so the lock is released between iterations and so
        # that a partial run still leaves a consistent partial state.
        db.commit()
        if sleep_seconds:
            time.sleep(sleep_seconds)

    logger.info("Refresh-token activity backfill updated %d rows", total)
    return total


def _build_arg_parser() -> argparse.ArgumentParser:
    description = (
        "Batched deployment-time backfill for "
        "refresh_tokens.last_activity_at IS NULL rows."
    )
    epilog = (
        "Live evidence (run before/after the backfill):\n"
        "  SELECT count(*) FROM refresh_tokens WHERE last_activity_at IS NULL;\n"
        "  SELECT id, user_id, last_activity_at FROM refresh_tokens "
        "WHERE last_activity_at IS NULL;\n"
        "Both queries must return zero rows once the backfill completes."
    )
    parser = argparse.ArgumentParser(
        description=description,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Maximum number of rows updated per batch (default: 1000).",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.1,
        help="Sleep seconds between batches (default: 0.1).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    # Lazy import so unit tests that import the module do not pull in the
    # postgres_db engine (which connects on import).
    from postgres_db import SessionLocal

    db = SessionLocal()
    try:
        updated = backfill_refresh_token_activity(
            db,
            batch_size=args.batch_size,
            sleep_seconds=args.sleep_seconds,
        )
    finally:
        db.close()

    print(f"backfill_refresh_token_activity updated {updated} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())