import base64
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from main import app
from models.user import User
from services.auth_service import get_current_active_user
from services.tunnel_health import LinkIdentity, encode_link_id

client = TestClient(app)


def _tunnel_user(role="OPERATOR", allowed_locations=None):
    return User(
        username="operator",
        role=role,
        permissions=["CI_VIEW"],
        allowed_locations=allowed_locations or ["HQ-Madrid"],
    )


@pytest.fixture(autouse=True)
def authenticated_tunnel_user():
    app.dependency_overrides[get_current_active_user] = _tunnel_user
    yield
    app.dependency_overrides.pop(get_current_active_user, None)


def _link_id(medium="vpn"):
    return encode_link_id(
        LinkIdentity(source="hub-a", relationship="CONNECTS_TO", target="edge-b", medium=medium)
    )


def test_get_tunnel_health_returns_latest_health_for_accessible_link():
    with patch("routers.tunnels.topology_repo.get_tunnel_health_link") as mock_get:
        mock_get.return_value = {
            "link_id": _link_id(),
            "source": "hub-a",
            "target": "edge-b",
            "relationship": "CONNECTS_TO",
            "medium": "vpn",
            "status": "UP",
            "authority": {
                "state": "UP",
                "source": "SNMP",
                "observed_at": "2026-07-04T10:00:00Z",
                "reason": "sample",
            },
            "icmp": {"available": True, "latency_ms": 10.0, "error": None, "reason": "sample"},
            "observed_at": "2026-07-04T10:00:01Z",
        }

        response = client.get(f"/api/tunnels/{_link_id()}/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "UP"
    assert data["authority"]["state"] == "UP"
    assert data["icmp"]["available"] is True
    mock_get.assert_called_once_with(
        LinkIdentity(
            source="hub-a",
            relationship="CONNECTS_TO",
            target="edge-b",
            medium="vpn",
        ),
        allowed_locations=["HQ-Madrid"],
        is_admin=False,
    )


def test_get_tunnel_health_rejects_unauthenticated_request_before_repository_lookup():
    app.dependency_overrides.pop(get_current_active_user, None)

    with patch("routers.tunnels.topology_repo.get_tunnel_health_link") as mock_get:
        response = client.get(f"/api/tunnels/{_link_id()}/health")

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"
    mock_get.assert_not_called()


def test_get_tunnel_health_forwards_admin_scope_to_repository():
    app.dependency_overrides[get_current_active_user] = lambda: _tunnel_user(
        role="ADMIN",
        allowed_locations=["HQ-Madrid", "Remote-Site"],
    )

    with patch("routers.tunnels.topology_repo.get_tunnel_health_link") as mock_get:
        mock_get.return_value = {
            "link_id": _link_id(),
            "source": "hub-a",
            "target": "edge-b",
            "relationship": "CONNECTS_TO",
            "medium": "vpn",
            "status": "UP",
            "authority": {"state": "UP", "source": "SNMP", "observed_at": None, "reason": "sample"},
            "icmp": {"available": True, "latency_ms": 10.0, "error": None, "reason": "sample"},
            "observed_at": "2026-07-04T10:00:01Z",
        }

        response = client.get(f"/api/tunnels/{_link_id()}/health")

    assert response.status_code == 200
    mock_get.assert_called_once_with(
        LinkIdentity(
            source="hub-a",
            relationship="CONNECTS_TO",
            target="edge-b",
            medium="vpn",
        ),
        allowed_locations=["HQ-Madrid", "Remote-Site"],
        is_admin=True,
    )


@pytest.mark.parametrize("bad_link_id", ["not-base64", "eyJ1bmtub3duIjoiZmllbGQifQ"])
def test_get_tunnel_health_rejects_malformed_link_id(bad_link_id):
    response = client.get(f"/api/tunnels/{bad_link_id}/health")

    assert response.status_code == 400


def test_get_tunnel_health_rejects_oversized_link_id_before_repository_lookup():
    payload = {
        "source": "hub-a" + ("x" * 600),
        "relationship": "CONNECTS_TO",
        "target": "edge-b",
        "medium": "vpn",
    }
    oversized_link_id = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )

    with patch("routers.tunnels.topology_repo.get_tunnel_health_link") as mock_get:
        response = client.get(f"/api/tunnels/{oversized_link_id}/health")

    assert response.status_code == 400
    mock_get.assert_not_called()


def test_get_tunnel_health_returns_404_for_missing_or_inaccessible_link():
    with patch("routers.tunnels.topology_repo.get_tunnel_health_link", return_value=None):
        response = client.get(f"/api/tunnels/{_link_id()}/health")

    assert response.status_code == 404


def test_get_tunnel_health_preserves_no_sample_response_body():
    with patch("routers.tunnels.topology_repo.get_tunnel_health_link") as mock_get:
        mock_get.return_value = {
            "link_id": _link_id("satellite"),
            "source": "hub-a",
            "target": "edge-b",
            "relationship": "CONNECTS_TO",
            "medium": "satellite",
            "status": "UNKNOWN",
            "authority": {
                "state": None,
                "source": None,
                "observed_at": None,
                "reason": "no_sample",
            },
            "icmp": {"available": False, "latency_ms": None, "error": None, "reason": "no_sample"},
            "observed_at": None,
        }

        response = client.get(f"/api/tunnels/{_link_id('satellite')}/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "UNKNOWN"
    assert data["authority"]["reason"] == "no_sample"
    assert data["icmp"]["reason"] == "no_sample"
    assert data["observed_at"] is None


def test_get_tunnel_health_preserves_missing_public_ip_and_icmp_failure_contexts():
    with patch("routers.tunnels.topology_repo.get_tunnel_health_link") as mock_get:
        mock_get.return_value = {
            "link_id": _link_id(),
            "source": "hub-a",
            "target": "edge-b",
            "relationship": "CONNECTS_TO",
            "medium": "vpn",
            "status": "UP",
            "authority": {"state": "UP", "source": "SNMP", "observed_at": None, "reason": "sample"},
            "icmp": {
                "available": False,
                "latency_ms": None,
                "error": None,
                "reason": "missing_public_ip",
            },
            "observed_at": "2026-07-04T10:00:01Z",
        }

        response = client.get(f"/api/tunnels/{_link_id()}/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "UP"
    assert data["icmp"] == {
        "available": False,
        "latency_ms": None,
        "error": None,
        "reason": "missing_public_ip",
    }
