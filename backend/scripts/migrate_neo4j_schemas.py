"""DRY wrapper: apply every ``backend/migrations/*.cypher`` except 008.

008 is skipped because its duplicate-ID preflight lives in
``migrate_ci_event_indexes.py`` (which ``safe-rebuild.sh`` invokes
explicitly right after this wrapper). Exit codes: 0 = success/no-op,
2 = statement error.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow direct script execution: ``python scripts/migrate_neo4j_schemas.py``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_db
from scripts._apply_cypher import CypherStatementError, apply_cypher_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_MIGRATIONS_DIR: Path = Path(__file__).resolve().parent.parent / "migrations"
_SKIP_MIGRATIONS: frozenset[str] = frozenset({"008_ci_event_indexes.cypher"})


def _iter_migration_files() -> list[Path]:
    return sorted(p for p in _MIGRATIONS_DIR.glob("*.cypher") if p.name not in _SKIP_MIGRATIONS)


def main() -> int:
    files = _iter_migration_files()
    if not files:
        logger.info("No migration files found in %s — nothing to do.", _MIGRATIONS_DIR)
        return 0
    logger.info(
        "Starting schema migration wrapper (%d file(s), 008 excluded): %s",
        len(files),
        ", ".join(p.name for p in files),
    )
    drv = get_db()
    for path in files:
        logger.info("Applying %s", path.name)
        try:
            apply_cypher_file(drv, path, log=logger)
        except CypherStatementError as exc:
            for err in exc.errors:
                logger.error("  [%d] %s — %s", err.index, err.statement[:80], err.exception)
            logger.error(
                "Migration aborted at %s. Earlier migrations are already committed. "
                "Fix the error and re-run; idempotent statements will be no-ops.",
                path.name,
            )
            return 2
    logger.info("All schema migrations applied successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
