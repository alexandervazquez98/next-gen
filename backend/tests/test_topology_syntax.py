"""Syntax validation tests for topology_repo Cypher queries.

These tests ensure that dynamic query construction doesn't produce
invalid Cypher syntax (e.g., dangling ANDs or duplicate WHEREs).
"""

import pytest
from repositories import topology_repo
from models.user import User

@pytest.fixture
def mock_admin_user():
    return User(
        username="admin",
        role="ADMIN",
        permissions=[],
        allowed_locations=[]
    )

@pytest.fixture
def mock_operator_user():
    return User(
        username="operator",
        role="OPERATOR",
        permissions=["CI_VIEW"],
        allowed_locations=["HQ-Madrid"]
    )

class TestTopologyQuerySyntax:
    """Validates the structure of generated Cypher queries."""

    def test_get_filtered_graph_data_no_filters_syntax(self, mock_neo4j_session, mock_admin_user):
        """Should produce clean syntax when no filters are applied."""
        topology_repo.get_filtered_graph_data(is_admin=True)
        
        # Capture generated queries
        queries = [q["query"] for q in mock_neo4j_session.queries]
        
        # Check links query (the one that failed)
        links_query = next(q for q in queries if "r]->(b:CI)" in q)
        
        # Basic syntax assertions
        assert "AND  RETURN" not in links_query, "Dangling AND found before RETURN"
        assert "WHERE  AND" not in links_query, "Dangling AND found after empty WHERE"
        assert links_query.count("WHERE") <= 1, "Duplicate WHERE clause found"
        
        # Exact expected structure for no-filter admin
        assert links_query.strip() == "MATCH (a:CI)-[r]->(b:CI) RETURN a, r, b"

    def test_get_filtered_graph_data_with_filters_syntax(self, mock_neo4j_session, mock_admin_user):
        """Should produce valid AND-joined filters for both nodes."""
        topology_repo.get_filtered_graph_data(layer="router", location="HQ-Madrid", is_admin=True)
        
        queries = [q["query"] for q in mock_neo4j_session.queries]
        links_query = next(q for q in queries if "r]->(b:CI)" in q)
        
        assert "WHERE" in links_query
        assert "a.layer = $layer" in links_query
        assert "b.layer = $layer" in links_query
        assert "a.location_name = $location" in links_query
        assert "b.location_name = $location" in links_query
        assert "AND" in links_query
        
        # Should not have duplicate WHERE
        assert links_query.count("WHERE") == 1
        # Should have correctly joined ANDs (4 conditions total: a.layer, a.loc, b.layer, b.loc -> 3 ANDs)
        assert links_query.count(" AND ") == 3

    def test_get_filtered_graph_data_operator_scoping_syntax(self, mock_neo4j_session, mock_operator_user):
        """Should include location scoping filters for non-admin users."""
        topology_repo.get_filtered_graph_data(
            allowed_locations=["HQ-Madrid"], 
            is_admin=False
        )
        
        queries = [q["query"] for q in mock_neo4j_session.queries]
        links_query = next(q for q in queries if "r]->(b:CI)" in q)
        
        assert "WHERE" in links_query
        assert "a.location_name IN $allowed_locations" in links_query
        assert "b.location_name IN $allowed_locations" in links_query
        assert links_query.count("WHERE") == 1
        assert "AND" in links_query
