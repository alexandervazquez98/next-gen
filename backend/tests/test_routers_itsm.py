"""Router-level tests for ITSM service catalog and ticket endpoints.

Focus:
- Explicit permission gates on read/write endpoints
- Route wiring and payload pass-through for create/get/update/deactivate/transition
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from models.user import User, UserPermission
from routers import itsm_service_catalog, ticket_folios
from services.auth_service import get_current_active_user

# ---------------------------------------------------------------------------
# Build a focused FastAPI app containing only ITSM routers under test.
# This avoids importing the full production app and unrelated legacy routers
# that may require broader Python-version compatibility workarounds.
# ---------------------------------------------------------------------------
app = FastAPI()
app.include_router(itsm_service_catalog.router, prefix="/api")
app.include_router(ticket_folios.router, prefix="/api")


# ---------------------------------------------------------------------------
# TestClient
# ---------------------------------------------------------------------------
client = TestClient(app)

READ_PERMISSION = UserPermission.ITSM_VIEW
WRITE_PERMISSION = UserPermission.ITSM_EDIT


def _make_pydantic_user(
    username: str = "testuser",
    role: str = "OPERATOR",
    permissions: list[UserPermission] | None = None,
) -> User:
    return User(
        username=username,
        role=role,
        permissions=[permission.value if isinstance(permission, UserPermission) else permission for permission in (permissions or [])],
        allowed_locations=[],
    )


def _override_current_user(user: User) -> None:
    async def override_get_current_active_user():
        return user

    app.dependency_overrides[get_current_active_user] = override_get_current_active_user


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    original_overrides = app.dependency_overrides.copy()
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


class TestItsmServiceCatalogRouter:
    """Permissioned route coverage for /api/itsm/service-catalog."""

    def test_list_catalogs_requires_authentication(self):
        response = client.get("/api/itsm/service-catalog")
        assert response.status_code == 401

    @pytest.mark.parametrize("method,url", [("get", "/api/itsm/service-catalog")])
    def test_read_routes_require_read_permission(self, method, url):
        _override_current_user(_make_pydantic_user())

        response = client.request(method, url)
        assert response.status_code == 403

    def test_read_catalogs_with_read_permission_calls_service(self):
        _override_current_user(_make_pydantic_user(permissions=[READ_PERMISSION]))

        with patch("routers.itsm_service_catalog.service_catalog_service") as mock_service:
            mock_service.list_service_catalogs.return_value = [
                {"service_id": "svc-1", "name": "Ops"}
            ]

            response = client.get("/api/itsm/service-catalog")

        assert response.status_code == 200
        assert response.json() == [{"service_id": "svc-1", "name": "Ops"}]
        mock_service.list_service_catalogs.assert_called_once_with(limit=100)

    def test_write_catalog_routes_require_write_permission(self):
        _override_current_user(_make_pydantic_user(permissions=[READ_PERMISSION]))

        response = client.post(
            "/api/itsm/service-catalog",
            json={"service_id": "svc-new", "name": "Core", "sla_target_minutes": 45},
        )
        assert response.status_code == 403

        response = client.put(
            "/api/itsm/service-catalog/svc-1",
            json={"name": "Changed"},
        )
        assert response.status_code == 403

        response = client.post("/api/itsm/service-catalog/svc-1/deactivate")
        assert response.status_code == 403

    def test_catalog_routes_reject_inventory_event_permissions(self):
        for endpoint, method, permissions in [
            ("/api/itsm/service-catalog", "get", [UserPermission.CI_VIEW]),
            ("/api/itsm/service-catalog", "post", [UserPermission.CI_EDIT]),
            ("/api/itsm/service-catalog/svc-1", "get", [UserPermission.CI_VIEW]),
            ("/api/itsm/service-catalog/svc-1", "put", [UserPermission.CI_EDIT]),
            ("/api/itsm/service-catalog/svc-1/deactivate", "post", [UserPermission.EVENT_VIEW]),
        ]:
            _override_current_user(_make_pydantic_user(permissions=permissions))
            payload = {"service_id": "svc-new", "name": "Core", "sla_target_minutes": 45}

            if method == "get":
                response = client.get(endpoint)
            elif method == "post":
                if endpoint.endswith("/deactivate"):
                    response = client.post(endpoint)
                else:
                    response = client.post(endpoint, json=payload)
            elif method == "put":
                response = client.put(endpoint, json={"name": "Changed"})

            assert response.status_code == 403

    def test_create_catalog_with_write_permission_passes_payload(self):
        _override_current_user(_make_pydantic_user(permissions=[WRITE_PERMISSION]))

        with patch("routers.itsm_service_catalog.service_catalog_service") as mock_service:
            mock_service.create_service_catalog.return_value = {
                "service_id": "svc-new",
                "name": "Core",
                "active": True,
            }

            response = client.post(
                "/api/itsm/service-catalog",
                json={"service_id": "svc-new", "name": "Core", "sla_target_minutes": 45},
            )

        assert response.status_code == 200
        assert response.json()["service_id"] == "svc-new"
        created_payload = mock_service.create_service_catalog.call_args.args[0]
        assert created_payload.service_id == "svc-new"

    def test_update_and_deactivate_catalog_with_write_permission(self):
        _override_current_user(_make_pydantic_user(permissions=[WRITE_PERMISSION]))

        with patch("routers.itsm_service_catalog.service_catalog_service") as mock_service:
            mock_service.update_service_catalog.return_value = {
                "service_id": "svc-1",
                "name": "Updated",
            }
            mock_service.deactivate_service_catalog.return_value = {
                "service_id": "svc-1",
                "active": False,
            }

            put_response = client.put(
                "/api/itsm/service-catalog/svc-1",
                json={"name": "Updated"},
            )
            deactivate_response = client.post("/api/itsm/service-catalog/svc-1/deactivate")

        assert put_response.status_code == 200
        assert deactivate_response.status_code == 200
        mock_service.update_service_catalog.assert_called_once()
        mock_service.deactivate_service_catalog.assert_called_once_with("svc-1", actor="testuser")


class TestItsmTicketRouter:
    """Permissioned route coverage for /api/itsm/tickets."""

    def test_ticket_read_routes_require_read_permission(self):
        _override_current_user(_make_pydantic_user())
        response = client.get("/api/itsm/tickets")
        assert response.status_code == 403

        response = client.get("/api/itsm/tickets/TK-1")
        assert response.status_code == 403

    def test_ticket_write_routes_require_write_permission(self):
        _override_current_user(_make_pydantic_user(permissions=[READ_PERMISSION]))

        response = client.post(
            "/api/itsm/tickets",
            json={"ticket_id": "TK-1", "type": "request", "title": "Access"},
        )
        assert response.status_code == 403

        response = client.put(
            "/api/itsm/tickets/TK-1",
            json={"title": "Changed"},
        )
        assert response.status_code == 403

        response = client.post(
            "/api/itsm/tickets/TK-1/transition",
            json={"next_status": "in_progress"},
        )
        assert response.status_code == 403

    def test_ticket_routes_reject_catalog_or_event_permissions(self):
        for endpoint, method, permissions in [
            ("/api/itsm/tickets", "get", [UserPermission.CI_VIEW]),
            ("/api/itsm/tickets/TK-1", "get", [UserPermission.EVENT_VIEW]),
            ("/api/itsm/tickets", "post", [UserPermission.CI_EDIT]),
            ("/api/itsm/tickets/TK-1", "put", [UserPermission.CI_EDIT]),
            ("/api/itsm/tickets/TK-1/transition", "post", [UserPermission.EVENT_CLOSE]),
        ]:
            _override_current_user(_make_pydantic_user(permissions=permissions))

            if method == "get":
                response = client.get(endpoint)
            elif method == "post":
                if endpoint.endswith("/transition"):
                    response = client.post(endpoint, json={"next_status": "in_progress"})
                else:
                    response = client.post(endpoint, json={"ticket_id": "TK-1", "type": "request", "title": "Access"})
            elif method == "put":
                response = client.put(endpoint, json={"title": "Changed"})

            assert response.status_code == 403

    def test_ticket_read_with_permission_calls_service(self):
        _override_current_user(_make_pydantic_user(permissions=[READ_PERMISSION]))

        with patch("routers.ticket_folios.ticket_folio_service") as mock_service:
            mock_service.list_ticket_folios.return_value = [
                {"ticket_id": "TK-1", "type": "request", "status": "open"}
            ]

            response = client.get("/api/itsm/tickets")

        assert response.status_code == 200
        assert response.json() == [{"ticket_id": "TK-1", "type": "request", "status": "open"}]
        mock_service.list_ticket_folios.assert_called_once_with(
            status=None,
            service_catalog_id=None,
            archived=None,
            limit=100,
        )

    def test_ticket_mutations_pass_actor_and_payload(self):
        _override_current_user(_make_pydantic_user(permissions=[WRITE_PERMISSION]))

        with patch("routers.ticket_folios.ticket_folio_service") as mock_service:
            mock_service.create_ticket_folio.return_value = {
                "ticket_id": "TK-1",
                "status": "open",
            }
            mock_service.update_ticket_folio.return_value = {
                "ticket_id": "TK-1",
                "title": "Escalated",
            }
            mock_service.transition_ticket_folio.return_value = {
                "ticket_id": "TK-1",
                "status": "in_progress",
            }

            response_create = client.post(
                "/api/itsm/tickets",
                json={"ticket_id": "TK-1", "type": "request", "title": "Access"},
            )
            response_update = client.put("/api/itsm/tickets/TK-1", json={"title": "Escalated"})
            response_transition = client.post(
                "/api/itsm/tickets/TK-1/transition",
                json={"next_status": "in_progress"},
            )

        assert response_create.status_code == 200
        assert response_update.status_code == 200
        assert response_transition.status_code == 200
        create_payload = mock_service.create_ticket_folio.call_args
        assert create_payload.args[0].ticket_id == "TK-1"
        assert create_payload.kwargs["actor"] == "testuser"

        update_payload = mock_service.update_ticket_folio.call_args
        assert update_payload.args[0] == "TK-1"
        assert update_payload.args[1].title == "Escalated"
        assert update_payload.kwargs["actor"] == "testuser"

        transition_payload = mock_service.transition_ticket_folio.call_args
        assert transition_payload.args[0] == "TK-1"
        assert transition_payload.kwargs["next_status"] == "in_progress"
        assert transition_payload.kwargs["actor"] == "testuser"

        assert mock_service.create_ticket_folio.called
        assert mock_service.update_ticket_folio.called
        assert mock_service.transition_ticket_folio.called
