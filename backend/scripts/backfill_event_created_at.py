"""One-shot idempotent backfill for ``Event.created_at IS NULL``.

Part of PR #1 for fix-423 (``fix-423-recovered-event-accumulation``). The streaming
bulk prune cursor (``services/event_service.py:event_batch_pruner``) cannot
paginate past NULL ``created_at`` rows — production has 70%+ legacy NULL rows
from before issue #279 wired ``created_at`` into every CREATE block. This script
fills those rows with ``COALESCE(recovered_at, last_seen, closed_at, datetime())``
in bounded batches with a short sleep between batches so it can run during a
low-traffic window without taking a long lock on the ``Event`` label.

The script is intentionally DB-only and read-mostly:

* It MUST NOT change runtime Event write semantics.
* It MUST be idempotent — running it twice is safe and the second run is a no-op.

Usage:
    python backend/scripts/backfill_event_created_at.py --dry-run
    python backend/scripts/backfill_event_created_at.py --batch-size 500 --sleep-seconds 0.5

Live evidence (run before/after on production Neo4j):

    MATCH (e:Event) WHERE e.created_at IS NULL RETURN count(e) AS candidate_count;
    MATCH (e:Event) WHERE e.created_at IS NULL
        RETURN e.id, e.recovered_at, e.last_seen, e.closed_at, e.created_at
        LIMIT 5;
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Allow running this script directly from the repository root or from inside
# backend/scripts without requiring PYTHONPATH manipulation by callers.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cypher statements
# ---------------------------------------------------------------------------
#
# The bounded UPDATE pulls at most ``batch_size`` legacy rows per batch via
# ``WITH e LIMIT $batch_size`` and falls back through every plausible
# timestamp field before falling back to ``datetime()`` so rows with NO
# recovery / closure history still receive a sensible ``created_at``.
#
# The filter is scoped to ``created_at IS NULL`` so re-runs are a no-op: once
# every row has a ``created_at`` the subquery returns zero rows and the loop
# exits cleanly.

COUNT_NULL_CYPHER = "MATCH (e:Event) WHERE e.created_at IS NULL RETURN count(e) AS candidate_count"

UPDATE_BACKFILL_CYPHER = (
    "MATCH (e:Event) WHERE e.created_at IS NULL "
    "WITH e LIMIT $batch_size "
    "SET e.created_at = COALESCE(e.recovered_at, e.last_seen, e.closed_at, datetime()) "
    "RETURN e.id AS updated_id"
)


def backfill_event_created_at(
    session,
    *,
    batch_size: int = 500,
    sleep_seconds: float = 0.1,
    dry_run: bool = False,
) -> dict:
    """Backfill NULL ``Event.created_at`` rows in bounded batches.

    Iterates bounded UPDATE batches (default 500 rows) with ``sleep_seconds`` of
    pause between batches. Returns a summary dict with keys:

    * ``dry_run`` (bool) — whether the run was a no-op probe.
    * ``candidates`` (int) — count of NULL ``created_at`` rows seen in this run
      (sum of every batch's UPDATE rowcount).
    * ``updated`` (int) — number of rows whose ``created_at`` was actually
      mutated (== ``candidates`` for live runs, always ``0`` for dry-run).

    The function is idempotent: once no NULL rows remain the loop exits
    cleanly and returns ``{"updated": 0, ...}`` on subsequent calls.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if sleep_seconds < 0:
        raise ValueError("sleep_seconds must be non-negative")

    if dry_run:
        result = session.run(COUNT_NULL_CYPHER).single()
        candidates = (result or {}).get("candidate_count", 0) if result else 0
        logger.info(
            "backfill_event_created_at dry-run: %d candidate rows (no mutations)",
            candidates,
        )
        return {"dry_run": True, "candidates": candidates, "updated": 0}

    updated = 0
    while True:
        result = session.run(UPDATE_BACKFILL_CYPHER, batch_size=batch_size)
        rows = list(result)
        rowcount = len(rows)
        if rowcount == 0:
            break
        updated += rowcount
        if sleep_seconds:
            time.sleep(sleep_seconds)

    logger.info("backfill_event_created_at updated %d rows", updated)
    return {"dry_run": False, "candidates": updated, "updated": updated}


def _build_arg_parser() -> argparse.ArgumentParser:
    description = (
        "Bounded deployment-time backfill for Event.created_at IS NULL rows. "
        "Idempotent: re-runs are no-ops once every row has a created_at."
    )
    epilog = (
        "Live evidence (run before/after the backfill on production Neo4j):\n"
        "  MATCH (e:Event) WHERE e.created_at IS NULL "
        "RETURN count(e) AS candidate_count;\n"
        "  MATCH (e:Event) WHERE e.created_at IS NULL "
        "RETURN e.id, e.recovered_at, e.last_seen, e.closed_at, e.created_at LIMIT 5;\n"
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
        default=500,
        help="Maximum number of rows updated per batch (default: 500).",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.1,
        help="Sleep seconds between batches (default: 0.1).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count candidate rows without mutating anything.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    # Lazy import so ``python backend/scripts/backfill_event_created_at.py --help``
    # works on hosts that do not have the neo4j driver installed.
    from database import get_db

    driver = get_db()
    with driver.session() as session:
        report = backfill_event_created_at(
            session,
            batch_size=args.batch_size,
            sleep_seconds=args.sleep_seconds,
            dry_run=args.dry_run,
        )

    print(
        f"backfill_event_created_at: dry_run={report['dry_run']} "
        f"candidates={report['candidates']} updated={report['updated']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
