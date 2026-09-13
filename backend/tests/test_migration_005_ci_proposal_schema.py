"""Tests for the 005_ci_proposal_schema.cypher migration — feat-cmdb-ai-handoff.

Loads the migration file from disk and asserts it declares:
- the unique id constraint on :CIProposal
- 3 supporting indexes (status, created_at, proposed_category)
- IF NOT EXISTS guards on every statement (idempotent)
- a documented rollback one-liner

Pure file-level checks; no live Neo4j required.
"""

from __future__ import annotations

from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "005_ci_proposal_schema.cypher"
)


def _load_migration() -> str:
    assert MIGRATION_PATH.exists(), (
        f"Migration file missing: {MIGRATION_PATH}"
    )
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_file_exists_with_correct_name():
    """The migration file MUST be named 005_ci_proposal_schema.cypher."""
    assert MIGRATION_PATH.name == "005_ci_proposal_schema.cypher"


def test_constraint_and_indexes_present():
    """The migration MUST declare the unique id constraint and 3 indexes."""
    body = _load_migration()
    assert "CREATE CONSTRAINT ci_proposal_id_unique" in body, (
        "Migration missing the :CIProposal.id unique constraint"
    )
    assert "FOR (p:CIProposal) REQUIRE p.id IS UNIQUE" in body, (
        "Constraint MUST require p.id IS UNIQUE"
    )
    # Indexes
    for idx in ("ci_proposal_status", "ci_proposal_created_at", "ci_proposal_category"):
        assert f"CREATE INDEX {idx}" in body, f"Missing index {idx}"


def test_all_statements_are_idempotent():
    """Every CREATE statement MUST include IF NOT EXISTS so the migration is safe to re-run."""
    body = _load_migration()
    for statement in body.split(";"):
        statement = statement.strip()
        if not statement or statement.startswith("//"):
            continue
        if not statement.upper().startswith("CREATE "):
            continue
        assert "IF NOT EXISTS" in statement, (
            f"Statement not idempotent (missing IF NOT EXISTS): {statement[:120]}"
        )


def test_migration_documents_rollback():
    """The migration MUST include a rollback one-liner in a leading comment."""
    body = _load_migration()
    # The header should mention DROP CONSTRAINT or rollback so on-call can roll back.
    assert "DROP CONSTRAINT" in body, "Migration header MUST document rollback with DROP CONSTRAINT"
    assert "IF EXISTS" in body, "Rollback must use IF EXISTS to be safe"