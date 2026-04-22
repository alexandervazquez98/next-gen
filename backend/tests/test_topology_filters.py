
import pytest
from unittest.mock import patch, MagicMock
from repositories import topology_repo

def test_get_filtered_graph_data_default_returns_only_cis():
    """
    Test that by default, the graph only returns :CI nodes and relationships between them.
    """
    # Patch get_db where it is IMPORTED in topology_repo
    with patch("repositories.topology_repo.get_db") as mock_get_db:
        session_mock = MagicMock()
        driver_mock = MagicMock()
        driver_mock.session.return_value.__enter__.return_value = session_mock
        mock_get_db.return_value = driver_mock
        
        session_mock.run.return_value = []
        
        topology_repo.get_filtered_graph_data()
        
        assert session_mock.run.call_count >= 2
        
        # Check nodes query
        args, _ = session_mock.run.call_args_list[0]
        nodes_query = args[0]
        assert "MATCH (n:CI)" in nodes_query
        
        # Check links query
        args, _ = session_mock.run.call_args_list[1]
        links_query = args[0]
        assert "MATCH (a:CI)-[r]->(b:CI)" in links_query

def test_get_filtered_graph_data_with_location_filter():
    """
    Test that applying a location filter adds the correct WHERE clause.
    """
    with patch("repositories.topology_repo.get_db") as mock_get_db:
        session_mock = MagicMock()
        driver_mock = MagicMock()
        driver_mock.session.return_value.__enter__.return_value = session_mock
        mock_get_db.return_value = driver_mock
        
        session_mock.run.return_value = []

        topology_repo.get_filtered_graph_data(location="DataCenter_A")
        
        # Check nodes query
        args, kwargs = session_mock.run.call_args_list[0]
        nodes_query = args[0]
        assert "WHERE n.location_name = $location" in nodes_query
        assert kwargs["location"] == "DataCenter_A"
