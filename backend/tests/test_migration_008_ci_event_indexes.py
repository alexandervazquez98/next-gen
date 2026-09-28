"""Tests for the 008_ci_event_indexes.cypher migration — feat-523-ci-event-neo4j-indexes.

Loads the migration file from disk and asserts it declares:
- unique id constraint on :CI.id   (turns MERGE full-scan into index seek)
- unique id constraint on :Event.id  (primary detail lookup)
- supporting indexes on Event.ci_id, Event.metric_id, CI.status
- IF NOT EXISTS guards on every statement (idempotent)
- a documented rollback one-liner

Pure file-level checks; no live Neo4j required.
"""

from __future__ import annotations

from pathlib import Path

MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migrations" / "008_ci_event_indexes.cypher"


def _load_migration() -> str:
    assert MIGRATION_PATH.exists(), f"Migration file missing: {MIGRATION_PATH}"
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_file_exists_with_correct_name():
    """The migration file MUST be named 008_ci_event_indexes.cypher."""
    assert MIGRATION_PATH.name == "008_ci_event_indexes.cypher"


def test_constraint_and_indexes_present():
    """The migration MUST declare the :CI.id and :Event.id uniqueness constraints plus supporting indexes."""
    body = _load_migration()
    # Uniqueness constraints
    assert "ci_id_unique" in body, "Migration missing the :CI.id unique constraint (ci_id_unique)"
    assert (
        "FOR (c:CI) REQUIRE c.id IS UNIQUE" in body
    ), "Constraint MUST require c.id IS UNIQUE on :CI"
    assert (
        "event_id_unique" in body
    ), "Migration missing the :Event.id unique constraint (event_id_unique)"
    assert (
        "FOR (e:Event) REQUIRE e.id IS UNIQUE" in body
    ), "Constraint MUST require e.id IS UNIQUE on :Event"
    # Supporting indexes (query-verified properties)
    assert (
        "event_ci_id" in body
    ), "Migration missing index event_ci_id on Event.ci_id (event_writer dedup)"
    assert (
        "event_metric_id" in body
    ), "Migration missing index event_metric_id on Event.metric_id (event_writer dedup)"
    assert (
        "ci_status" in body
    ), "Migration missing index ci_status on CI.status (analytics_worker CRITICAL filter)"


def test_all_statements_are_idempotent():
    """Every CREATE statement MUST include IF NOT EXISTS so the migration is safe to re-run."""
    body = _load_migration()
    for statement in body.split(";"):
        statement = statement.strip()
        if not statement or statement.startswith("//"):
            continue
        if not statement.upper().startswith("CREATE "):
            continue
        assert (
            "IF NOT EXISTS" in statement
        ), f"Statement not idempotent (missing IF NOT EXISTS): {statement[:120]}"


def test_migration_documents_rollback():
    """The migration MUST include a rollback one-liner in a leading comment."""
    body = _load_migration()
    # The header should mention DROP CONSTRAINT so on-call can roll back.
    assert "DROP CONSTRAINT" in body, "Migration header MUST document rollback with DROP CONSTRAINT"
    assert "IF EXISTS" in body, "Rollback must use IF EXISTS to be safe"
