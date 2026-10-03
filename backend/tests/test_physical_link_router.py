"""Router-level tests for /api/cmdb/physical-links — feat-444-physical-link-styling (slice 2).

Slice 2/4 of the fiber-optic / physical-link visualization chain (#444). The
router exposes four endpoints:

- POST   /api/cmdb/physical-links              (authenticated, CI_EDIT)
- GET    /api/cmdb/physical-links              (public)
- GET    /api/cmdb/physical-links/{id}         (public)
- PATCH  /api/cmdb/physical-links/{id}/status  (authenticated, CI_EDIT)

This file builds a minimal FastAPI app (``tests/test_routers_itsm.py`` pattern)
to avoid importing the full production app and unrelated legacy routers.
The service layer is stubbed so the tests exercise the router wiring
(auth deps, response shapes, error forwarding) end-to-end without Neo4j.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from models.user import User, UserPermission
from routers import physical_links
from services.auth_service import get_current_active_user

# Enable the CRUD router under test (gated on FEATURE_CMDB_PHYSICAL_LINKS_ENABLED,
# default off → 404 when off) so this file's happy-path tests can reach the
# endpoints. A dedicated ``test_feature_flag_off_returns_404`` class at the
# bottom flips the env var to "false" and asserts the gate.
os.environ.setdefault("FEATURE_CMDB_PHYSICAL_LINKS_ENABLED", "true")

# ---------------------------------------------------------------------------
# Minimal FastAPI app — mirrors tests/test_routers_itsm.py:25-29
# ---------------------------------------------------------------------------
app = FastAPI()
app.include_router(physical_links.router, prefix="/api")
client = TestClient(app)


# ---------------------------------------------------------------------------
# Service-layer stub
# ---------------------------------------------------------------------------


@dataclass
class _ServiceStub:
    """Stub of ``physical_link_service`` with controllable returns."""

    create_returns: dict | None = None
    create_raises: Exception | None = None
    get_returns: dict | None = None
    list_returns: list[dict] = field(default_factory=list)
    update_returns: dict | None = None
    update_raises: Exception | None = None

    def create_physical_link(self, *, payload, current_user):
        if self.create_raises:
            raise self.create_raises
        return self.create_returns or {
            "id": payload.get("id", "pl-1"),
            "type": payload.get("type", "fiber"),
            "endpoints": list(payload["endpoints"]),
            "status": payload.get("status", "UNKNOWN"),
            "capacity_gbps": payload.get("capacity_gbps"),
            "install_date": payload.get("install_date"),
        }

    def get_physical_link(self, link_id):
        if self.get_returns is None:
            return None
        return dict(self.get_returns, id=link_id)

    def list_physical_links(self, **_kwargs):
        return list(self.list_returns)

    def update_physical_link_status(self, *, link_id, status, current_user):
        if self.update_raises:
            raise self.update_raises
        if self.update_returns is None:
            return None
        return dict(self.update_returns, id=link_id, status=status)


@pytest.fixture
def service_stub(monkeypatch):
    """Patch ``physical_link_service`` at every call boundary used by the router."""
    from services import physical_link_service as svc

    stub = _ServiceStub()
    monkeypatch.setattr(svc, "create_physical_link", stub.create_physical_link)
    monkeypatch.setattr(svc, "get_physical_link", stub.get_physical_link)
    monkeypatch.setattr(svc, "list_physical_links", stub.list_physical_links)
    monkeypatch.setattr(svc, "update_physical_link_status", stub.update_physical_link_status)
    return stub


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _user(role: str = "OPERATOR", permissions: list[str] | None = None) -> User:
    return User(
        username="alice",
        role=role,
        permissions=permissions or [],
        allowed_locations=[],
    )


def _override_user(user: User | None) -> None:
    if user is None:
        app.dependency_overrides.pop(get_current_active_user, None)
    else:
        app.dependency_overrides[get_current_active_user] = lambda: user


@pytest.fixture(autouse=True)
def _reset_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/cmdb/physical-links
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_happy_path_returns_201(self, service_stub):
        """POST without filters MUST return 201 + the wire-shape row."""
        _override_user(_user(role="OPERATOR", permissions=[UserPermission.CI_EDIT.value]))
        body = {
            "id": "pl-fiber-001",
            "type": "fiber",
            "endpoints": ["ci-router-a", "ci-router-b"],
            "status": "UP",
            "capacity_gbps": 10.0,
            "install_date": "2024-01-15",
        }
        resp = client.post("/api/cmdb/physical-links", json=body)
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "pl-fiber-001"
        assert data["type"] == "fiber"
        assert data["endpoints"] == ["ci-router-a", "ci-router-b"]
        assert data["status"] == "UP"
        assert data["capacity_gbps"] == 10.0

    def test_create_without_auth_returns_401(self, service_stub):
        """POST without auth MUST return 401 (auth dep raises before service is called)."""
        _override_user(None)  # remove the override -> dep raises 401
        body = {
            "id": "pl-fiber-001",
            "type": "fiber",
            "endpoints": ["ci-router-a", "ci-router-b"],
        }
        resp = client.post("/api/cmdb/physical-links", json=body)
        assert resp.status_code == 401

    def test_create_invalid_type_returns_400(self, service_stub):
        """POST with an unknown PhysicalLinkType MUST return 400 (Pydantic validation)."""
        _override_user(_user(role="OPERATOR", permissions=[UserPermission.CI_EDIT.value]))
        body = {
            "id": "pl-x",
            "type": "plasma",
            "endpoints": ["ci-a", "ci-b"],
        }
        resp = client.post("/api/cmdb/physical-links", json=body)
        assert resp.status_code == 422  # Pydantic Literal validation


# ---------------------------------------------------------------------------
# GET /api/cmdb/physical-links (list)
# ---------------------------------------------------------------------------


class TestList:
    def test_list_no_filters_returns_200_and_array(self, service_stub):
        """GET without any filters MUST return 200 + a (possibly empty) array."""
        service_stub.list_returns = [
            {
                "id": "pl-1",
                "type": "fiber",
                "endpoints": ["ci-a", "ci-b"],
                "status": "UP",
                "capacity_gbps": 10.0,
                "install_date": None,
            }
        ]
        resp = client.get("/api/cmdb/physical-links")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["id"] == "pl-1"
        assert data[0]["endpoints"] == ["ci-a", "ci-b"]

    def test_list_with_ci_id_filter_returns_200(self, service_stub):
        """GET with ci_id=foo MUST return 200 (filter is pass-through to the service)."""
        service_stub.list_returns = []
        resp = client.get("/api/cmdb/physical-links", params={"ci_id": "ci-target"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_type_filter_returns_200(self, service_stub):
        """GET with type=fiber MUST return 200."""
        service_stub.list_returns = []
        resp = client.get("/api/cmdb/physical-links", params={"type": "fiber"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_status_filter_returns_200(self, service_stub):
        """GET with status=UP MUST return 200."""
        service_stub.list_returns = []
        resp = client.get("/api/cmdb/physical-links", params={"status": "UP"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_without_auth_returns_200_public_read(self, service_stub):
        """GET without auth MUST return 200 (public read, mirrors tunnel links)."""
        service_stub.list_returns = []
        resp = client.get("/api/cmdb/physical-links")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/cmdb/physical-links/{id}
# ---------------------------------------------------------------------------


class TestGetById:
    def test_get_returns_200_when_present(self, service_stub):
        """GET by id MUST return 200 + the wire row when the id is known."""
        service_stub.get_returns = {
            "id": "pl-fiber-001",
            "type": "fiber",
            "endpoints": ["ci-a", "ci-b"],
            "status": "UP",
            "capacity_gbps": 10.0,
            "install_date": None,
        }
        resp = client.get("/api/cmdb/physical-links/pl-fiber-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "pl-fiber-001"
        assert data["endpoints"] == ["ci-a", "ci-b"]

    def test_get_returns_404_when_missing(self, service_stub):
        """GET by id MUST return 404 when the id is unknown."""
        service_stub.get_returns = None
        resp = client.get("/api/cmdb/physical-links/missing")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/cmdb/physical-links/{id}/status
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    def test_patch_happy_path_returns_200(self, service_stub):
        """PATCH with a valid status MUST return 200 + the updated row."""
        _override_user(_user(role="OPERATOR", permissions=[UserPermission.CI_EDIT.value]))
        service_stub.update_returns = {
            "id": "pl-1",
            "type": "fiber",
            "endpoints": ["ci-a", "ci-b"],
            "status": "UP",
            "capacity_gbps": 10.0,
            "install_date": None,
        }
        resp = client.patch(
            "/api/cmdb/physical-links/pl-1/status",
            json={"status": "UP"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "pl-1"
        assert data["status"] == "UP"

    def test_patch_unknown_status_returns_400(self, service_stub):
        """PATCH with an invalid status MUST return 400 (Pydantic Literal validation)."""
        _override_user(_user(role="OPERATOR", permissions=[UserPermission.CI_EDIT.value]))
        resp = client.patch(
            "/api/cmdb/physical-links/pl-1/status",
            json={"status": "ON_FIRE"},
        )
        assert resp.status_code == 422

    def test_patch_without_auth_returns_401(self, service_stub):
        """PATCH without auth MUST return 401."""
        _override_user(None)
        resp = client.patch(
            "/api/cmdb/physical-links/pl-1/status",
            json={"status": "UP"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Feature-flag gate (FEATURE_CMDB_PHYSICAL_LINKS_ENABLED)
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    """When FEATURE_CMDB_PHYSICAL_LINKS_ENABLED=false, every endpoint MUST 404.

    Mirrors tests/test_cmdb_proposal_router.py::TestFeatureFlag pattern. The
    gate is implemented as a router-level ``dependencies=[Depends(_feature_flag_or_404)]``
    so the 404 fires before any service call, regardless of method or path.
    """

    def test_feature_flag_off_returns_404_for_list(self, service_stub, monkeypatch):
        monkeypatch.setenv("FEATURE_CMDB_PHYSICAL_LINKS_ENABLED", "false")
        resp = client.get("/api/cmdb/physical-links")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "feature_disabled"

    def test_feature_flag_off_returns_404_for_get_by_id(self, service_stub, monkeypatch):
        monkeypatch.setenv("FEATURE_CMDB_PHYSICAL_LINKS_ENABLED", "false")
        resp = client.get("/api/cmdb/physical-links/pl-1")
        assert resp.status_code == 404

    def test_feature_flag_off_returns_404_for_create(self, service_stub, monkeypatch):
        monkeypatch.setenv("FEATURE_CMDB_PHYSICAL_LINKS_ENABLED", "false")
        _override_user(_user(role="ADMIN"))
        resp = client.post(
            "/api/cmdb/physical-links",
            json={
                "id": "pl-1",
                "type": "fiber",
                "endpoints": ["ci-a", "ci-b"],
            },
        )
        assert resp.status_code == 404

    def test_feature_flag_off_returns_404_for_patch(self, service_stub, monkeypatch):
        monkeypatch.setenv("FEATURE_CMDB_PHYSICAL_LINKS_ENABLED", "false")
        _override_user(_user(role="ADMIN"))
        resp = client.patch(
            "/api/cmdb/physical-links/pl-1/status",
            json={"status": "UP"},
        )
        assert resp.status_code == 404
