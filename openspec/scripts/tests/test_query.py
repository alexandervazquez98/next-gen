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


def test_compute_query_hash_is_deterministic_and_differentiates_params():
    from openspec.scripts.cmdb_backfill_orphans import compute_query_hash

    query = "MATCH (n) RETURN n"
    base_params = {"relationship_types": ["DEPENDS_ON"], "cap": 100}
    assert (
        compute_query_hash(query, base_params)
        == compute_query_hash(query, base_params)
    )

    other_params = {"relationship_types": ["DEPENDS_ON"], "cap": 200}
    assert compute_query_hash(query, base_params) != compute_query_hash(
        query, other_params
    )


def test_compute_query_hash_is_16_hex_chars():
    from openspec.scripts.cmdb_backfill_orphans import compute_query_hash

    digest = compute_query_hash(
        "MATCH (n) RETURN n", {"relationship_types": ["DEPENDS_ON"], "cap": 1}
    )

    assert len(digest) == 16
    assert all(character in "0123456789abcdef" for character in digest)


def test_fake_session_run_records_query_and_returns_records():
    from openspec.scripts.tests.fake_neo4j import (
        FakeRecord,
        FakeResult,
        FakeSession,
    )

    session = FakeSession([{"ci_id": "ci-test-ap-orphan-001"}])
    result = session.run("MATCH (n) RETURN n", cap=5)

    assert isinstance(result, FakeResult)
    assert session.queries == [("MATCH (n) RETURN n", {"cap": 5})]

    records = list(result)
    assert len(records) == 1
    assert isinstance(records[0], FakeRecord)
    assert records[0]["ci_id"] == "ci-test-ap-orphan-001"
    assert records[0].get("missing") is None


def test_discover_orphans_with_empty_session_returns_empty_list():
    from openspec.scripts.cmdb_backfill_orphans import discover_orphans
    from openspec.scripts.tests.fake_neo4j import FakeSession

    session = FakeSession([])

    result = discover_orphans(
        session,
        scope="ap",
        rel_types=["DEPENDS_ON", "HOSTED_ON"],
        cap=10_000,
    )

    assert result.ids == []
    assert result.cap_reached is False
    assert session.queries == [
        (
            "MATCH (n:CI:AccessPoint)\n"
            "WHERE NOT EXISTS {\n"
            "  MATCH (n)-[r]->(m:CI)\n"
            "  WHERE type(r) IN $relationship_types\n"
            "}\n"
            "RETURN n.id AS ci_id\n"
            "LIMIT $cap",
            {
                "relationship_types": ["DEPENDS_ON", "HOSTED_ON"],
                "cap": 10_000,
            },
        )
    ]
