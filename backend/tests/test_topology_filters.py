
import pytest
from unittest.mock import patch, MagicMock
from repositories import topology_repo

@pytest.fixture
def mock_db():
    with patch("repositories.topology_repo.get_db") as mock:
        yield mock

def test_get_filtered_graph_data_default_returns_only_cis(mock_db):
    """
    Test that by default, the graph only returns :CI nodes and relationships between them.
    """
    session = mock_db.return_value.session.return_value.__enter__.return_value
    
    # We want to see if the query uses labels
    topology_repo.get_filtered_graph_data()
    
    # Check nodes query
    args, _ = session.run.call_args_list[0]
    nodes_query = args[0]
    assert "MATCH (n:CI)" in nodes_query
    
    # Check links query
    args, _ = session.run.call_args_list[1]
    links_query = args[0]
    assert "MATCH (a:CI)-[r]->(b:CI)" in links_query

def test_get_filtered_graph_data_with_location_filter(mock_db):
    """
    Test that applying a location filter adds the correct WHERE clause.
    """
    session = mock_db.return_value.session.return_value.__enter__.return_value
    
    topology_repo.get_filtered_graph_data(location="DataCenter_A")
    
    # Check nodes query
    args, kwargs = session.run.call_args_list[0]
    nodes_query = args[0]
    assert "WHERE n.location_name = $location" in nodes_query
    assert kwargs["location"] == "DataCenter_A"
