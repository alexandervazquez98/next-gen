"""Router-level tests for the nodes endpoints — mocked dependencies.

Focus areas:
- GET /api/nodes — auth enforcement, admin vs scoped listing
- POST /api/nodes — CI_EDIT permission, success, validation
- DELETE /api/nodes/{id} — CI_DELETE permission, success
- GET /api/nodes/{id}/usage — public endpoint, success
- GET /api/nodes/{id}/metrics — public endpoint, success
- POST /api/nodes/upload — file validation (non-.xlsx rejection)
- GET /api/nodes/template — public endpoint, returns streaming response

Strategy:
- Patch Neo4j driver BEFORE importing main (avoids real connection at import)
- Use FastAPI TestClient
- Override get_current_active_user for protected endpoints
- Mock topology_repo functions for service-layer isolation
"""

import pytest
import json
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from io import BytesIO

# ---------------------------------------------------------------------------
# Patch Neo4j driver BEFORE importing anything that touches database.py
# ---------------------------------------------------------------------------
_mock_neo4j_driver = MagicMock()
with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
    from main import app
    from database import get_db

from models.user import User, UserPermission
from services.auth_service import get_current_active_user

# ---------------------------------------------------------------------------
# TestClient
# ---------------------------------------------------------------------------
client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pydantic_user(
    username: str = "testuser",
    role: str = "OPERATOR",
    permissions: list[UserPermission] | None = None,
    disabled: bool = False,
    allowed_locations: list[str] | None = None,
) -> User:
    """Create a Pydantic User for injection via dependency override."""
    return User(
        username=username,
        role=role,
        permissions=permissions or [],
        allowed_locations=allowed_locations or [],
        disabled=disabled,
    )


def _make_neo4j_node_record(
    node_id: str = "ci-001",
    name: str = "Router-01",
    status: str = "OK",
    ip: str = "192.168.1.1",
    brand: str = "Cisco",
    model: str = "ASR-1000",
    layer: str = "router",
    location_name: str = "Data Center A",
    snmp: str | None = None,
) -> dict:
    """Build a dict simulating a Neo4j CI node record."""
    snmp_val = snmp or json.dumps({"version": "v2c", "readCommunity": "public"})
    return {
        "id": node_id,
        "name": name,
        "status": status,
        "ip": ip,
        "brand": brand,
        "model": model,
        "layer": layer,
        "location_name": location_name,
        "snmp": snmp_val,
        "location": None,
        "pollingInterval": 60,
    }


