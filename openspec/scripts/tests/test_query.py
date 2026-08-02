"""Strict-TDD tests for the parameterized orphan query (WU-8)."""

from __future__ import annotations


def test_build_query_uses_not_exists_and_parameterized_allowlist():
    from openspec.scripts.cmdb_backfill_orphans import build_query

    query, params = build_query(
        scope="ap",
        rel_types=["DEPENDS_ON", "HOSTED_ON"],
        cap=10_000,
    )

    assert "MATCH (n:CI:AccessPoint)" in query
    assert "WHERE NOT EXISTS" in query
    assert "MATCH (n)-[r]->(m:CI)" in query
    assert "type(r) IN $relationship_types" in query
    assert "RETURN n.id AS ci_id" in query
    assert "LIMIT $cap" in query
    assert params == {
        "relationship_types": ["DEPENDS_ON", "HOSTED_ON"],
        "cap": 10_000,
    }


def test_build_query_accepts_custom_cap_without_interpolating_relationships():
    from openspec.scripts.cmdb_backfill_orphans import build_query

    query, params = build_query("ap", ["MANAGES"], cap=3)

    assert "MANAGES" not in query
    assert params == {"relationship_types": ["MANAGES"], "cap": 3}
