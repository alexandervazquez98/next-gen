"""Router-level tests for catalog endpoints - mocked dependencies.

Focus areas:
- Catalog router has NO authentication. All endpoints are public.
- Happy path coverage for categories, hardware, and owner groups.
- Representative error coverage via mocked service exceptions and validation.

Strategy:
- Patch Neo4j driver BEFORE importing main (avoids real connection at import)
- Use FastAPI TestClient
- Mock routers.catalog.catalog_service for router-level isolation
"""

from unittest.mock import MagicMock, patch

import pytest

from fastapi import HTTPException
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Patch Neo4j driver BEFORE importing anything that touches database.py
# ---------------------------------------------------------------------------
_mock_neo4j_driver = MagicMock()
with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
    from main import app

from models.user import User, UserPermission
from services.auth_service import get_current_active_user


# ---------------------------------------------------------------------------
# TestClient
# ---------------------------------------------------------------------------
client = TestClient(app)


def _make_pydantic_user(
    username: str = "testuser",
    role: str = "OPERATOR",
    permissions: list[UserPermission] | None = None,
) -> User:
    return User(
        username=username,
        role=role,
        permissions=permissions or [],
        allowed_locations=[],
    )


def _override_current_user(user: User) -> None:
    async def override_get_current_active_user():
        return user

    app.dependency_overrides[get_current_active_user] = override_get_current_active_user


def _request(method: str, url: str, json=None, params=None):
    return client.request(method.upper(), url, json=json, params=params)


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    original_overrides = app.dependency_overrides.copy()
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


