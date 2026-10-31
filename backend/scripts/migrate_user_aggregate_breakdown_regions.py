"""Add the ``users.aggregate_breakdown_regions`` column to existing databases.

Why this exists
---------------
``Base.metadata.create_all(bind=engine)`` (see ``backend/main.py``) only
creates missing *tables*, never missing *columns*. Databases created before
#391 PR1 therefore lack this column while the ``User`` model declares it, and
every ORM read of ``User`` fails with::

    column "aggregate_breakdown_regions" does not exist

The statement used to live in
``backend/migrations/007_user_aggregate_breakdown_regions.cypher``, inside the
Neo4j migration corpus. The Neo4j runner received PostgreSQL DDL and aborted
with ``Invalid input 'TABLE': expected`` (see issue #552), so the column was
never applied anywhere. It is applied from the deploy flow instead.

Run from the repository root with::

    python backend/scripts/migrate_user_aggregate_breakdown_regions.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow direct script execution: ``python scripts/migrate_user_aggregate_breakdown_regions.py``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ADD_COLUMN_SQL = (
    "ALTER TABLE users "
    "ADD COLUMN IF NOT EXISTS aggregate_breakdown_regions TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]"
)


def ensure_aggregate_breakdown_regions_column(engine) -> None:
    """Add the column when it is missing. Idempotent and safe to re-run."""
    with engine.begin() as conn:
        conn.execute(text(ADD_COLUMN_SQL))
    logger.info("users.aggregate_breakdown_regions is present.")


def main() -> int:
    from postgres_db import engine

    logger.info("Starting User.aggregate_breakdown_regions column migration...")
    ensure_aggregate_breakdown_regions_column(engine)
    logger.info("User.aggregate_breakdown_regions column migration complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
