import pytest
from fastapi.testclient import TestClient
from main import app
from models.user import User

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def admin_token(client):
    # This depends on how your auth is mocked in conftest
    # But we can override the dependency if needed
    return "fake-admin-token"

class TestNodesBulkRouter:
    """Debugs 405 and routing issues for bulk operations."""

    def test_bulk_update_route_exists(self, client):
        """Verifies that PUT /api/nodes/bulk-update/ is reachable."""
        # We don't care about the result logic here, just the HTTP status
        # If it returns 401 or 403, the route EXISTS (Method Allowed).
        # If it returns 405, the route is NOT REGISTERED with PUT.
        response = client.put("/api/nodes/bulk-update/")
        assert response.status_code != 405, "PUT /api/nodes/bulk-update/ returned 405"

    def test_bulk_update_no_slash_route(self, client):
        """Checks if the version without trailing slash also works or redirects."""
        response = client.put("/api/nodes/bulk-update")
        # If redirect_slashes is False, this might be 404 or 405. 
        # But it should NOT be allowed to break the main app.
        assert response.status_code != 405, "PUT /api/nodes/bulk-update returned 405"

    def test_route_priority_collision(self, client):
        """Ensures 'bulk-update' isn't being hijacked by '/{node_id}'."""
        # If bulk-update is hijacked, it will try to use delete_node or get_node_usage
        # which usually expect GET/DELETE.
        response = client.put("/api/nodes/bulk-update/")
        # If it returns 401/403/422, it's hitting the right function.
        # If it returns 405, it might be hitting a GET-only route.
        assert response.status_code != 405

    def test_list_routes(self):
        """Print all registered routes for manual debug."""
        routes = []
        for route in app.routes:
            if hasattr(route, "path"):
                routes.append(f"{route.methods} {route.path}")
        
        print("\n".join(routes))
        assert any("/api/nodes/bulk-update" in r for r in routes)