def _make_full_record(
    node_props: dict | None = None,
    category: str = "router",
    metrics: list[dict] | None = None,
) -> dict:
    """Wrap node props into the shape returned by topology_repo.get_nodes."""
    return {
        "node": node_props or _make_neo4j_node_record(),
        "category": category,
        "metrics": metrics or [],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_neo4j_driver():
    """Provide a mock Neo4j driver with controllable session/query responses."""
    driver = MagicMock()
    mock_session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    mock_session.run.return_value = []
    return driver


# ---------------------------------------------------------------------------
# Tests: GET /api/nodes — list all CIs
# ---------------------------------------------------------------------------


class TestGetNodes:
    """Tests for GET /api/nodes endpoint."""

    def test_list_nodes_unauthenticated(self):
        """No auth token should return 401."""
        response = client.get("/api/nodes")
        assert response.status_code == 401

    def test_list_nodes_disabled_user(self):
        """Disabled user should get 400."""
        disabled_user = _make_pydantic_user(
            username="disabled_user",
            role="VIEWER",
            disabled=True,
        )

        async def override_get_current_active_user():
            from fastapi import HTTPException

            if disabled_user.disabled:
                raise HTTPException(status_code=400, detail="Inactive user")
            return disabled_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.get("/api/nodes")
        assert response.status_code == 400

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_list_nodes_admin_success(self, mock_neo4j_driver):
        """Admin should list all nodes without location scoping."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        node_record = _make_neo4j_node_record(
            node_id="ci-001",
            name="Router-01",
            brand="Cisco",
            model="ASR-1000",
        )
        full_record = _make_full_record(node_props=node_record, category="router")

        with patch("services.node_service.topology_repo") as mock_repo:
            mock_repo.get_nodes.return_value = [full_record]

            response = client.get("/api/nodes")

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["label"] == "Router-01"
            assert data[0]["brand"] == "Cisco"

            # Admin should get is_admin=True, no location filter
            mock_repo.get_nodes.assert_called_once()
            call_args = mock_repo.get_nodes.call_args
            assert call_args[0][1] is True  # is_admin=True

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_list_nodes_operator_scoped_by_location(self, mock_neo4j_driver):
        """Non-admin should have results scoped to allowed_locations."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            allowed_locations=["HQ-Madrid"],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        node_record = _make_neo4j_node_record(
            node_id="ci-002",
            name="Switch-01",
            location_name="HQ-Madrid",
        )
        full_record = _make_full_record(node_props=node_record, category="switch")

        with patch("services.node_service.topology_repo") as mock_repo:
            mock_repo.get_nodes.return_value = [full_record]

            response = client.get("/api/nodes")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["label"] == "Switch-01"

            # Non-admin: should pass allowed_locations and is_admin=False
            mock_repo.get_nodes.assert_called_once()
            call_args = mock_repo.get_nodes.call_args
            assert call_args[0][0] == ["HQ-Madrid"]
            assert call_args[0][1] is False

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_list_nodes_operator_no_locations_returns_empty(self):
        """Operator with no allowed_locations should get empty list."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            allowed_locations=[],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        # topology_repo.get_nodes returns [] early when not admin and no locations
        with patch("services.node_service.topology_repo") as mock_repo:
            mock_repo.get_nodes.return_value = []

            response = client.get("/api/nodes")

            assert response.status_code == 200
            data = response.json()
            assert data == []

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_list_nodes_with_metrics(self):
        """Nodes with associated metrics should include metric data."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        node_record = _make_neo4j_node_record(node_id="ci-003", name="Server-01")
        metrics = [
            {
                "name": "cpu-load",
                "protocol": "SNMP",
                "status": "OK",
                "value": 45.2,
                "last_updated": None,
            }
        ]
        full_record = _make_full_record(node_props=node_record, metrics=metrics)

        with patch("services.node_service.topology_repo") as mock_repo:
            mock_repo.get_nodes.return_value = [full_record]

            response = client.get("/api/nodes")

            assert response.status_code == 200
            data = response.json()
            assert len(data[0]["metrics"]) == 1
            assert data[0]["metrics"][0]["name"] == "cpu-load"
            assert data[0]["metrics"][0]["value"] == 45.2

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_list_nodes_snmp_string_parsed(self):
        """SNMP stored as JSON string should be parsed to dict."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        snmp_json = json.dumps({"version": "v3", "readCommunity": "secure"})
        node_record = _make_neo4j_node_record(snmp=snmp_json)
        full_record = _make_full_record(node_props=node_record)

        with patch("services.node_service.topology_repo") as mock_repo:
            mock_repo.get_nodes.return_value = [full_record]

            response = client.get("/api/nodes")

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data[0]["snmp"], dict)
            assert data[0]["snmp"]["version"] == "v3"

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: POST /api/nodes — create/update CI
# ---------------------------------------------------------------------------


class TestCreateNode:
    """Tests for POST /api/nodes endpoint."""

    def test_create_node_unauthenticated(self):
        """No auth token should return 401."""
        response = client.post(
            "/api/nodes",
            json={
                "id": "ci-new",
                "label": "New Router",
                "type": "router",
            },
        )
        assert response.status_code == 401

    def test_create_node_no_ci_edit_permission(self):
        """User without CI_EDIT should get 403."""
        fake_user = _make_pydantic_user(
            username="viewer",
            role="VIEWER",
            permissions=[],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.post(
            "/api/nodes",
            json={
                "id": "ci-new",
                "label": "New Router",
                "type": "router",
            },
        )

        assert response.status_code == 403

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_create_node_admin_success(self):
        """Admin should be able to create a node."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        with patch("routers.nodes.node_service") as mock_service:
            mock_service.create_update_node.return_value = {
                "message": "Node created/updated",
                "id": "ci-new",
            }

            response = client.post(
                "/api/nodes",
                json={
                    "id": "ci-new",
                    "label": "New Router",
                    "type": "router",
                    "status": "OK",
                    "ip": "10.0.0.1",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["message"] == "Node created/updated"
            assert data["id"] == "ci-new"

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_create_node_operator_with_ci_edit(self):
        """Operator with CI_EDIT permission should create a node."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.CI_EDIT],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        with patch("routers.nodes.node_service") as mock_service:
            mock_service.create_update_node.return_value = {
                "message": "Node created/updated",
                "id": "ci-002",
            }

            response = client.post(
                "/api/nodes",
                json={
                    "id": "ci-002",
                    "label": "Switch-01",
                    "type": "switch",
                },
            )

            assert response.status_code == 200

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_create_node_invalid_payload(self):
        """Missing required fields should return 422."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        # Missing required 'label' and 'type'
        response = client.post(
            "/api/nodes",
            json={"id": "ci-bad"},
        )

        assert response.status_code == 422

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: DELETE /api/nodes/{id} — delete CI
# ---------------------------------------------------------------------------


class TestDeleteNode:
    """Tests for DELETE /api/nodes/{node_id} endpoint."""

    def test_delete_node_unauthenticated(self):
        """No auth token should return 401."""
        response = client.delete("/api/nodes/ci-001")
        assert response.status_code == 401

    def test_delete_node_no_ci_delete_permission(self):
        """User without CI_DELETE should get 403."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.CI_EDIT],  # has CI_EDIT but not CI_DELETE
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.delete("/api/nodes/ci-001")

        assert response.status_code == 403

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_delete_node_admin_success(self):
        """Admin should be able to delete a node."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        with patch("routers.nodes.node_service") as mock_service:
            mock_service.delete_node.return_value = {
                "message": "Node deleted",
                "id": "ci-001",
            }

            response = client.delete("/api/nodes/ci-001")

            assert response.status_code == 200
            data = response.json()
            assert data["message"] == "Node deleted"
            assert data["id"] == "ci-001"

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: GET /api/nodes/{id}/usage — public endpoint
# ---------------------------------------------------------------------------


class TestGetNodeUsage:
    """Tests for GET /api/nodes/{node_id}/usage endpoint."""

    def test_get_node_usage_success(self):
        """Should return usage count without auth."""
        with patch("routers.nodes.node_service") as mock_service:
            mock_service.get_node_usage.return_value = {"count": 5}

            response = client.get("/api/nodes/ci-001/usage")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 5

    def test_get_node_usage_no_auth_required(self):
        """Endpoint should be accessible without authentication."""
        with patch("routers.nodes.node_service") as mock_service:
            mock_service.get_node_usage.return_value = {"count": 0}

            response = client.get("/api/nodes/ci-999/usage")

            # Should NOT be 401 — this is a public endpoint
            assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tests: GET /api/nodes/{id}/metrics — public endpoint
# ---------------------------------------------------------------------------


class TestGetNodeMetrics:
    """Tests for GET /api/nodes/{node_id}/metrics endpoint."""

    def test_get_node_metrics_success(self):
        """Should return applicable metrics without auth."""
        with patch("routers.nodes.metric_service") as mock_service:
            mock_service.get_applicable_metrics.return_value = [
                {"id": "cpu-load", "protocol": "SNMP"},
                {"id": "PING-Router-01", "protocol": "ICMP"},
            ]

            response = client.get("/api/nodes/ci-001/metrics")

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 2

    def test_get_node_metrics_no_auth_required(self):
        """Endpoint should be accessible without authentication."""
        with patch("routers.nodes.metric_service") as mock_service:
            mock_service.get_applicable_metrics.return_value = []

            response = client.get("/api/nodes/ci-001/metrics")

            assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tests: POST /api/nodes/upload — bulk upload
# ---------------------------------------------------------------------------


class TestUploadNodes:
    """Tests for POST /api/nodes/upload endpoint."""

    def test_upload_unauthenticated(self):
        """Request without auth should return 401."""
        response = client.post("/api/nodes/upload")
        assert response.status_code == 401

    def test_upload_no_ci_edit_permission(self):
        """User without CI_EDIT should return 403."""
        from services.auth_service import get_current_active_user
        app.dependency_overrides[get_current_active_user] = lambda: User(
            id="op-01", username="op01", role="OPERATOR", permissions=[]
        )
        response = client.post(
            "/api/nodes/upload",
            files={"file": ("data.xlsx", b"fake", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        )
        assert response.status_code == 403
        app.dependency_overrides.clear()

    def test_upload_invalid_file_format(self):
        """Non-.xlsx file should return 400 (with auth)."""
        from services.auth_service import get_current_active_user
        app.dependency_overrides[get_current_active_user] = lambda: User(
            id="admin-01", username="admin", role="ADMIN", permissions=["CI_EDIT"]
        )

        # TestClient sends files via the `files` parameter
        response = client.post(
            "/api/nodes/upload",
            files={"file": ("data.csv", b"fake,csv,content", "text/csv")},
        )

        assert response.status_code == 400
        assert "Invalid file format" in response.json()["detail"]
        app.dependency_overrides.clear()

    def test_upload_xlsx_accepted(self):
        """An .xlsx file should be accepted (service mocked, with auth)."""
        from services.auth_service import get_current_active_user
        app.dependency_overrides[get_current_active_user] = lambda: User(
            id="admin-01", username="admin", role="ADMIN", permissions=["CI_EDIT"]
        )

        # Create a minimal fake xlsx-like bytes (service will be mocked)
        fake_xlsx = b"PK\x03\x04fake-xlsx-content"

        async def mock_bulk_upload(*args, **kwargs):
            return {"message": "Successfully processed 0 CIs"}

        with patch.object(
            __import__("services").node_service,
            "bulk_upload_nodes",
            new=mock_bulk_upload,
        ):
            response = client.post(
                "/api/nodes/upload",
                files={
                    "file": (
                        "import.xlsx",
                        fake_xlsx,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

            # Should NOT be 400 — file format is valid
            assert response.status_code == 200
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: GET /api/nodes/template — protected endpoint
# ---------------------------------------------------------------------------


class TestGetNodeTemplate:
    """Tests for GET /api/nodes/template endpoint."""

    def test_get_template_unauthenticated(self):
        """Template endpoint should now return 401 without auth."""
        response = client.get("/api/nodes/template")
        assert response.status_code == 401

    def test_get_template_authenticated_success(self):
        """Template endpoint should be accessible with authentication and CI_EDIT."""
        from services.auth_service import get_current_active_user
        app.dependency_overrides[get_current_active_user] = lambda: User(
            id="user-01", username="user01", role="OPERATOR", permissions=["CI_EDIT"]
        )
        with patch("routers.nodes.node_service") as mock_service:
            # Return a mock StreamingResponse-compatible object
            mock_stream = MagicMock()
            mock_stream.status_code = 200
            mock_service.get_node_template.return_value = mock_stream

            response = client.get("/api/nodes/template")

            assert response.status_code == 200
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: PUT /api/nodes/{node_id}/metadata — AI agent metadata update
# ---------------------------------------------------------------------------


class TestUpdateNodeMetadata:
    """Tests for PUT /api/nodes/{node_id}/metadata endpoint with AI agent restrictions."""

    def _ai_user(self, username: str = "ai-agent-1") -> User:
        """Create a fake AI agent user."""
        return User(
            username=username,
            role="AI_DIAGNOSTIC",
            permissions=[],
            allowed_locations=[],
        )

    def _operator_user(self) -> User:
        """Create a regular operator user."""
        return User(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.CI_EDIT],
            allowed_locations=[],
        )

    def _mock_session(self):
        """Return a mock DB session that won't hit the real DB."""
        session = MagicMock()
        session.execute.return_value = MagicMock(scalar=MagicMock(return_value=0))
        session.close = MagicMock()
        return session

    def test_metadata_update_unauthenticated(self):
        """No auth token should return 401."""
        response = client.put(
            "/api/nodes/ci-001/metadata",
            json={"status": "MAINTENANCE"},
        )
        assert response.status_code == 401

    def test_ai_agent_can_update_allowed_field_status(self):
        """AI agent can update 'status' field — it is in the allowed set."""
        async def override():
            return self._ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.nodes.node_service") as mock_service, \
             patch("services.ai_guard_service.SessionLocal") as mock_session, \
             patch("services.ai_guard_service.check_all_guards") as mock_guards:
            mock_guards.return_value = MagicMock(allowed=True)
            mock_session.return_value = self._mock_session()
            mock_service.update_node_metadata.return_value = {
                "message": "Node metadata updated",
                "id": "ci-001",
            }

            response = client.put(
                "/api/nodes/ci-001/metadata",
                json={"status": "MAINTENANCE"},
            )

            assert response.status_code == 200
            mock_service.update_node_metadata.assert_called_once()

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_can_update_allowed_field_polling_interval(self):
        """AI agent can update 'pollingInterval' field — it is in the allowed set."""
        async def override():
            return self._ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.nodes.node_service") as mock_service, \
             patch("services.ai_guard_service.SessionLocal") as mock_session, \
             patch("services.ai_guard_service.check_all_guards") as mock_guards:
            mock_guards.return_value = MagicMock(allowed=True)
            mock_session.return_value = self._mock_session()
            mock_service.update_node_metadata.return_value = {
                "message": "Node metadata updated",
                "id": "ci-001",
            }

            response = client.put(
                "/api/nodes/ci-001/metadata",
                json={"pollingInterval": 120},
            )

            assert response.status_code == 200

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_can_update_allowed_field_owner(self):
        """AI agent can update 'owner' field — it is in the allowed set."""
        async def override():
            return self._ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.nodes.node_service") as mock_service, \
             patch("services.ai_guard_service.SessionLocal") as mock_session, \
             patch("services.ai_guard_service.check_all_guards") as mock_guards:
            mock_guards.return_value = MagicMock(allowed=True)
            mock_session.return_value = self._mock_session()
            mock_service.update_node_metadata.return_value = {
                "message": "Node metadata updated",
                "id": "ci-001",
            }

            response = client.put(
                "/api/nodes/ci-001/metadata",
                json={"owner": "NetOps"},
            )

            assert response.status_code == 200

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_can_update_allowed_field_metadata_dict(self):
        """AI agent can update 'metadata' field — it is in the allowed set."""
        async def override():
            return self._ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.nodes.node_service") as mock_service, \
             patch("services.ai_guard_service.SessionLocal") as mock_session, \
             patch("services.ai_guard_service.check_all_guards") as mock_guards:
            mock_guards.return_value = MagicMock(allowed=True)
            mock_session.return_value = self._mock_session()
            mock_service.update_node_metadata.return_value = {
                "message": "Node metadata updated",
                "id": "ci-001",
            }

            response = client.put(
                "/api/nodes/ci-001/metadata",
                json={"metadata": {"note": "updated by AI"}},
            )

            assert response.status_code == 200

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_blocked_from_updating_brand_field(self):
        """AI agent gets 403 when trying to update 'brand' field."""
        async def override():
            return self._ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("services.ai_guard_service.SessionLocal") as mock_session, \
             patch("services.ai_guard_service.check_all_guards") as mock_guards:
            mock_guards.return_value = MagicMock(allowed=True)
            mock_session.return_value = self._mock_session()

            response = client.put(
                "/api/nodes/ci-001/metadata",
                json={"status": "MAINTENANCE", "brand": "Juniper"},
            )

            assert response.status_code == 403
            assert "brand" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_blocked_from_updating_model_field(self):
        """AI agent gets 403 when trying to update 'model' field."""
        async def override():
            return self._ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("services.ai_guard_service.SessionLocal") as mock_session, \
             patch("services.ai_guard_service.check_all_guards") as mock_guards:
            mock_guards.return_value = MagicMock(allowed=True)
            mock_session.return_value = self._mock_session()

            response = client.put(
                "/api/nodes/ci-001/metadata",
                json={"owner": "NetOps", "model": "MX-204"},
            )

            assert response.status_code == 403
            assert "model" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_blocked_from_updating_snmp_field(self):
        """AI agent gets 403 when trying to update 'snmp' field."""
        async def override():
            return self._ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("services.ai_guard_service.SessionLocal") as mock_session, \
             patch("services.ai_guard_service.check_all_guards") as mock_guards:
            mock_guards.return_value = MagicMock(allowed=True)
            mock_session.return_value = self._mock_session()

            response = client.put(
                "/api/nodes/ci-001/metadata",
                json={"status": "OK", "snmp": {"version": "v3"}},
            )

            assert response.status_code == 403
            assert "snmp" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_blocked_when_guard_fails(self):
        """AI agent gets 403 when guard check fails (e.g., cooldown active)."""
        async def override():
            return self._ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("services.ai_guard_service.check_all_guards") as mock_guards:
            mock_guards.return_value = MagicMock(
                allowed=False,
                reason="Cooldown active",
            )

            response = client.put(
                "/api/nodes/ci-001/metadata",
                json={"status": "MAINTENANCE"},
            )

            assert response.status_code == 403
            assert "Cooldown active" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_regular_operator_can_update_all_fields(self):
        """Regular operator with CI_EDIT can update any field (including blocked ones)."""
        async def override():
            return self._operator_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.nodes.node_service") as mock_service:
            mock_service.update_node_metadata.return_value = {
                "message": "Node metadata updated",
                "id": "ci-001",
            }

            response = client.put(
                "/api/nodes/ci-001/metadata",
                json={"ip": "10.0.0.99", "brand": "Juniper"},
            )

            # Regular user is not blocked by AI field restrictions
            assert response.status_code == 200


# Tests: GET /api/nodes/search — CI text search
# ---------------------------------------------------------------------------


class TestSearchNodes:
    """Tests for GET /api/nodes/search endpoint."""

    def test_search_nodes_unauthenticated(self):
        """No auth token should return 401."""
        response = client.get("/api/nodes/search?q=router")
        assert response.status_code == 401

    def test_search_nodes_query_too_short(self):
        """Query with fewer than 2 chars should return 400."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.get("/api/nodes/search?q=a")
        assert response.status_code == 400
        assert "at least 2 characters" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_search_nodes_success(self):
        """Valid query should return 200 with array of matching nodes."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        node_record = _make_neo4j_node_record(
            node_id="ci-001",
            name="Router-01",
            brand="Cisco",
            model="ASR-1000",
        )

        with patch("routers.nodes.node_service") as mock_service:
            mock_service.search_nodes.return_value = [
                {
                    "id": "ci-001",
                    "label": "Router-01",
                    "ip": "192.168.1.1",
                    "status": "OK",
                    "brand": "Cisco",
                    "model": "ASR-1000",
                }
            ]

            response = client.get("/api/nodes/search?q=Router")

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["label"] == "Router-01"
            mock_service.search_nodes.assert_called_once()
            call_args = mock_service.search_nodes.call_args
            assert call_args[0][0].username == "admin"
            assert call_args[0][1] == "Router"

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_search_nodes_empty_results(self):
        """Empty results should return 200 with empty array."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        with patch("routers.nodes.node_service") as mock_service:
            mock_service.search_nodes.return_value = []

            response = client.get("/api/nodes/search?q=NonExistent")

            assert response.status_code == 200
            data = response.json()
            assert data == []
