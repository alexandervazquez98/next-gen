"""Static analysis tests for migration  - WU1 foundation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATION_FILE = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "itsm_service_catalog.cypher"
)


def _read_migration() -> str:
    if not MIGRATION_FILE.exists():
        return ""
    return MIGRATION_FILE.read_text(encoding="utf-8")


class TestItsmCatalogMigrationFile:
    """Validate migration presence and required directives."""

    def test_migration_file_exists(self):
        assert MIGRATION_FILE.exists(), (
            f"Migration file not found at {MIGRATION_FILE}. "
            "Task 1.7 requires backend/migrations/itsm_service_catalog.cypher."
        )

    def test_migration_file_is_non_empty(self):
        if not MIGRATION_FILE.exists():
            pytest.skip("Migration file does not exist yet (pre-implementation).")
        content = _read_migration()
        assert content.strip(), "Migration file is empty."

    def test_migration_file_has_header_comment(self):
        if not MIGRATION_FILE.exists():
            pytest.skip("Migration file does not exist yet (pre-implementation).")
        content = _read_migration()
        assert "//" in content[:250] or "/*" in content[:250], (
            "Migration file should start with comments describing intent."
        )

    def test_service_catalog_unique_constraint_present(self):
        if not MIGRATION_FILE.exists():
            pytest.skip("Migration file does not exist yet (pre-implementation).")
        content = _read_migration()
        assert re.search(
            r"CREATE\s+CONSTRAINT\s+service_catalog_service_id\b",
            content,
            re.IGNORECASE,
        ), "Missing CREATE CONSTRAINT service_catalog_service_id."
        assert re.search(
            r"CREATE\s+CONSTRAINT\s+service_catalog_service_id\b.*?FOR\s*\(\s*sc\s*:\s*ServiceCatalog\b",
            content,
            re.IGNORECASE | re.DOTALL,
        ), "service_catalog_service_id must target :ServiceCatalog node."

    def test_ticket_folio_unique_constraint_present(self):
        if not MIGRATION_FILE.exists():
            pytest.skip("Migration file does not exist yet (pre-implementation).")
        content = _read_migration()
        assert re.search(
            r"CREATE\s+CONSTRAINT\s+ticket_folio_ticket_id\b",
            content,
            re.IGNORECASE,
        ), "Missing CREATE CONSTRAINT ticket_folio_ticket_id."
        assert re.search(
            r"CREATE\s+CONSTRAINT\s+ticket_folio_ticket_id\b.*?FOR\s*\(\s*tf\s*:\s*TicketFolio\b",
            content,
            re.IGNORECASE | re.DOTALL,
        ), "ticket_folio_ticket_id must target :TicketFolio node."

    def test_required_indexes_exist(self):
        if not MIGRATION_FILE.exists():
            pytest.skip("Migration file does not exist yet (pre-implementation).")
        content = _read_migration()
        assert re.search(
            r"CREATE\s+INDEX\s+service_catalog_active\b",
            content,
            re.IGNORECASE,
        ), "Missing index service_catalog_active."
        assert re.search(
            r"CREATE\s+INDEX\s+ticket_folio_status\b",
            content,
            re.IGNORECASE,
        ), "Missing index ticket_folio_status."
        assert re.search(
            r"CREATE\s+INDEX\s+ticket_folio_service_catalog_id\b",
            content,
            re.IGNORECASE,
        ), "Missing index ticket_folio_service_catalog_id."

    def test_idempotency_keywords_are_present(self):
        if not MIGRATION_FILE.exists():
            pytest.skip("Migration file does not exist yet (pre-implementation).")
        content = _read_migration().upper().replace("\n", " ")
        assert "IF NOT EXISTS" in content, "Migration statements must be idempotent."

    def test_file_documents_backfill_and_compatibility(self):
        if not MIGRATION_FILE.exists():
            pytest.skip("Migration file does not exist yet (pre-implementation).")
        content = _read_migration().lower()
        assert (
            "legacy" in content and "service_id" in content
        ), "Backfill/legacy compatibility should be documented for legacy ServiceCatalog IDs."
        assert (
            "backfill" in content or "coalesce" in content
        ), "Backfill logic must be documented explicitly."
        assert (
            "event snapshot" in content or "event" not in content or "snapshot" in content
        ), "Compatibility notes should include that event snapshots are not mutated."
