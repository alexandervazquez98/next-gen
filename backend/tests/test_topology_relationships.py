import asyncio
from unittest.mock import patch

from repositories import topology_repo
from models.user import User
from routers.links import CiIdsPayload, get_cis_relationships
from services import link_service


def test_create_link_rejects_legacy_connected_to(mock_neo4j_driver):
    try:
        topology_repo.create_link("ci-a", "ci-b", "CONNECTED_TO")
    except ValueError:
        return
    raise AssertionError("legacy CONNECTED_TO relationship was accepted")


def test_create_link_accepts_connects_to(mock_neo4j_driver):
    topology_repo.create_link("ci-a", "ci-b", "CONNECTS_TO")

    query = mock_neo4j_driver.mock_session.queries[-1]["query"]
    assert "MERGE (a)-[r:CONNECTS_TO]->(b)" in query


def test_get_links_query_includes_hosted_on(mock_neo4j_driver):
    mock_neo4j_driver.mock_session.set_default_response([])

    topology_repo.get_links(allowed_locations=[], is_admin=True)

    query = mock_neo4j_driver.mock_session.queries[-1]["query"]
    assert "HOSTED_ON" in query
    assert "CONNECTS_TO" in query
    assert "DEPENDS_ON" in query
    assert "CONNECTED_TO" not in query


def test_cis_relationships_route_uses_scoped_service_path():
    async def run_route():
        user = User(
            username="operator",
            role="OPERATOR",
            permissions=["CI_VIEW"],
            allowed_locations=["HQ-Madrid"],
        )
        with patch("routers.links.link_service.get_cis_relationships", return_value={"ci-a": {}}) as mock_service:
            result = await get_cis_relationships(CiIdsPayload(ci_ids=["ci-a"]), user)
        return result, mock_service

    result, mock_service = asyncio.run(run_route())
    assert result == {"ci-a": {}}
    mock_service.assert_called_once()
    assert mock_service.call_args.args[0] == ["ci-a"]
    assert mock_service.call_args.args[1].allowed_locations == ["HQ-Madrid"]


def test_cis_relationship_summary_applies_non_admin_location_scope(mock_neo4j_driver):
    mock_neo4j_driver.mock_session.set_default_response([])
    user = User(
        username="operator",
        role="OPERATOR",
        permissions=["CI_VIEW"],
        allowed_locations=["HQ-Madrid"],
    )

    link_service.get_cis_relationships(["ci-a", "ci-b"], user)

    query_call = mock_neo4j_driver.mock_session.queries[-1]
    assert "a.id IN $ci_ids AND a.location_name IN $allowed_locations" in query_call["query"]
    assert "b.id IN $ci_ids AND b.location_name IN $allowed_locations" in query_call["query"]
    assert query_call["params"]["allowed_locations"] == ["HQ-Madrid"]


def test_cis_relationship_summary_does_not_populate_disallowed_requested_ci(mock_neo4j_driver):
    mock_neo4j_driver.mock_session.set_default_response([
        {
            "source_id": "allowed-ci",
            "source_label": "Allowed CI",
            "source_location": "HQ-Madrid",
            "target_id": "blocked-ci",
            "target_label": "Blocked CI",
            "target_location": "Secret",
            "rel_type": "CONNECTS_TO",
        }
    ])
    user = User(
        username="operator",
        role="OPERATOR",
        permissions=["CI_VIEW"],
        allowed_locations=["HQ-Madrid"],
    )

    summary = link_service.get_cis_relationships(["allowed-ci", "blocked-ci"], user)

    assert summary["allowed-ci"]["asSource"] == [
        {"otherId": "blocked-ci", "otherLabel": "Blocked CI", "type": "CONNECTS_TO"}
    ]
    assert summary["blocked-ci"] == {"asSource": [], "asTarget": []}


def test_cis_relationship_summary_returns_empty_scoped_summary_without_locations(mock_neo4j_driver):
    user = User(
        username="operator",
        role="OPERATOR",
        permissions=["CI_VIEW"],
        allowed_locations=[],
    )

    summary = link_service.get_cis_relationships(["ci-a"], user)

    assert summary == {"ci-a": {"asSource": [], "asTarget": []}}
    assert mock_neo4j_driver.mock_session.queries == []
