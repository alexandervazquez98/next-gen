
import pytest
from unittest.mock import patch, MagicMock
from repositories import topology_repo

def test_execute_mass_links_creates_cartesian_product():
    """
    Test that execute_mass_links constructs a query that links 
    everyone in Set A to everyone in Set B.
    """
    with patch("repositories.topology_repo.get_db") as mock_get_db:
        session_mock = MagicMock()
        driver_mock = MagicMock()
        driver_mock.session.return_value.__enter__.return_value = session_mock
        mock_get_db.return_value = driver_mock
        
        session_mock.run.return_value = []
        
        source_filter = {"layer": "Server"}
        target_filter = {"name": "CORE-SW-01"}
        rel_type = "DEPENDS_ON"
        
        # Mock result of MERGE
        mock_result = MagicMock()
        mock_result.single.return_value = {"total": 10}
        session_mock.run.return_value = mock_result
        
        topology_repo.execute_mass_links(source_filter, target_filter, rel_type)
        
        # Verify that session.run was called
        assert session_mock.run.call_count == 1
        
        args, kwargs = session_mock.run.call_args
        query = args[0]
        
        # We expect a Cartesian MERGE
        assert "MATCH (a:CI), (b:CI)" in query
        assert "MERGE (a)-[r:DEPENDS_ON]->(b)" in query
        assert "a.layer = $src_layer" in query
        assert "b.name = $target_name" in query

def test_count_potential_links_returns_product_size():
    """
    Test the simulation logic.
    """
    with patch("repositories.topology_repo.get_db") as mock_get_db:
        session_mock = MagicMock()
        driver_mock = MagicMock()
        driver_mock.session.return_value.__enter__.return_value = session_mock
        mock_get_db.return_value = driver_mock
        
        # Mock result of COUNT
        mock_result = MagicMock()
        mock_result.single.return_value = {"total": 20}
        session_mock.run.return_value = mock_result
        
        source_filter = {"layer": "Server"}
        target_filter = {"location": "Site_A"}
        
        count = topology_repo.count_potential_links(source_filter, target_filter)
        
        assert count == 20
        assert "RETURN count(*) as total" in session_mock.run.call_args[0][0]
