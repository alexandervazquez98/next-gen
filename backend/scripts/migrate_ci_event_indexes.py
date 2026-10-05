"""Idempotently apply 008_ci_event_indexes.cypher: CI/Event uniqueness constraints and supporting indexes.

Run from the repository root INSIDE the backend container:
    docker compose exec -T backend python scripts/migrate_ci_event_indexes.py

Exit codes:
    0 — all statements applied (or already present)
    1 — preflight failure (duplicate IDs detected; nothing applied)
    2 — statement execution error (see stderr for details)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

# Add backend to path for direct script execution.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_db
from scripts._apply_cypher import (
    _split_statements as _extract_cypher_statements,  # noqa: F401  backward-compat alias for tests
    apply_cypher_file,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Module-level so tests can monkeypatch the location without touching the
# filesystem under ``backend/migrations/``. ``safe-rebuild.sh`` always uses
# the real directory; tests substitute a tmp_path.
_MIGRATIONS_DIR: Path = Path(__file__).resolve().parent.parent / "migrations"
_MIGRATION_FILE = "008_ci_event_indexes.cypher"

# Preflight queries — run before applying anything.
# If either returns rows, the migration will abort and nothing is applied.
_PREFLIGHT_CI_DUPLICATES = """
MATCH (c:CI)
WITH c.id AS id, count(*) AS n
WHERE n > 1
RETURN id, n
LIMIT 20
"""

_PREFLIGHT_EVENT_DUPLICATES = """
MATCH (e:Event)
WITH e.id AS id, count(*) AS n
WHERE n > 1
RETURN id, n
LIMIT 20
"""


def _migration_file_path() -> Path:
    """Return absolute path for the CI/Event indexes migration script."""
    return _MIGRATIONS_DIR / _MIGRATION_FILE


def _run_preflight(driver: Any) -> None:
    """Run duplicate-ID preflight checks. Raises SystemExit(1) if duplicates are found."""
    logger.info("Running preflight duplicate-ID checks ...")
    with driver.session() as session:
        ci_dups = list(session.run(_PREFLIGHT_CI_DUPLICATES))
        if ci_dups:
            logger.error(
                "PREFLIGHT FAILED: %d duplicate :CI.id values found. " "Sample: %s",
                len(ci_dups),
                [dict(r) for r in ci_dups],
            )
            logger.error(
                "Resolve duplicate IDs before applying the migration. "
                "Migration ABORTED — nothing applied."
            )
            sys.exit(1)

        event_dups = list(session.run(_PREFLIGHT_EVENT_DUPLICATES))
        if event_dups:
            logger.error(
                "PREFLIGHT FAILED: %d duplicate :Event.id values found. " "Sample: %s",
                len(event_dups),
                [dict(r) for r in event_dups],
            )
            logger.error(
                "Resolve duplicate IDs before applying the migration. "
                "Migration ABORTED — nothing applied."
            )
            sys.exit(1)

    logger.info("Preflight passed — no duplicate IDs detected.")


def apply_ci_event_indexes(driver: Any | None = None) -> None:
    """Apply the CI/Event index migration to Neo4j.

    Idempotent: every statement uses IF NOT EXISTS so re-runs are safe.
    Performs a preflight duplicate-ID check before applying anything.

    Args:
        driver: Neo4j driver instance. Defaults to the app's get_db() driver.

    Raises:
        SystemExit(1): preflight failure — duplicate IDs detected, nothing applied.
        SystemExit(2): statement execution error.
    """
    drv = driver if driver is not None else get_db()

    _run_preflight(drv)

    migration_path = _migration_file_path()
    if not migration_path.exists():
        logger.error("Migration file not found: %s", migration_path)
        sys.exit(2)

    try:
        apply_cypher_file(drv, migration_path, log=logger)
    except Exception:  # noqa: BLE001
        # The utility already logs the failing statement and exception.
        # Re-raise as SystemExit(2) to preserve the public exit-code contract.
        sys.exit(2)

    logger.info("Migration %s applied successfully.", _MIGRATION_FILE)


def main() -> int:
    """CLI entry point."""
    logger.info("Starting migration: %s", _MIGRATION_FILE)
    try:
        apply_ci_event_indexes()
        return 0
    except SystemExit as exc:
        return exc.code if exc.code is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
