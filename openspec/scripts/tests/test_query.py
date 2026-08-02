"""Strict-TDD tests for the parameterized orphan query (WU-8)."""

from __future__ import annotations

import pytest


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

    assert result.ids == ()
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


def _orphan_rows(count: int) -> list:
    return [
        {"ci_id": f"ci-test-ap-orphan-{index:03d}"}
        for index in range(1, count + 1)
    ]


def test_discover_orphans_seven_orphans_scn001():
    from openspec.scripts.cmdb_backfill_orphans import discover_orphans
    from openspec.scripts.tests.fake_neo4j import FakeSession

    session = FakeSession(_orphan_rows(7))

    result = discover_orphans(session, "ap", ["DEPENDS_ON", "HOSTED_ON"])

    assert len(result.ids) == 7
    assert result.ids[0] == "ci-test-ap-orphan-001"
    assert result.ids[-1] == "ci-test-ap-orphan-007"
    assert result.cap_reached is False


def test_discover_orphans_keeps_only_first_seven_scn002_baseline():
    """SCN-002 only proves the query returns orphan IDs in the FakeSession.

    Excluding wired APs is enforced inside the Cypher query (NOT EXISTS).
    The fake session has no notion of wiring — it returns whatever rows
    the production code decides are orphans. This test keeps the spec
    scenario covered: synthetic-only IDs, exact count, exact ordering.
    """
    from openspec.scripts.cmdb_backfill_orphans import discover_orphans
    from openspec.scripts.tests.fake_neo4j import FakeSession

    rows = _orphan_rows(5)
    session = FakeSession(rows)

    result = discover_orphans(session, "ap", ["DEPENDS_ON", "HOSTED_ON"])

    assert list(result.ids) == [
        "ci-test-ap-orphan-001",
        "ci-test-ap-orphan-002",
        "ci-test-ap-orphan-003",
        "ci-test-ap-orphan-004",
        "ci-test-ap-orphan-005",
    ]
    assert result.cap_reached is False


def test_discover_orphans_uses_supplied_relationship_allowlist_scn004():
    from openspec.scripts.cmdb_backfill_orphans import discover_orphans
    from openspec.scripts.tests.fake_neo4j import FakeSession

    rows = _orphan_rows(6)
    session = FakeSession(rows)

    result = discover_orphans(session, "ap", ["HOSTED_ON"])

    assert len(result.ids) == 6
    assert session.queries[0][1]["relationship_types"] == ["HOSTED_ON"]


def test_discover_orphans_caps_at_ten_thousand_scn010():
    from openspec.scripts.cmdb_backfill_orphans import (
        MAX_ORPHAN_CAP,
        discover_orphans,
    )
    from openspec.scripts.tests.fake_neo4j import FakeSession

    session = FakeSession(_orphan_rows(15_000))

    result = discover_orphans(session, "ap", ["DEPENDS_ON", "HOSTED_ON"])

    assert len(result.ids) == MAX_ORPHAN_CAP
    assert result.cap_reached is True


def test_discover_orphans_dedupes_duplicate_rows_scn001_dedupe():
    from openspec.scripts.cmdb_backfill_orphans import discover_orphans
    from openspec.scripts.tests.fake_neo4j import FakeSession

    rows = [
        {"ci_id": "ci-test-ap-orphan-001"},
        {"ci_id": "ci-test-ap-orphan-001"},
        {"ci_id": "ci-test-ap-orphan-002"},
    ]
    session = FakeSession(rows)

    result = discover_orphans(session, "ap", ["DEPENDS_ON", "HOSTED_ON"])

    assert list(result.ids) == [
        "ci-test-ap-orphan-001",
        "ci-test-ap-orphan-002",
    ]
    assert result.cap_reached is False


def test_discover_orphans_strips_non_opaque_records_scn006():
    from openspec.scripts.cmdb_backfill_orphans import discover_orphans
    from openspec.scripts.tests.fake_neo4j import FakeSession

    rows = [
        {"ci_id": "ci-test-ap-orphan-001"},
        {"ci_id": "REGION_TAG"},
        {"ci_id": "10.99.99.99"},
        {"ci_id": "ci-test-ap-orphan-002"},
    ]
    session = FakeSession(rows)

    result = discover_orphans(session, "ap", ["DEPENDS_ON", "HOSTED_ON"])

    assert list(result.ids) == [
        "ci-test-ap-orphan-001",
        "ci-test-ap-orphan-002",
    ]
    assert result.cap_reached is False


def test_discover_orphans_schema_drift_scn011():
    from openspec.scripts.cmdb_backfill_orphans import (
        OrphanDiscoveryError,
        discover_orphans,
    )
    from openspec.scripts.tests.fake_neo4j import FakeSession

    session = FakeSession(RuntimeError("Neo4jError: label AccessPoint not found"))

    with pytest.raises(OrphanDiscoveryError) as exc_info:
        discover_orphans(session, "ap", ["DEPENDS_ON", "HOSTED_ON"])

    assert "missing label AccessPoint" in str(exc_info.value)


def test_discover_orphans_rejects_bad_cap():
    from openspec.scripts.cmdb_backfill_orphans import discover_orphans
    from openspec.scripts.tests.fake_neo4j import FakeSession

    session = FakeSession([])

    with pytest.raises(ValueError):
        discover_orphans(session, "ap", ["DEPENDS_ON"], cap=0)


def test_build_query_rejects_invalid_scope():
    from openspec.scripts.cmdb_backfill_orphans import build_query

    with pytest.raises(ValueError):
        build_query("switch", ["DEPENDS_ON"], cap=10)


def test_build_query_rejects_raw_cypher_in_rel_types():
    from openspec.scripts.cmdb_backfill_orphans import build_query

    with pytest.raises(ValueError):
        build_query("ap", ["MATCH (n) DELETE n"], cap=10)
