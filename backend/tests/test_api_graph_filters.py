
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from main import app

client = TestClient(app)

@pytest.fixture
def mock_auth():
    with patch("services.auth_service.get_current_active_user") as mock:
        mock.return_value = MagicMock(username="admin", role="ADMIN")
        yield mock

def test_get_graph_full_with_filters(mock_auth):
    """
    Test that the /graph/full endpoint accepts filter parameters 
    and passes them to the link service.
    """
    with patch("services.link_service.get_full_graph") as mock_get_graph:
        mock_get_graph.return_value = {"nodes": [], "links": []}
        
        # Test with multiple filters
        response = client.get("/api/graph/full?layer=L3&location=DataCenter_A")
        
        assert response.status_code == 200
        # Verify link_service was called with parameters
        mock_get_graph.assert_called_once_with(layer="L3", location="DataCenter_A", owner=None)
