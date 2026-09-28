"""Idempotently apply 008_ci_event_indexes.cypher: CI/Event uniqueness constraints and supporting indexes.

Run from the repository root with:
    python backend/scripts/migrate_ci_event_indexes.py

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

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
    return Path(__file__).resolve().parent.parent / "migrations" / _MIGRATION_FILE


def _extract_cypher_statements(content: str) -> list[str]:
    """Split migration text into executable statements, skipping comment-only lines."""
    statements: list[str] = []
    for raw_statement in content.split(";"):
        lines = [line.strip() for line in raw_statement.splitlines() if line.strip()]
        query_lines = [
            line for line in lines if not line.lstrip().startswith("//") and line != "--"
        ]
        normalized = " ".join(query_lines).strip()
        if not normalized:
            continue
        statements.append(normalized)
    return statements


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

    raw = migration_path.read_text(encoding="utf-8")
    statements = _extract_cypher_statements(raw)
    logger.info("Loaded %d statement(s) from %s", len(statements), _MIGRATION_FILE)

    with drv.session() as session:
        for i, stmt in enumerate(statements, start=1):
            try:
                session.run(stmt)
                logger.info("  [%d/%d] OK: %s", i, len(statements), stmt[:80])
            except Exception as exc:  # noqa: BLE001
                logger.error("  [%d/%d] FAILED: %s", i, len(statements), stmt[:80])
                logger.error(
                    "  Statement error from Neo4j driver: %s",
                    exc,
                )
                logger.error(
                    "  Migration aborted. Fix the error above and re-run. "
                    "Statements already committed cannot be rolled back by this script."
                )
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
