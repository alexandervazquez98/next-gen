
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from main import app

client = TestClient(app)

@pytest.fixture
def mock_auth():
    from services.auth_service import get_current_active_user
    mock_user = MagicMock(username="admin", role="ADMIN")
    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    yield mock_user
    app.dependency_overrides.clear()

def test_mass_link_simulate_requires_auth():
    """Verify that simulate endpoint is protected."""
    response = client.post("/api/links/mass/simulate", json={})
    assert response.status_code == 401

def test_mass_link_simulate_success(mock_auth):
    """Test successful simulation call."""
    with patch("services.link_service.simulate_bulk_links") as mock_sim:
        mock_sim.return_value = {
            "potential_links": 45,
            "is_safe": True,
            "message": "Ready"
        }
        
        payload = {
            "source_filter": {"layer": "Server"},
            "target_filter": {"name": "CORE-SW"},
            "relationship": "DEPENDS_ON"
        }
        
        response = client.post("/api/links/mass/simulate", json=payload)
        assert response.status_code == 200
        assert response.json()["potential_links"] == 45

def test_mass_link_execute_requires_auth():
    """Verify that execute endpoint is protected."""
    response = client.post("/api/links/mass", json={})
    assert response.status_code == 401

def test_mass_link_execute_success(mock_auth):
    """Test successful execution call."""
    with patch("services.link_service.execute_bulk_links") as mock_exec:
        mock_exec.return_value = {
            "success": True,
            "message": "Created 45 links",
            "created_count": 45
        }
        
        payload = {
            "source_filter": {"layer": "Server"},
            "target_filter": {"name": "CORE-SW"},
            "relationship": "DEPENDS_ON"
        }
        
        response = client.post("/api/links/mass", json=payload)
        assert response.status_code == 200
        assert response.json()["created_count"] == 45
