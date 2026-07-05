"""Router-level tests for links endpoints — mocked dependencies.

Focus areas:
- Links: NO auth on any endpoint (documented gap). All endpoints are public.
- GET /api/links — list all relationship links
- POST /api/links — create a relationship
- DELETE /api/links — delete a relationship
- GET /api/graph/full — fetch complete graph topology

Strategy:
- Patch Neo4j driver BEFORE importing main (avoids real connection at import)
- Use FastAPI TestClient
- Mock topology_repo functions for service-layer isolation
- Document the auth gap (no endpoint requires authentication)
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from models.user import User
from services.auth_service import get_current_active_user

# ---------------------------------------------------------------------------
# Patch Neo4j driver BEFORE importing anything that touches database.py
# ---------------------------------------------------------------------------
_mock_neo4j_driver = MagicMock()
with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
    from main import app

# ---------------------------------------------------------------------------
# TestClient
# ---------------------------------------------------------------------------
client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticated_links_user():
    app.dependency_overrides[get_current_active_user] = lambda: User(
        username="test-admin",
        role="ADMIN",
        permissions=[],
        allowed_locations=[],
    )
    yield
    app.dependency_overrides.pop(get_current_active_user, None)


# ===========================================================================
# LINKS ROUTER TESTS
# ===========================================================================
# NOTE: The links router has NO authentication. All endpoints are public.
# This is a known security gap — these tests document the current behavior.
# ===========================================================================


class TestLinksList:
    """Tests for GET /api/links — list all relationship links."""

    def test_list_links_returns_empty(self):
        """Should return empty list when no links exist."""
        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.get_links.return_value = []

            response = client.get("/api/links")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_list_links_returns_data(self):
        """Should return link definitions when they exist."""
        sample_links = [
            {
                "source": "ci-001",
                "source_label": "Router-01",
                "target": "ci-002",
                "target_label": "Switch-01",
                "relationship": "CONNECTS_TO",
            },
            {
                "source": "ci-002",
                "source_label": "Switch-01",
                "target": "ci-003",
                "target_label": "Server-01",
                "relationship": "HOSTED_ON",
            },
        ]

        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.get_links.return_value = sample_links

            response = client.get("/api/links")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["source"] == "ci-001"
        assert data[0]["relationship"] == "CONNECTS_TO"
        assert data[1]["relationship"] == "HOSTED_ON"

    def test_list_links_no_auth_required(self):
        """Links list should NOT require authentication (documented gap)."""
        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.get_links.return_value = []

            response = client.get("/api/links")

        assert response.status_code == 200
        assert response.status_code != 401
        assert response.status_code != 403

    def test_list_links_exposes_medium_when_set(self):
        """Slice 1 / VPN-Rel R4 / Sc 8: /api/links propagates tunnel medium."""
        sample_links = [
            {
                "source": "hub-a",
                "source_label": "Hub-A",
                "target": "router-b",
                "target_label": "Router-B",
                "relationship": "CONNECTS_TO",
                "medium": "vpn",
            },
            {
                "source": "hub-c",
                "source_label": "Hub-C",
                "target": "router-d",
                "target_label": "Router-D",
                "relationship": "CONNECTS_TO",
                "medium": "satellite",
            },
        ]

        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.get_links.return_value = sample_links

            response = client.get("/api/links")

        assert response.status_code == 200
        data = response.json()
        assert data[0]["medium"] == "vpn"
        assert data[1]["medium"] == "satellite"


class TestLinksCreate:
    """Tests for POST /api/links — create a relationship."""

    def test_create_link_success(self):
        """Should create a link between two nodes."""
        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.create_link.return_value = None

            response = client.post(
                "/api/links",
                json={
                    "source": "ci-001",
                    "target": "ci-002",
                    "relationship": "DEPENDS_ON",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "Link created" in data["message"]
        # Slice 1 (feat-324): the repository signature gained an optional
        # `medium` kwarg. Non-tunnel calls pass medium=None.
        mock_repo.create_link.assert_called_once_with("ci-001", "ci-002", "DEPENDS_ON", medium=None)

    def test_create_link_validates_required_fields(self):
        """Should reject request missing required fields (source, target, relationship)."""
        response = client.post(
            "/api/links",
            json={"source": "ci-001"},
        )

        assert response.status_code == 422

    def test_create_link_no_auth_required(self):
        """Create link should NOT require auth (documented gap)."""
        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.create_link.return_value = None

            response = client.post(
                "/api/links",
                json={
                    "source": "ci-001",
                    "target": "ci-002",
                    "relationship": "CONNECTS_TO",
                },
            )

        assert response.status_code != 401
        assert response.status_code != 403

    def test_create_tunnel_link_rejected_without_vpn_hub_endpoint(self):
        """Slice 1 / VPN-Rel R3 / Sc 7: tunnel relation without vpn_hub endpoint
        surfaces as HTTP 400."""
        with patch("services.link_service.topology_repo") as mock_repo:
            # Make repository.create_link see two router endpoints (no vpn_hub).
            mock_repo.create_link.return_value = None

            response = client.post(
                "/api/links",
                json={
                    "source": "router-a",
                    "target": "router-b",
                    "relationship": "CONNECTS_TO",
                    "medium": "vpn",
                },
            )

        assert response.status_code == 400

    def test_create_link_invalid_medium_returns_400_without_persistence(self):
        """Invalid medium should return 400 at the route and avoid partial writes."""
        with patch("services.link_service.topology_repo") as mock_repo:
            response = client.post(
                "/api/links",
                json={
                    "source": "hub-a",
                    "target": "router-b",
                    "relationship": "CONNECTS_TO",
                    "medium": "microwave",
                },
            )

        assert response.status_code == 400
        mock_repo.create_link.assert_not_called()


class TestLinksDelete:
    """Tests for DELETE /api/links — delete a relationship."""

    def test_delete_link_success(self):
        """Should delete a link between two nodes."""
        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.delete_link.return_value = None

            response = client.request(
                "DELETE",
                "/api/links",
                json={
                    "source": "ci-001",
                    "target": "ci-002",
                    "relationship": "DEPENDS_ON",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "Link deleted" in data["message"]
        mock_repo.delete_link.assert_called_once_with("ci-001", "ci-002", "DEPENDS_ON")

    def test_delete_link_validates_required_fields(self):
        """Should reject request missing required fields."""
        response = client.request(
            "DELETE",
            "/api/links",
            json={"source": "ci-001"},
        )

        assert response.status_code == 422

    def test_delete_link_no_auth_required(self):
        """Delete link should NOT require auth (documented gap)."""
        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.delete_link.return_value = None

            response = client.request(
                "DELETE",
                "/api/links",
                json={
                    "source": "ci-001",
                    "target": "ci-002",
                    "relationship": "CONNECTS_TO",
                },
            )

        assert response.status_code != 401
        assert response.status_code != 403


class TestGraphFull:
    """Tests for GET /api/graph/full — fetch complete graph topology."""

    def test_full_graph_returns_empty(self):
        """Should return empty graph when no data exists."""
        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.get_filtered_graph_data.return_value = ([], [])

            response = client.get("/api/graph/full")

        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "links" in data
        assert len(data["nodes"]) == 0
        assert len(data["links"]) == 0

    def test_full_graph_returns_data(self):
        """Should return formatted nodes and links from graph data."""
        raw_nodes = [
            {
                "id": "ci-001",
                "name": "Router-01",
                "status": "OK",
                "_labels": ["CI"],
            },
            {
                "id": "ci-002",
                "name": "Switch-01",
                "status": "WARNING",
                "_labels": ["CI"],
            },
            {
                "id": "cpu-load",
                "protocol": "SNMP",
                "_labels": ["MetricDef"],
            },
        ]
        raw_links = [
            {
                "source_node": {"id": "ci-001", "name": "Router-01"},
                "target_node": {"id": "ci-002", "name": "Switch-01"},
                "type": "CONNECTS_TO",
            },
        ]

        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.get_filtered_graph_data.return_value = (raw_nodes, raw_links)

            response = client.get("/api/graph/full")

        assert response.status_code == 200
        data = response.json()
        assert len(data["nodes"]) == 3
        assert len(data["links"]) == 1
        assert data["links"][0]["source"] == "ci-001"
        assert data["links"][0]["target"] == "ci-002"
        assert data["links"][0]["relationship"] == "CONNECTS_TO"

    def test_full_graph_handles_fallback_ids(self):
        """Should handle nodes without explicit ID using name/label fallback."""
        raw_nodes = [
            {
                "name": "Router-01",
                "status": "OK",
                "_labels": ["CI"],
            },
            {
                "brand": "Cisco",
                "model": "ASR-1000",
                "_labels": ["HardwareModel"],
            },
        ]
        raw_links = []

        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.get_filtered_graph_data.return_value = (raw_nodes, raw_links)

            response = client.get("/api/graph/full")

        assert response.status_code == 200
        data = response.json()
        assert len(data["nodes"]) == 2
        # First node: uses name as fallback
        assert data["nodes"][0]["id"] == "Router-01"
        assert data["nodes"][0]["type"] == "CI"
        # Second node: uses "Brand Model" as fallback
        assert data["nodes"][1]["id"] == "Cisco ASR-1000"
        assert data["nodes"][1]["type"] == "Hardware"

    def test_full_graph_categorizes_node_types(self):
        """Should correctly categorize nodes by their Neo4j labels."""
        raw_nodes = [
            {"id": "cat-1", "name": "Router", "_labels": ["Category"]},
            {"id": "owner-1", "name": "NetOps", "_labels": ["OwnerGroup"]},
            {"id": "user-1", "name": "admin", "_labels": ["User"]},
            {
                "id": "hw-1",
                "brand": "Cisco",
                "model": "ISR4K",
                "_labels": ["HardwareModel"],
            },
            {"id": "metric-1", "protocol": "SNMP", "_labels": ["MetricDef"]},
            {"id": "unknown-1", "name": "Something", "_labels": ["CustomLabel"]},
        ]

        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.get_filtered_graph_data.return_value = (raw_nodes, [])

            response = client.get("/api/graph/full")

        assert response.status_code == 200
        data = response.json()
        types = {n["id"]: n["type"] for n in data["nodes"]}
        assert types["cat-1"] == "Category"
        assert types["owner-1"] == "Owner"
        assert types["user-1"] == "User"
        assert types["hw-1"] == "Hardware"
        assert types["metric-1"] == "Metric"
        assert types["unknown-1"] == "Unknown"

    def test_full_graph_no_auth_required(self):
        """Full graph should NOT require authentication (documented gap)."""
        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.get_filtered_graph_data.return_value = ([], [])

            response = client.get("/api/graph/full")

        assert response.status_code == 200
        assert response.status_code != 401
        assert response.status_code != 403

    def test_full_graph_exposes_medium_on_tunnel_links(self):
        """Slice 1 / VPN-Rel R4 / Sc 8: /api/graph/full surfaces tunnel medium."""
        raw_nodes = [
            {"id": "hub-a", "name": "Hub-A", "status": "OK", "_labels": ["CI"]},
            {"id": "router-b", "name": "Router-B", "status": "OK", "_labels": ["CI"]},
        ]
        raw_links = [
            {
                "source_node": {"id": "hub-a", "name": "Hub-A"},
                "target_node": {"id": "router-b", "name": "Router-B"},
                "type": "CONNECTS_TO",
                "medium": "satellite",
            },
        ]

        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.get_filtered_graph_data.return_value = (raw_nodes, raw_links)

            response = client.get("/api/graph/full")

        assert response.status_code == 200
        data = response.json()
        assert data["links"][0]["medium"] == "satellite"

    def test_full_graph_admin_projects_public_ip_for_cidetailmodal_topology_consumer(self):
        """Admin /graph/full topology data exposes public_ip after scoped repository access."""
        raw_nodes = [
            {
                "id": "hub-a",
                "name": "Hub-A",
                "status": "OK",
                "public_ip": "203.0.113.30",
                "_labels": ["CI"],
                "layer": "vpn_hub",
            },
        ]

        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.get_filtered_graph_data.return_value = (raw_nodes, [])

            response = client.get("/api/graph/full")

        assert response.status_code == 200
        node = response.json()["nodes"][0]
        assert node["public_ip"] == "203.0.113.30"
        assert node["metadata"]["public_ip"] == "203.0.113.30"
        mock_repo.get_filtered_graph_data.assert_called_once_with(
            layer=None,
            location=None,
            owner=None,
            allowed_locations=[],
            is_admin=True,
        )

    def test_full_graph_operator_limited_scope_projects_only_scoped_public_ips(self):
        """Limited non-admin /graph/full data never includes out-of-scope public IPs."""
        app.dependency_overrides[get_current_active_user] = lambda: User(
            username="operator",
            role="OPERATOR",
            permissions=[],
            allowed_locations=["HQ-Madrid"],
        )
        raw_nodes = [
            {
                "id": "hub-madrid",
                "name": "Madrid Hub",
                "status": "OK",
                "public_ip": "203.0.113.40",
                "location_name": "HQ-Madrid",
                "_labels": ["CI"],
                "layer": "vpn_hub",
            },
            {
                "id": "hub-private",
                "name": "Private Hub",
                "status": "OK",
                "public_ip": "203.0.113.99",
                "location_name": "Private-Site",
                "_labels": ["CI"],
                "layer": "vpn_hub",
            },
        ]
        scoped_nodes = [
            node for node in raw_nodes if node["location_name"] == "HQ-Madrid"
        ]

        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.get_filtered_graph_data.return_value = (scoped_nodes, [])

            response = client.get("/api/graph/full")

        assert response.status_code == 200
        data = response.json()
        assert [node["id"] for node in data["nodes"]] == ["hub-madrid"]
        assert data["nodes"][0]["public_ip"] == "203.0.113.40"
        assert "203.0.113.99" not in response.text
        mock_repo.get_filtered_graph_data.assert_called_once_with(
            layer=None,
            location=None,
            owner=None,
            allowed_locations=["HQ-Madrid"],
            is_admin=False,
        )

    def test_full_graph_operator_empty_scope_has_no_topology_or_public_ip_leak(self):
        """Empty non-admin scope returns no CIDetailModal topology public_ip data."""
        app.dependency_overrides[get_current_active_user] = lambda: User(
            username="operator",
            role="OPERATOR",
            permissions=[],
            allowed_locations=[],
        )
        out_of_scope_nodes = [
            {
                "id": "hub-private",
                "name": "Private Hub",
                "status": "OK",
                "public_ip": "203.0.113.99",
                "location_name": "Private-Site",
                "_labels": ["CI"],
                "layer": "vpn_hub",
            },
        ]
        out_of_scope_links = [
            {
                "source_node": {"id": "hub-private", "name": "Private Hub"},
                "target_node": {"id": "router-private", "name": "Private Router"},
                "type": "CONNECTS_TO",
                "medium": "vpn",
            },
        ]

        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.get_filtered_graph_data.return_value = (
                out_of_scope_nodes,
                out_of_scope_links,
            )

            response = client.get("/api/graph/full")

        assert response.status_code == 200
        data = response.json()
        assert data == {"nodes": [], "links": []}
        assert "public_ip" not in response.text
        assert "203.0.113.99" not in response.text
        assert "hub-private" not in response.text
        mock_repo.get_filtered_graph_data.assert_not_called()

    def test_full_graph_does_not_change_node_status_or_event_fields(self):
        """Slice 1 / VPN-Rel R4 / Sc 8: existing node status/event fields stay
        untouched after Slice 1 changes."""
        raw_nodes = [
            {
                "id": "ci-001",
                "name": "Router-01",
                "status": "ACTIVE",
                "ip": "10.0.0.1",
                "_labels": ["CI"],
                "layer": "router",
            },
        ]
        raw_links = []

        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.get_filtered_graph_data.return_value = (raw_nodes, raw_links)

            response = client.get("/api/graph/full")

        assert response.status_code == 200
        data = response.json()
        node = data["nodes"][0]
        assert node["status"] == "ACTIVE"
        assert node["type"] == "router"
        # Public IP is a NEW optional field; absence is allowed for legacy CIs.
        assert "public_ip" not in node or node.get("public_ip") in (None, "")
