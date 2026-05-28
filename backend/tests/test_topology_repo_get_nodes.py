"""Repository query contract tests for topology_repo.get_nodes."""

from repositories import topology_repo


_COORDINATE_PREDICATES = (
    "n.location IS NOT NULL",
    "n.location.latitude IS NOT NULL",
    "n.location.longitude IS NOT NULL",
)


def _assert_no_coordinate_predicates(query: str) -> None:
    for predicate in _COORDINATE_PREDICATES:
        assert predicate not in query


def test_get_nodes_admin_does_not_require_point_location(mock_neo4j_driver):
    """Admin inventory listing should not filter out CIs without coordinates."""
    mock_neo4j_driver.mock_session.set_default_response(
        [{"n": {"id": "ci-unlocated"}, "category": "router", "metrics": []}]
    )

    rows = topology_repo.get_nodes(allowed_locations=[], is_admin=True)

    assert rows == [
        {"node": {"id": "ci-unlocated"}, "category": "router", "metrics": []}
    ]
    query_call = mock_neo4j_driver.mock_session.queries[-1]
    query = query_call["query"]
    assert "MATCH (n:CI)" in query
    assert "n.location_name IN $allowed_locations" not in query
    _assert_no_coordinate_predicates(query)


def test_get_nodes_non_admin_scopes_by_location_name_without_point_filter(
    mock_neo4j_driver,
):
    """Scoped inventory should use location_name without requiring coordinates."""
    mock_neo4j_driver.mock_session.set_default_response(
        [{"n": {"id": "ci-site-a"}, "category": "switch", "metrics": []}]
    )

    rows = topology_repo.get_nodes(["Site A"], is_admin=False)

    assert rows == [
        {"node": {"id": "ci-site-a"}, "category": "switch", "metrics": []}
    ]
    query_call = mock_neo4j_driver.mock_session.queries[-1]
    query = query_call["query"]
    assert "n.location_name IN $allowed_locations" in query
    assert query_call["params"] == {"allowed_locations": ["Site A"]}
    _assert_no_coordinate_predicates(query)


def test_get_nodes_non_admin_no_allowed_locations_returns_empty_without_query(
    mock_neo4j_driver,
):
    """Non-admin users without allowed locations should not query inventory."""
    rows = topology_repo.get_nodes([], is_admin=False)

    assert rows == []
    assert mock_neo4j_driver.mock_session.queries == []


def test_get_filtered_graph_data_keeps_point_location_filter(mock_neo4j_driver):
    """Map/topology graph data should remain restricted to geolocated CIs."""
    mock_neo4j_driver.mock_session.set_default_response([])

    topology_repo.get_filtered_graph_data(is_admin=True)

    node_query = mock_neo4j_driver.mock_session.queries[0]["query"]
    for predicate in _COORDINATE_PREDICATES:
        assert predicate in node_query