class TestCategoriesRouter:
    """Tests for category catalog endpoints."""

    def test_get_categories_returns_empty(self):
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.get_categories.return_value = []

            response = client.get("/api/categories")

        assert response.status_code == 200
        assert response.json() == []

    def test_get_categories_returns_data(self):
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.get_categories.return_value = [
                {"name": "Router"},
                {"name": "Switch"},
            ]

            response = client.get("/api/categories")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "Router"

    def test_get_categories_no_auth_required(self):
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.get_categories.return_value = []

            response = client.get("/api/categories")

        assert response.status_code == 200
        assert response.status_code != 401
        assert response.status_code != 403

    @pytest.mark.parametrize(
        ("method", "url", "json"),
        [
            ("post", "/api/categories", {"name": "Router"}),
            ("put", "/api/categories/Router", {"name": "Edge Router"}),
            ("delete", "/api/categories/Router", None),
        ],
    )
    def test_category_mutations_require_authentication(self, method, url, json):
        response = _request(method, url, json=json)

        assert response.status_code == 401

    @pytest.mark.parametrize(
        ("method", "url", "json", "permission"),
        [
            ("post", "/api/categories", {"name": "Router"}, UserPermission.CI_EDIT),
            (
                "put",
                "/api/categories/Router",
                {"name": "Edge Router"},
                UserPermission.CI_EDIT,
            ),
            ("delete", "/api/categories/Router", None, UserPermission.CI_DELETE),
        ],
    )
    def test_category_mutations_require_permissions(
        self, method, url, json, permission
    ):
        _override_current_user(_make_pydantic_user())

        response = _request(method, url, json=json)

        assert response.status_code == 403

        _override_current_user(_make_pydantic_user(permissions=[permission]))
        with patch("routers.catalog.catalog_service") as mock_service:
            if method == "post":
                mock_service.create_category.return_value = {"message": "ok"}
            elif method == "put":
                mock_service.update_category.return_value = {"message": "ok"}
            else:
                mock_service.delete_category.return_value = {"message": "ok"}

            success_response = _request(method, url, json=json)

        assert success_response.status_code == 200

    def test_create_category_success(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.create_category.return_value = {"message": "Category created"}

            response = client.post("/api/categories", json={"name": "Router"})

        assert response.status_code == 200
        assert response.json()["message"] == "Category created"
        sent_category = mock_service.create_category.call_args.args[0]
        assert sent_category.name == "Router"

    def test_create_category_conflict(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.create_category.side_effect = HTTPException(
                status_code=409,
                detail="Category already exists",
            )

            response = client.post("/api/categories", json={"name": "Router"})

        assert response.status_code == 409
        assert response.json()["detail"] == "Category already exists"

    def test_create_category_validation_error(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        response = client.post("/api/categories", json={})

        assert response.status_code == 422

    def test_delete_category_success(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_DELETE])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.delete_category.return_value = {"message": "Category deleted"}

            response = client.delete("/api/categories/Router")

        assert response.status_code == 200
        assert response.json()["message"] == "Category deleted"
        mock_service.delete_category.assert_called_once_with("Router")

    def test_update_category_success(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.update_category.return_value = {"message": "Category updated"}

            response = client.put(
                "/api/categories/Router",
                json={"name": "Edge Router"},
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Category updated"
        mock_service.update_category.assert_called_once_with("Router", "Edge Router")

    def test_get_category_usage_success(self):
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.get_category_usage.return_value = {"count": 4}

            response = client.get("/api/categories/Router/usage")

        assert response.status_code == 200
        assert response.json() == {"count": 4}
        mock_service.get_category_usage.assert_called_once_with("Router")


class TestHardwareRouter:
    """Tests for hardware catalog endpoints."""

    def test_get_hardware_catalog_returns_empty(self):
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.get_hardware_catalog.return_value = []

            response = client.get("/api/hardware")

        assert response.status_code == 200
        assert response.json() == []

    def test_get_hardware_catalog_returns_data(self):
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.get_hardware_catalog.return_value = [
                {
                    "brand": "Cisco",
                    "model": "ASR-1000",
                    "category": "Router",
                    "owner": "NetOps",
                }
            ]

            response = client.get("/api/hardware")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["brand"] == "Cisco"
        assert data[0]["model"] == "ASR-1000"

    @pytest.mark.parametrize(
        ("method", "url", "json", "params"),
        [
            (
                "post",
                "/api/hardware",
                {
                    "brand": "Cisco",
                    "model": "ASR-1000",
                    "category": "Router",
                    "owner": "NetOps",
                },
                None,
            ),
            ("put", "/api/hardware/Cisco/ASR-1000", {"category": "Router"}, None),
            ("delete", "/api/hardware/Cisco/ASR-1000", None, None),
            (
                "post",
                "/api/hardware/assign_metric",
                None,
                {"brand": "Cisco", "model": "ASR-1000", "metric_id": "cpu-load"},
            ),
            (
                "post",
                "/api/hardware/unassign_metric",
                None,
                {"brand": "Cisco", "model": "ASR-1000", "metric_id": "cpu-load"},
            ),
        ],
    )
    def test_hardware_mutations_require_authentication(self, method, url, json, params):
        response = _request(method, url, json=json, params=params)

        assert response.status_code == 401

    @pytest.mark.parametrize(
        ("method", "url", "json", "params", "permission"),
        [
            (
                "post",
                "/api/hardware",
                {
                    "brand": "Cisco",
                    "model": "ASR-1000",
                    "category": "Router",
                    "owner": "NetOps",
                },
                None,
                UserPermission.CI_EDIT,
            ),
            (
                "put",
                "/api/hardware/Cisco/ASR-1000",
                {"category": "Router"},
                None,
                UserPermission.CI_EDIT,
            ),
            (
                "delete",
                "/api/hardware/Cisco/ASR-1000",
                None,
                None,
                UserPermission.CI_DELETE,
            ),
            (
                "post",
                "/api/hardware/assign_metric",
                None,
                {"brand": "Cisco", "model": "ASR-1000", "metric_id": "cpu-load"},
                UserPermission.CI_EDIT,
            ),
            (
                "post",
                "/api/hardware/unassign_metric",
                None,
                {"brand": "Cisco", "model": "ASR-1000", "metric_id": "cpu-load"},
                UserPermission.CI_EDIT,
            ),
        ],
    )
    def test_hardware_mutations_require_permissions(
        self, method, url, json, params, permission
    ):
        _override_current_user(_make_pydantic_user())

        response = _request(method, url, json=json, params=params)

        assert response.status_code == 403

        _override_current_user(_make_pydantic_user(permissions=[permission]))
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.create_hardware_model.return_value = {"message": "ok"}
            mock_service.update_hardware_model.return_value = {"message": "ok"}
            mock_service.delete_hardware_model.return_value = {"message": "ok"}
            mock_service.assign_metric_to_model.return_value = {"message": "ok"}
            mock_service.unassign_metric_from_model.return_value = {"message": "ok"}

            success_response = _request(method, url, json=json, params=params)

        assert success_response.status_code == 200

    def test_create_hardware_model_success(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.create_hardware_model.return_value = {
                "message": "Hardware Model saved"
            }

            response = client.post(
                "/api/hardware",
                json={
                    "brand": "Cisco",
                    "model": "ASR-1000",
                    "category": "Router",
                    "owner": "NetOps",
                },
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Hardware Model saved"
        sent_item = mock_service.create_hardware_model.call_args.args[0]
        assert sent_item.brand == "Cisco"
        assert sent_item.model == "ASR-1000"
        assert sent_item.category == "Router"
        assert sent_item.owner == "NetOps"

    def test_create_hardware_model_validation_error(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        response = client.post("/api/hardware", json={"brand": "Cisco"})

        assert response.status_code == 422

    def test_delete_hardware_model_success(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_DELETE])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.delete_hardware_model.return_value = {
                "message": "Hardware Model deleted"
            }

            response = client.delete("/api/hardware/Cisco/ASR-1000")

        assert response.status_code == 200
        assert response.json()["message"] == "Hardware Model deleted"
        mock_service.delete_hardware_model.assert_called_once_with("Cisco", "ASR-1000")

    def test_update_hardware_model_success(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.update_hardware_model.return_value = {
                "message": "Hardware Model updated"
            }

            response = client.put(
                "/api/hardware/Cisco/ASR-1000",
                json={
                    "brand": "Cisco",
                    "model": "ASR-1000-X",
                    "category": "Router",
                    "owner": "CoreOps",
                },
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Hardware Model updated"
        old_brand, old_model, hw_update = (
            mock_service.update_hardware_model.call_args.args
        )
        assert old_brand == "Cisco"
        assert old_model == "ASR-1000"
        assert hw_update.brand == "Cisco"
        assert hw_update.model == "ASR-1000-X"
        assert hw_update.category == "Router"
        assert hw_update.owner == "CoreOps"

    def test_update_hardware_model_uses_path_defaults(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.update_hardware_model.return_value = {
                "message": "Hardware Model updated"
            }

            response = client.put(
                "/api/hardware/Cisco/ASR-1000",
                json={"category": "Router"},
            )

        assert response.status_code == 200
        _, _, hw_update = mock_service.update_hardware_model.call_args.args
        assert hw_update.brand == "Cisco"
        assert hw_update.model == "ASR-1000"
        assert hw_update.category == "Router"
        assert hw_update.owner is None

    def test_update_hardware_model_not_found(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.update_hardware_model.side_effect = HTTPException(
                status_code=404,
                detail="Hardware model not found",
            )

            response = client.put(
                "/api/hardware/Cisco/ASR-404",
                json={"owner": "NetOps"},
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Hardware model not found"

    def test_get_hardware_usage_success(self):
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.get_hardware_usage.return_value = {"count": 7}

            response = client.get("/api/hardware/Cisco/ASR-1000/usage")

        assert response.status_code == 200
        assert response.json() == {"count": 7}
        mock_service.get_hardware_usage.assert_called_once_with("Cisco", "ASR-1000")

    def test_assign_metric_to_model_success(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.assign_metric_to_model.return_value = {
                "message": "Metric assigned to model"
            }

            response = client.post(
                "/api/hardware/assign_metric",
                params={"brand": "Cisco", "model": "ASR-1000", "metric_id": "cpu-load"},
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Metric assigned to model"
        mock_service.assign_metric_to_model.assert_called_once_with(
            "Cisco", "ASR-1000", "cpu-load"
        )

    def test_unassign_metric_from_model_success(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.unassign_metric_from_model.return_value = {
                "message": "Metric unassigned from model"
            }

            response = client.post(
                "/api/hardware/unassign_metric",
                params={"brand": "Cisco", "model": "ASR-1000", "metric_id": "cpu-load"},
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Metric unassigned from model"
        mock_service.unassign_metric_from_model.assert_called_once_with(
            "Cisco", "ASR-1000", "cpu-load"
        )

    def test_assign_metric_requires_query_params(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        response = client.post("/api/hardware/assign_metric", params={"brand": "Cisco"})

        assert response.status_code == 422


class TestOwnersRouter:
    """Tests for owner group catalog endpoints."""

    def test_get_owners_returns_empty(self):
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.get_owners.return_value = []

            response = client.get("/api/owners")

        assert response.status_code == 200
        assert response.json() == []

    def test_get_owners_returns_data(self):
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.get_owners.return_value = [
                {
                    "name": "NetOps",
                    "users": [
                        {
                            "name": "alice",
                            "email": "alice@example.com",
                            "phone": "+541100000000",
                        }
                    ],
                }
            ]

            response = client.get("/api/owners")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "NetOps"
        assert data[0]["users"][0]["name"] == "alice"

    @pytest.mark.parametrize(
        ("method", "url", "json"),
        [
            ("post", "/api/owners", {"name": "NetOps", "users": []}),
            ("put", "/api/owners/NetOps", {"name": "CoreOps"}),
            ("delete", "/api/owners/NetOps", None),
            (
                "post",
                "/api/owners/NetOps/users",
                {
                    "username": "alice",
                    "role": "VIEWER",
                    "permissions": [],
                    "allowed_locations": [],
                },
            ),
            ("delete", "/api/owners/NetOps/users/alice", None),
        ],
    )
    def test_owner_mutations_require_authentication(self, method, url, json):
        response = _request(method, url, json=json)

        assert response.status_code == 401

    @pytest.mark.parametrize(
        ("method", "url", "json", "permission"),
        [
            (
                "post",
                "/api/owners",
                {"name": "NetOps", "users": []},
                UserPermission.CI_EDIT,
            ),
            ("put", "/api/owners/NetOps", {"name": "CoreOps"}, UserPermission.CI_EDIT),
            ("delete", "/api/owners/NetOps", None, UserPermission.CI_DELETE),
            (
                "post",
                "/api/owners/NetOps/users",
                {
                    "username": "alice",
                    "role": "VIEWER",
                    "permissions": [],
                    "allowed_locations": [],
                },
                UserPermission.CI_EDIT,
            ),
            (
                "delete",
                "/api/owners/NetOps/users/alice",
                None,
                UserPermission.CI_DELETE,
            ),
        ],
    )
    def test_owner_mutations_require_permissions(self, method, url, json, permission):
        _override_current_user(_make_pydantic_user())

        response = _request(method, url, json=json)

        assert response.status_code == 403

        _override_current_user(_make_pydantic_user(permissions=[permission]))
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.create_owner_group.return_value = {"message": "ok"}
            mock_service.update_owner_group.return_value = {"message": "ok"}
            mock_service.delete_owner_group.return_value = {"message": "ok"}
            mock_service.link_user_to_group.return_value = {"message": "ok"}
            mock_service.unlink_user_from_group.return_value = {"message": "ok"}

            success_response = _request(method, url, json=json)

        assert success_response.status_code == 200

    def test_create_owner_group_success(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.create_owner_group.return_value = {
                "message": "Owner Group created/updated"
            }

            response = client.post(
                "/api/owners",
                json={
                    "name": "NetOps",
                    "users": [
                        {
                            "name": "alice",
                            "email": "alice@example.com",
                            "phone": "+541100000000",
                        }
                    ],
                },
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Owner Group created/updated"
        sent_group = mock_service.create_owner_group.call_args.args[0]
        assert sent_group.name == "NetOps"
        assert sent_group.users[0]["name"] == "alice"

    def test_delete_owner_group_success(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_DELETE])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.delete_owner_group.return_value = {
                "message": "Owner Group deleted"
            }

            response = client.delete("/api/owners/NetOps")

        assert response.status_code == 200
        assert response.json()["message"] == "Owner Group deleted"
        mock_service.delete_owner_group.assert_called_once_with("NetOps")

    def test_update_owner_group_success_with_users(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.update_owner_group.return_value = {
                "message": "Owner Group updated"
            }

            response = client.put(
                "/api/owners/NetOps",
                json={
                    "name": "CoreOps",
                    "users": [
                        {
                            "name": "bob",
                            "email": "bob@example.com",
                            "phone": "+541122233344",
                        }
                    ],
                },
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Owner Group updated"
        old_name, owner_update = mock_service.update_owner_group.call_args.args
        assert old_name == "NetOps"
        assert owner_update.name == "CoreOps"
        assert owner_update.users[0]["name"] == "bob"

    def test_update_owner_group_preserves_users_as_none_when_omitted(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.update_owner_group.return_value = {
                "message": "Owner Group updated"
            }

            response = client.put(
                "/api/owners/NetOps",
                json={"name": "CoreOps"},
            )

        assert response.status_code == 200
        _, owner_update = mock_service.update_owner_group.call_args.args
        assert owner_update.name == "CoreOps"
        assert owner_update.users is None

    def test_get_owner_usage_success(self):
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.get_owner_usage.return_value = {"count": 3, "user_count": 2}

            response = client.get("/api/owners/NetOps/usage")

        assert response.status_code == 200
        assert response.json() == {"count": 3, "user_count": 2}
        mock_service.get_owner_usage.assert_called_once_with("NetOps")

    def test_link_user_to_group_success(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.link_user_to_group.return_value = {
                "message": "User linked to group"
            }

            response = client.post(
                "/api/owners/NetOps/users",
                json={
                    "username": "alice",
                    "role": "VIEWER",
                    "permissions": [],
                    "allowed_locations": [],
                    "email": "alice@example.com",
                    "phone": "+541100000000",
                },
            )

        assert response.status_code == 200
        assert response.json()["message"] == "User linked to group"
        mock_service.link_user_to_group.assert_called_once_with(
            "NetOps",
            {
                "username": "alice",
                "role": "VIEWER",
                "permissions": [],
                "allowed_locations": [],
                "allowed_ci_types": None,
                "phone": "+541100000000",
                "email": "alice@example.com",
                "tier": "T1",
                "disabled": False,
                "force_password_change": False,
            },
        )

    def test_link_user_to_group_validation_error(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        response = client.post(
            "/api/owners/NetOps/users",
            json={"role": "VIEWER"},
        )

        assert response.status_code == 422

    def test_link_user_to_group_not_found(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.link_user_to_group.side_effect = HTTPException(
                status_code=404,
                detail="Owner group not found",
            )

            response = client.post(
                "/api/owners/MissingGroup/users",
                json={
                    "username": "alice",
                    "role": "VIEWER",
                    "permissions": [],
                    "allowed_locations": [],
                },
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Owner group not found"

    def test_unlink_user_from_group_success(self):
        _override_current_user(
            _make_pydantic_user(permissions=[UserPermission.CI_DELETE])
        )
        with patch("routers.catalog.catalog_service") as mock_service:
            mock_service.unlink_user_from_group.return_value = {
                "message": "User unlinked from group"
            }

            response = client.delete("/api/owners/NetOps/users/alice")

        assert response.status_code == 200
        assert response.json()["message"] == "User unlinked from group"
        mock_service.unlink_user_from_group.assert_called_once_with("NetOps", "alice")
