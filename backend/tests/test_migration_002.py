"""Static analysis tests for migration 002_generic_device_schema.cypher.

Per user decision Q7, we do NOT use testcontainers or live Neo4j for migration
verification in unit tests. These tests read the .cypher file as plain text and
verify it contains the expected constraints and indexes via regex matches.

For ops-time verification (production rollouts), the migration is also written
to be idempotent (IF NOT EXISTS) so re-running it is safe.

The 5 expected artifacts (per design \u00a73):
- CONSTRAINT device_id_unique   (Device.id unique)
- CONSTRAINT metric_id_unique   (Metric.id unique)
- INDEX     device_source_topic  (Device.source_topic)
- INDEX     device_parser_name   (Device.parser_name)
- INDEX     metric_device_name   (Metric.device_id, Metric.name)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Repository path: backend/tests/test_migration_002.py
# Migration path: backend/migrations/002_generic_device_schema.cypher
MIGRATION_FILE = (
    Path(__file__).resolve().parent.parent / "migrations" / "002_generic_device_schema.cypher"
)


def _read_migration() -> str:
    """Read the migration file as plain text.

    Returns an empty string if the file does not yet exist \u2014 some test
    assertions are then expected to fail (TDD red-phase behavior).
    """
    if not MIGRATION_FILE.exists():
        return ""
    return MIGRATION_FILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Migration file presence
# ---------------------------------------------------------------------------


class TestMigrationFilePresence:
    """The migration file must exist and be a non-empty text file."""

    def test_migration_file_exists(self):
        assert MIGRATION_FILE.exists(), (
            f"Migration file not found at {MIGRATION_FILE}. "
            "Task 3a.1 requires backend/migrations/002_generic_device_schema.cypher."
        )

    def test_migration_file_is_non_empty(self):
        if not MIGRATION_FILE.exists():
            pytest.skip("Migration file does not exist yet (pre-implementation).")
        content = _read_migration()
        assert content.strip(), "Migration file is empty."

    def test_migration_file_ends_with_newline(self):
        if not MIGRATION_FILE.exists():
            pytest.skip("Migration file does not exist yet (pre-implementation).")
        content = _read_migration()
        assert content.endswith("\n"), "Migration file should end with a trailing newline."


# ---------------------------------------------------------------------------
# Constraint declarations
# ---------------------------------------------------------------------------


class TestConstraints:
    """Verify the two unique constraints on Device and Metric labels."""

    def test_device_id_unique_constraint_present(self):
        content = _read_migration()
        assert content, "Migration file is missing or empty."
        # Match CREATE CONSTRAINT device_id_unique (case-insensitive)
        pattern = re.compile(
            r"CREATE\s+CONSTRAINT\s+device_id_unique\b",
            re.IGNORECASE,
        )
        assert pattern.search(content), (
            "Expected CREATE CONSTRAINT device_id_unique not found in migration file."
        )

    def test_metric_id_unique_constraint_present(self):
        content = _read_migration()
        assert content, "Migration file is missing or empty."
        pattern = re.compile(
            r"CREATE\s+CONSTRAINT\s+metric_id_unique\b",
            re.IGNORECASE,
        )
        assert pattern.search(content), (
            "Expected CREATE CONSTRAINT metric_id_unique not found in migration file."
        )

    def test_device_constraint_targets_device_label(self):
        content = _read_migration()
        assert content, "Migration file is missing or empty."
        # Find the device_id_unique constraint block and verify it targets :Device
        pattern = re.compile(
            r"CREATE\s+CONSTRAINT\s+device_id_unique.*?FOR\s*\(\s*d\s*:\s*Device\s*\)",
            re.IGNORECASE | re.DOTALL,
        )
        assert pattern.search(content), "device_id_unique constraint must target (d:Device)."

    def test_metric_constraint_targets_metric_label(self):
        content = _read_migration()
        assert content, "Migration file is missing or empty."
        pattern = re.compile(
            r"CREATE\s+CONSTRAINT\s+metric_id_unique.*?FOR\s*\(\s*m\s*:\s*Metric\s*\)",
            re.IGNORECASE | re.DOTALL,
        )
        assert pattern.search(content), "metric_id_unique constraint must target (m:Metric)."


# ---------------------------------------------------------------------------
# Index declarations
# ---------------------------------------------------------------------------


class TestIndexes:
    """Verify the three lookup indexes for Device and Metric."""

    def test_device_source_topic_index_present(self):
        content = _read_migration()
        assert content, "Migration file is missing or empty."
        pattern = re.compile(
            r"CREATE\s+INDEX\s+device_source_topic\b",
            re.IGNORECASE,
        )
        assert pattern.search(content), (
            "Expected CREATE INDEX device_source_topic not found in migration file."
        )

    def test_device_parser_name_index_present(self):
        content = _read_migration()
        assert content, "Migration file is missing or empty."
        pattern = re.compile(
            r"CREATE\s+INDEX\s+device_parser_name\b",
            re.IGNORECASE,
        )
        assert pattern.search(content), (
            "Expected CREATE INDEX device_parser_name not found in migration file."
        )

    def test_metric_device_name_index_present(self):
        content = _read_migration()
        assert content, "Migration file is missing or empty."
        pattern = re.compile(
            r"CREATE\s+INDEX\s+metric_device_name\b",
            re.IGNORECASE,
        )
        assert pattern.search(content), (
            "Expected CREATE INDEX metric_device_name not found in migration file."
        )

    def test_metric_device_name_index_is_composite(self):
        """Index on Metric must cover both (device_id, name) for the upsert path."""
        content = _read_migration()
        assert content, "Migration file is missing or empty."
        # Look for the metric_device_name block and check it lists both columns.
        # Cypher syntax: "FOR (m:Metric) ON (m.device_id, m.name)"
        pattern = re.compile(
            r"CREATE\s+INDEX\s+metric_device_name\b.*?FOR\s*\(\s*m\s*:\s*Metric\s*\)\s*ON\s*\(\s*m\.device_id\s*,\s*m\.name\s*\)",
            re.IGNORECASE | re.DOTALL,
        )
        assert pattern.search(content), (
            "metric_device_name index must be composite on (m.device_id, m.name)."
        )


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """All CREATE statements must use IF NOT EXISTS so re-running is a no-op."""

    def test_all_constraints_use_if_not_exists(self):
        content = _read_migration()
        assert content, "Migration file is missing or empty."
        # Find every CREATE CONSTRAINT line and verify IF NOT EXISTS appears
        # on the same logical statement (allow whitespace/newlines between).
        constraint_pattern = re.compile(
            r"CREATE\s+CONSTRAINT\s+(\w+)\s+(.*?);",
            re.IGNORECASE | re.DOTALL,
        )
        for match in constraint_pattern.finditer(content):
            stmt_body = match.group(0)
            assert "IF NOT EXISTS" in stmt_body.upper().replace("\n", " "), (
                f"Constraint '{match.group(1)}' must use IF NOT EXISTS for idempotency."
            )

    def test_all_indexes_use_if_not_exists(self):
        content = _read_migration()
        assert content, "Migration file is missing or empty."
        index_pattern = re.compile(
            r"CREATE\s+INDEX\s+(\w+)\s+(.*?);",
            re.IGNORECASE | re.DOTALL,
        )
        for match in index_pattern.finditer(content):
            stmt_body = match.group(0)
            assert "IF NOT EXISTS" in stmt_body.upper().replace("\n", " "), (
                f"Index '{match.group(1)}' must use IF NOT EXISTS for idempotency."
            )


# ---------------------------------------------------------------------------
# Documentation expectations
# ---------------------------------------------------------------------------


class TestDocumentation:
    """The migration file should document its purpose and intended use."""

    def test_migration_has_header_comment(self):
        content = _read_migration()
        assert content, "Migration file is missing or empty."
        # Look for any // or /* comment near the top (within first 200 chars).
        head = content[:200]
        assert "//" in head or "/*" in head, (
            "Migration file should start with a comment explaining its purpose."
        )

    def test_migration_mentions_additive_or_no_modify(self):
        """The migration must NOT modify existing RTU/Sensor nodes (additive only)."""
        content = _read_migration()
        assert content, "Migration file is missing or empty."
        lower = content.lower()
        # Look for any wording that explicitly says it's additive / doesn't modify existing nodes
        signals = (
            "additive",
            "does not modify",
            "do not modify",
            "not modified",
            "existing rtu/sensor",
        )
        assert any(s in lower for s in signals), (
            "Migration file should document that it does NOT modify existing "
            "RTU/Sensor nodes (additive migration)."
        )
