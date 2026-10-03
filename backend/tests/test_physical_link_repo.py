"""Repository tests for :PhysicalLink — feat-444-physical-link-styling (slice 2).

Slice 2 of the PhysicalLink visualization chain (#444) layers a CRUD API on top
of the metadata model that shipped in slice 1 (#323). This file covers the
``PhysicalLinkRepo`` boundary against the same Neo4j ``:PhysicalLink`` label
created by migration 009.

Mirrors the optimistic-version precedent at
``backend/repositories/cmdb_proposal_repo.py`` — every Cypher statement is
parameterized via ``$params`` (no f-string interpolation of user input).

The conftest ``mock_neo4j_driver`` fixture wires ``database.get_db()`` to a
``MockNeo4jDriver`` so all queries are captured, never executed live.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


@pytest.fixture
def repo(mock_neo4j_driver):
    """A PhysicalLinkRepo wired to the mocked Neo4j driver."""
    from repositories.physical_link_repo import PhysicalLinkRepo

    return PhysicalLinkRepo(driver=mock_neo4j_driver)


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _link_row(
    link_id: str = "pl-fiber-001",
    link_type: str = "fiber",
    endpoint_a: str = "ci-router-a",
    endpoint_b: str = "ci-router-b",
    status: str = "UNKNOWN",
    capacity_gbps: float | None = 10.0,
    install_date: str | None = "2024-01-15",
) -> dict:
    return {
        "id": link_id,
        "type": link_type,
        "endpoints": [endpoint_a, endpoint_b],
        "status": status,
        "capacity_gbps": capacity_gbps,
        "install_date": install_date,
    }


# ---------------------------------------------------------------------------
# T-R1: create()
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_returns_persisted_record(self, mock_neo4j_driver, repo):
        """create() MUST return the row Neo4j RETURNed."""
        mock_neo4j_driver.mock_session.set_response(
            "create (pl:physicallink",
            [_link_row(link_id="pl-fiber-001")],
        )
        row = repo.create(
            link_id="pl-fiber-001",
            link_type="fiber",
            endpoints=("ci-router-a", "ci-router-b"),
            status="UNKNOWN",
            capacity_gbps=10.0,
            install_date="2024-01-15",
        )
        assert row["id"] == "pl-fiber-001"
        assert row["type"] == "fiber"
        # endpoints MUST be a list[str] on the wire, not the Python tuple.
        assert row["endpoints"] == ["ci-router-a", "ci-router-b"]
        assert row["status"] == "UNKNOWN"
        assert row["capacity_gbps"] == 10.0

    def test_create_uses_parameterized_cypher(self, mock_neo4j_driver, repo):
        """create() MUST pass user-supplied data via $params, NOT f-string interpolation."""
        mock_neo4j_driver.mock_session.set_response("create (pl:physicallink", [_link_row()])
        repo.create(
            link_id="pl-fiber-001",
            link_type="fiber",
            endpoints=("ci-router-a", "ci-router-b"),
            status="UNKNOWN",
            capacity_gbps=None,
            install_date=None,
        )
        cypher_call = next(
            c
            for c in mock_neo4j_driver.mock_session.queries
            if "create (pl:physicallink" in c["query"].lower()
        )
        # Hardening: every user-controlled field MUST be a $param, not interpolated.
        for param_name in ("link_id", "link_type", "endpoint_a", "endpoint_b", "status"):
            assert (
                param_name in cypher_call["params"]
            ), f"create() MUST pass {param_name} via $params; f-string leak risk"
        assert cypher_call["params"]["link_id"] == "pl-fiber-001"
        assert cypher_call["params"]["link_type"] == "fiber"


# ---------------------------------------------------------------------------
# T-R2: get_by_id()
# ---------------------------------------------------------------------------


class TestGetById:
    def test_get_by_id_returns_none_when_missing(self, mock_neo4j_driver, repo):
        """get_by_id() MUST return None when no row matches."""
        mock_neo4j_driver.mock_session.set_default_response([])
        assert repo.get_by_id("missing") is None

    def test_get_by_id_returns_row_when_present(self, mock_neo4j_driver, repo):
        """get_by_id() MUST return the row when present."""
        mock_neo4j_driver.mock_session.set_response(
            "match (pl:physicallink)",
            [_link_row(link_id="pl-fiber-007")],
        )
        row = repo.get_by_id("pl-fiber-007")
        assert row is not None
        assert row["id"] == "pl-fiber-007"


# ---------------------------------------------------------------------------
# T-R3: list() — with and without filters
# ---------------------------------------------------------------------------


class TestList:
    def test_list_all_returns_every_row(self, mock_neo4j_driver, repo):
        """list() with no filters MUST return every PhysicalLink row."""
        mock_neo4j_driver.mock_session.set_default_response(
            [_link_row(link_id="a"), _link_row(link_id="b"), _link_row(link_id="c")]
        )
        rows = repo.list()
        assert len(rows) == 3
        assert {r["id"] for r in rows} == {"a", "b", "c"}

    def test_list_filter_by_ci_id(self, mock_neo4j_driver, repo):
        """list(ci_id=...) MUST pass ci_id via $params and return only matching rows."""
        mock_neo4j_driver.mock_session.set_default_response(
            [_link_row(link_id="pl-x", endpoint_a="ci-target")]
        )
        rows = repo.list(ci_id="ci-target")
        assert len(rows) == 1
        # Ensure ci_id was passed as a parameter, never interpolated.
        list_queries = [
            q
            for q in mock_neo4j_driver.mock_session.queries
            if "match (pl:physicallink)" in q["query"].lower()
            and "create" not in q["query"].lower()
        ]
        assert any(
            q["params"].get("ci_id") == "ci-target" for q in list_queries
        ), "list() MUST apply ci_id filter via $params"

    def test_list_filter_by_type(self, mock_neo4j_driver, repo):
        """list(type=...) MUST pass type via $params and return only matching rows."""
        mock_neo4j_driver.mock_session.set_default_response(
            [_link_row(link_id="pl-x", link_type="fiber")]
        )
        rows = repo.list(link_type="fiber")
        assert all(r["type"] == "fiber" for r in rows)
        list_queries = [
            q
            for q in mock_neo4j_driver.mock_session.queries
            if "match (pl:physicallink)" in q["query"].lower()
            and "create" not in q["query"].lower()
        ]
        assert any(
            q["params"].get("link_type") == "fiber" for q in list_queries
        ), "list() MUST apply type filter via $params"

    def test_list_filter_by_status(self, mock_neo4j_driver, repo):
        """list(status=...) MUST pass status via $params and return only matching rows."""
        mock_neo4j_driver.mock_session.set_default_response(
            [_link_row(link_id="pl-x", status="UP")]
        )
        rows = repo.list(status="UP")
        assert all(r["status"] == "UP" for r in rows)
        list_queries = [
            q
            for q in mock_neo4j_driver.mock_session.queries
            if "match (pl:physicallink)" in q["query"].lower()
            and "create" not in q["query"].lower()
        ]
        assert any(
            q["params"].get("status") == "UP" for q in list_queries
        ), "list() MUST apply status filter via $params"

    def test_list_applies_pagination(self, mock_neo4j_driver, repo):
        """list(limit, offset) MUST apply skip/limit via $params."""
        mock_neo4j_driver.mock_session.set_default_response([])
        repo.list(limit=25, offset=50)
        list_queries = [
            q
            for q in mock_neo4j_driver.mock_session.queries
            if "match (pl:physicallink)" in q["query"].lower()
            and "create" not in q["query"].lower()
        ]
        assert any(
            q["params"].get("limit") == 25 and q["params"].get("offset") == 50 for q in list_queries
        ), "list() MUST apply pagination via $params (skip/limit)"


# ---------------------------------------------------------------------------
# T-R4: update_status()
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    def test_update_status_returns_updated_row(self, mock_neo4j_driver, repo):
        """update_status() MUST return the row with the new status."""
        mock_neo4j_driver.mock_session.set_response(
            "match (pl:physicallink",
            [_link_row(link_id="pl-fiber-001", status="UP")],
        )
        row = repo.update_status("pl-fiber-001", "UP")
        assert row is not None
        assert row["status"] == "UP"
        assert row["id"] == "pl-fiber-001"

    def test_update_status_returns_none_when_missing(self, mock_neo4j_driver, repo):
        """update_status() MUST return None when the id is unknown."""
        mock_neo4j_driver.mock_session.set_default_response([])
        assert repo.update_status("missing", "UP") is None
