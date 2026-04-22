"""Syntax validation tests for Mass Relationship Editor (CRUD).

Ensures that bulk Create, Update, and Delete operations produce 
valid Cypher queries and handle filters correctly.
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

class TestTopologyMassSyntax:
    """Validates the structure of bulk Cypher queries."""

    def test_execute_mass_links_create_syntax(self, mock_neo4j_session, mock_admin_user):
        """Should produce a Cartesian MERGE for bulk creation."""
        source_filter = {"layer": "Router"}
        target_filter = {"location": "HQ"}
        
        topology_repo.execute_mass_links(
            source_filter, target_filter, 
            relationship="DEPENDS_ON", 
            is_admin=True
        )
        
        query = mock_neo4j_session.queries[-1]["query"]
        
        assert "MERGE (a)-[r:DEPENDS_ON]->(b)" in query
        assert "a.layer = $a_layer" in query
        assert "b.location_name = $b_location" in query
        assert query.count("MATCH") == 2
        assert "WHERE a.id <> b.id" in query

    def test_execute_mass_delete_syntax(self, mock_neo4j_session, mock_admin_user):
        """Should produce a bulk MATCH and DELETE."""
        source_filter = {"layer": "Switch"}
        target_filter = {"layer": "Server"}
        
        topology_repo.execute_mass_delete(
            source_filter, target_filter, 
            relationship="CONNECTS_TO", 
            is_admin=True
        )
        
        query = mock_neo4j_session.queries[-1]["query"]
        
        assert "MATCH (a)-[r:CONNECTS_TO]->(b)" in query
        assert "DELETE r" in query
        assert "a.layer = $a_layer" in query
        assert "b.layer = $b_layer" in query
        assert "RETURN count(r)" in query

    def test_execute_mass_update_syntax(self, mock_neo4j_session, mock_admin_user):
        """Should delete old relationship and merge new one in bulk."""
        source_filter = {"name": "CORE-01"}
        target_filter = {} # All targets
        
        topology_repo.execute_mass_update(
            source_filter, target_filter, 
            old_relationship="CONNECTS_TO", 
            new_relationship="DEPENDS_ON",
            is_admin=True
        )
        
        query = mock_neo4j_session.queries[-1]["query"]
        
        assert "MATCH (a)-[old:CONNECTS_TO]->(b)" in query
        assert "DELETE old" in query
        assert "MERGE (a)-[new:DEPENDS_ON]->(b)" in query
        assert "a.name = $a_name" in query
        assert "RETURN count(new)" in query

    def test_count_potential_links_mapping_fix(self, mock_neo4j_session, mock_admin_user):
        """Verify the fix for field mapping (source_samples/target_samples)."""
        # Set a mock response that matches the keys the repo expects from Neo4j
        mock_neo4j_session.set_default_response([{"total": 10, "src_sample": ["A"], "tgt_sample": ["B"]}])
        
        result = topology_repo.count_potential_links(
            {"layer": "X"}, {"layer": "Y"}, is_admin=True
        )
        
        # Verify result uses the new corrected keys for service/frontend
        assert "source_samples" in result
        assert "target_samples" in result
        assert result["source_samples"] == ["A"]
        assert result["target_samples"] == ["B"]
