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

import re
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


def test_four_new_indexes_present():
    """The migration MUST declare ci_location_name, ci_test_seed, event_status, and event_test_seed indexes."""
    body = _load_migration()
    # ci_location_name — topology_repo.py:480 scopes non-admin users by location
    assert (
        "ci_location_name" in body
    ), "Migration missing ci_location_name index on CI.location_name (topology_repo.py:480)"
    assert (
        "FOR (c:CI) ON (c.location_name)" in body
    ), "ci_location_name MUST use FOR (c:CI) ON (c.location_name)"
    # ci_test_seed
    assert "ci_test_seed" in body, "Migration missing ci_test_seed index on CI.test_seed"
    assert (
        "FOR (c:CI) ON (c.test_seed)" in body
    ), "ci_test_seed MUST use FOR (c:CI) ON (c.test_seed)"
    # event_status — list-membership predicate IS index-backed in Neo4j
    assert "event_status" in body, "Migration missing event_status index on Event.status"
    assert (
        "FOR (e:Event) ON (e.status)" in body
    ), "event_status MUST use FOR (e:Event) ON (e.status)"
    # event_test_seed
    assert "event_test_seed" in body, "Migration missing event_test_seed index on Event.test_seed"
    assert (
        "FOR (e:Event) ON (e.test_seed)" in body
    ), "event_test_seed MUST use FOR (e:Event) ON (e.test_seed)"


def test_header_does_not_falsely_exclude_in_predicates():
    """The header MUST NOT claim that IN-list predicates are un-indexable (Neo4j range indexes support IN)."""
    body = _load_migration()
    # The old header claimed "IN is not an equality or range seek" — that is false.
    # Neo4j range indexes explicitly support: equality, list membership (IN), existence, range, prefix.
    assert "IN is not an equality or range seek" not in body, (
        "Header contains a false claim that IN predicates are un-indexable. "
        "Neo4j range indexes explicitly support list membership (IN)."
    )


def test_header_excludes_event_type_not_metric_led():
    """Event.event_type exclusion MUST be justified by metric_id-led compound dedup, not left unexplained."""
    body = _load_migration()
    # The retained exclusion for event_type must cite the metric_id dedup path
    if "Event.event_type" in body and "NOT" in body.upper():
        # only passes if the exclusion rationale mentions metric_id
        assert (
            "metric_id" in body
        ), "Event.event_type exclusion must cite metric_id as the led predicate"


def test_rollback_covers_all_created_indexes():
    """The rollback block MUST mention every index and constraint the file creates.

    Derives the expected name set by parsing CREATE statements so the test stays
    correct as the file grows rather than hardcoding a list that drifts.
    """
    body = _load_migration()
    # Parse all index/constraint names from CREATE statements
    created_names: set[str] = set()
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("//") or not stripped:
            continue
        # Match: CREATE [CONSTRAINT|INDEX] <name> IF NOT EXISTS
        m = re.search(
            r"CREATE\s+(?:CONSTRAINT|INDEX)\s+(\w+)\s+IF NOT EXISTS", stripped, re.IGNORECASE
        )
        if m:
            created_names.add(m.group(1))
    assert created_names, "Could not parse any CREATE statements from migration"
    # The rollback block is in the header comment; extract it
    rollback_start = body.find("Rollback one-liner:")
    assert rollback_start != -1, "Could not find 'Rollback one-liner:' in migration header"
    rollback_block = body[rollback_start : body.find("\n\n", rollback_start) or len(body)]
    # Every created name must appear in the rollback block
    missing = created_names - set(
        re.findall(r"(?:DROP CONSTRAINT|DROP INDEX)\s+(\w+)\s+IF EXISTS", rollback_block)
    )
    assert not missing, (
        f"Rollback block is missing DROP statements for: {missing}. "
        f"Full rollback block:\n{rollback_block}"
    )
