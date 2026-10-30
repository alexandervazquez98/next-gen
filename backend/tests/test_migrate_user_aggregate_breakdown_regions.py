"""Regression for the PostgreSQL column migration that replaced migration 007.

``backend/migrations/007_user_aggregate_breakdown_regions.cypher`` used to sit
in the Neo4j migration corpus, so the Neo4j runner received PostgreSQL DDL
(``Invalid input 'TABLE': expected``) and the column was never applied to
existing databases (``column "aggregate_breakdown_regions" does not exist``).
The DDL now lives in ``backend/scripts/migrate_user_aggregate_breakdown_regions.py``.
"""

from __future__ import annotations


class FakeConnection:
    def __init__(self):
        self.executed: list[str] = []

    def execute(self, statement, params=None):
        self.executed.append(str(statement))
        return []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeEngine:
    def __init__(self):
        self.conn = FakeConnection()

    def begin(self):
        return self.conn


def test_migration_adds_the_column_with_an_idempotent_statement():
    """The column is added with ``IF NOT EXISTS`` so re-runs are no-ops."""
    from scripts import migrate_user_aggregate_breakdown_regions as migration

    engine = FakeEngine()
    migration.ensure_aggregate_breakdown_regions_column(engine)

    assert len(engine.conn.executed) == 1
    sql = engine.conn.executed[0]
    assert "ALTER TABLE users" in sql
    assert "ADD COLUMN IF NOT EXISTS aggregate_breakdown_regions" in sql
    assert "TEXT[]" in sql
    assert "DEFAULT ARRAY[]::TEXT[]" in sql


def test_migration_is_safe_to_run_twice():
    """Running the migration twice issues the same idempotent statement."""
    from scripts import migrate_user_aggregate_breakdown_regions as migration

    engine = FakeEngine()
    migration.ensure_aggregate_breakdown_regions_column(engine)
    migration.ensure_aggregate_breakdown_regions_column(engine)

    assert engine.conn.executed == [engine.conn.executed[0]] * 2
    assert "IF NOT EXISTS" in engine.conn.executed[0]
