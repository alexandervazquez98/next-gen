"""Startup preflight checks and migration application for ITSM domain bootstrap.

The ITSM domain keeps existing `ServiceCatalog` and `TicketFolio` nodes in Neo4j.
Before enabling the new `service_id` identity constraints we run a startup
preflight with a **fail-fast policy**:

- Duplicate canonical identity values are rejected.
- Legacy identity rows that are missing/empty or conflicting are rejected.

The startup flow fails with `ItsmBootstrapPreflightError` when any blocker is
found, because auto-resolving legacy identity collisions could corrupt future
migrations and API operations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from database import get_db

ITSM_SERVICE_ID_POLICY = "fail-fast: resolve identity conflicts before startup"
logger = logging.getLogger(__name__)

_BACKFILL_COMPATIBILITY_QUERY = """
MATCH (sc:ServiceCatalog)
SET
  sc.service_id = coalesce(sc.service_id, sc.id),
  sc.id = coalesce(sc.id, sc.service_id),
  sc.name = coalesce(sc.name, sc.category, sc.id, sc.service_id),
  sc.tier = coalesce(sc.tier, sc.service_tier),
  sc.service_tier = coalesce(sc.service_tier, sc.tier),
  sc.sla_target_minutes = coalesce(sc.sla_target_minutes, sc.sla_minutes, 0),
  sc.sla_minutes = coalesce(sc.sla_minutes, sc.sla_target_minutes, 0),
  sc.active = coalesce(sc.active, true)
RETURN count(sc) AS backfilled
"""

_PRECHECK_DUPLICATE_CANONICAL_ID_QUERY = """
MATCH (sc:ServiceCatalog)
WITH trim(toString(coalesce(sc.service_id, sc.id))) AS canonical_id
WHERE canonical_id IS NOT NULL AND canonical_id <> ''
WITH canonical_id, count(*) AS total
WHERE total > 1
RETURN canonical_id, total
"""

_PRECHECK_INVALID_IDENTITY_QUERY = """
MATCH (sc:ServiceCatalog)
WITH
  trim(toString(coalesce(sc.service_id, sc.id))) AS canonical_id,
  sc.service_id AS service_id,
  sc.id AS legacy_id,
  trim(toString(sc.service_id)) AS service_id_norm,
  trim(toString(sc.id)) AS legacy_id_norm
WHERE
  (canonical_id IS NULL OR canonical_id = '')
  OR (service_id_norm IS NOT NULL AND service_id_norm <> ''
      AND legacy_id_norm IS NOT NULL AND legacy_id_norm <> ''
      AND service_id_norm <> legacy_id_norm)
RETURN canonical_id, service_id, legacy_id
"""


class ItsmBootstrapPreflightError(RuntimeError):
    """Raised when ITSM startup checks detect identity blockers."""


@dataclass
class ItsmPreflightReport:
    """Structured report produced by ITSM preflight checks."""

    duplicate_catalog_ids: list[str]
    invalid_catalog_nodes: list[str]


def _row_value(record: Any, key: str) -> Any:
    if hasattr(record, "get"):
        return record.get(key)
    return record[key]


def _consume_rows(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    if hasattr(result, "data") and callable(result.data):
        return list(result.data())
    return [dict(r) for r in result]


def _migration_file_path() -> Path:
    """Return absolute path for the ITSM startup migration script."""

    return Path(__file__).resolve().parent.parent / "migrations" / "itsm_service_catalog.cypher"


def _extract_cypher_statements(content: str) -> list[str]:
    """Split migration text into executable statements and skip comment-only lines."""

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


def _load_service_catalog_migration_statements() -> list[str]:
    """Load migration statements from the backend migrations folder."""

    migration_path = _migration_file_path()
    if not migration_path.exists():
        return []
    raw = migration_path.read_text(encoding="utf-8")
    return _extract_cypher_statements(raw)


def run_service_catalog_compatibility_backfill(driver: Any | None = None) -> None:
    """Normalize legacy ServiceCatalog identity aliases before strict checks."""

    drv = driver if driver is not None else get_db()
    with drv.session() as session:
        session.run(_BACKFILL_COMPATIBILITY_QUERY)


def run_service_catalog_preflight(driver: Any | None = None) -> ItsmPreflightReport:
    """Run duplicate/identity checks before applying ITSM constraints.

    Raises:
        ItsmBootstrapPreflightError: when duplicate canonical IDs or invalid legacy
            identity data are found.
    """

    drv = driver if driver is not None else get_db()
    with drv.session() as session:
        duplicate_rows = _consume_rows(session.run(_PRECHECK_DUPLICATE_CANONICAL_ID_QUERY))
        duplicate_ids = [
            str(_row_value(row, "canonical_id"))
            for row in duplicate_rows
            if _row_value(row, "canonical_id")
        ]

        invalid_rows = _consume_rows(session.run(_PRECHECK_INVALID_IDENTITY_QUERY))
        invalid_ids = [
            str(_row_value(row, "canonical_id"))
            for row in invalid_rows
            if _row_value(row, "canonical_id")
        ]

    if duplicate_ids or invalid_ids:
        message = (
            "ITSM catalog preflight failed: "
            f"policy='{ITSM_SERVICE_ID_POLICY}', "
            f"duplicate_canonical_ids={duplicate_ids}, "
            f"invalid_catalog_ids={invalid_ids}"
        )
        raise ItsmBootstrapPreflightError(message)

    return ItsmPreflightReport(duplicate_catalog_ids=[], invalid_catalog_nodes=[])


def run_service_catalog_migration(
    driver: Any | None = None, *, statements: list[str] | None = None
) -> int:
    """Apply ITSM migration statements in order.

    Returns:
        Number of statements executed.
    """

    executable_statements = (
        statements if statements is not None else _load_service_catalog_migration_statements()
    )
    if not executable_statements:
        return 0

    drv = driver if driver is not None else get_db()
    with drv.session() as session:
        for statement in executable_statements:
            session.run(statement)

    return len(executable_statements)


def run_service_catalog_startup_checks(
    driver: Any | None = None, *, apply_migration: bool = True
) -> ItsmPreflightReport | None:
    """Run startup checks without blocking API availability on operational failures.

    Identity-integrity conflicts remain explicit fail-fast blockers; transient
    backfill, preflight, and idempotent migration failures are logged instead.
    """

    try:
        run_service_catalog_compatibility_backfill(driver=driver)
        report = run_service_catalog_preflight(driver=driver)
    except ItsmBootstrapPreflightError:
        raise
    except Exception:
        logger.exception("ITSM service catalog startup checks failed; continuing API startup")
        return None

    if apply_migration:
        try:
            run_service_catalog_migration(driver=driver)
        except Exception:
            logger.exception("ITSM service catalog migration failed; continuing API startup")
    return report


def validate_service_catalog_preflight(driver: Any | None = None) -> None:
    """Public validation entrypoint used by startup wiring and unit tests."""

    run_service_catalog_preflight(driver=driver)
