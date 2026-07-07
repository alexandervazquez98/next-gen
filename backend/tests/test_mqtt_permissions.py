import pytest
import seed_roles
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from models.user import User, UserPermission
from services import mqtt_mapping_service


def _make_user(username: str = "operator", role: str = "OPERATOR", permissions=None):
    return User(
        username=username,
        role=role,
        permissions=[p.value if isinstance(p, UserPermission) else p for p in (permissions or [])],
        allowed_locations=[],
    )


def test_require_mqtt_read_denies_without_permission():
    """MQTT read endpoints must fail for users lacking read permission."""

    user = _make_user(permissions=[UserPermission.EVENT_VIEW])

    with pytest.raises(HTTPException) as exc:
        mqtt_mapping_service.require_mqtt_permission("MQTT_READ", user)

    assert exc.value.status_code == 403
    assert exc.value.detail == "Permission denied: MQTT_READ required"


def test_require_mqtt_read_accepts_explicit_mqtt_permission():
    """Explicit enum-backed permission should pass when available."""

    user = _make_user(permissions=[UserPermission.MQTT_READ])

    mqtt_mapping_service.require_mqtt_permission("MQTT_READ", user)


def test_require_mqtt_mapping_manage_denies_without_mapping_permission():
    """MQTT mapping operations must fail for users lacking mapping permission."""

    user = _make_user(permissions=[UserPermission.MQTT_READ])

    with pytest.raises(HTTPException) as exc:
        mqtt_mapping_service.require_mqtt_permission("MQTT_MAPPING_MANAGE", user)

    assert exc.value.status_code == 403
    assert exc.value.detail == "Permission denied: MQTT_MAPPING_MANAGE required"


def test_require_mqtt_mapping_manage_allows_explicit_permission():
    """Mapping-management operations should pass when permission exists."""

    user = _make_user(permissions=[UserPermission.MQTT_MAPPING_MANAGE])

    mqtt_mapping_service.require_mqtt_permission("MQTT_MAPPING_MANAGE", user)


def test_require_mqtt_read_falls_back_to_compatibility_map_on_explicit_missing(monkeypatch):
    """Compatibility mapping is centralized in one fallback map."""

    monkeypatch.setattr(
        mqtt_mapping_service,
        "_supports_explicit_mqtt_permissions",
        lambda: False,
    )

    user = _make_user(permissions=[UserPermission.CI_VIEW])
    mqtt_mapping_service.require_mqtt_permission("MQTT_READ", user)


def test_require_mqtt_mapping_manage_falls_back_to_compatibility_map_on_explicit_missing(
    monkeypatch,
):
    """Fallback must enforce mapping-manage boundary through central constants."""

    monkeypatch.setattr(
        mqtt_mapping_service,
        "_supports_explicit_mqtt_permissions",
        lambda: False,
    )

    user = _make_user(permissions=[UserPermission.CI_EDIT])
    mqtt_mapping_service.require_mqtt_permission("MQTT_MAPPING_MANAGE", user)


def test_require_mqtt_permission_router_negative_path_is_403():
    """Route-style call path returns 403 when boundary is unmet."""

    app = FastAPI()

    def _forbidden_user() -> User:
        return _make_user(permissions=[UserPermission.EVENT_VIEW])

    forbidden_user_dependency = Depends(_forbidden_user)

    @app.get("/mqtt/read")
    def protected_endpoint(current_user: User = forbidden_user_dependency):
        mqtt_mapping_service.require_mqtt_permission("MQTT_READ", current_user)
        return {"ok": True}

    response = TestClient(app).get("/mqtt/read")

    assert response.status_code == 403
    assert response.json()["detail"] == "Permission denied: MQTT_READ required"


class _FakeResult:
    def __init__(self, record):
        self._record = record

    def single(self):
        return self._record


class _SeedRoleSession:
    def __init__(self, existing_roles):
        self.existing_roles = existing_roles
        self.permission_updates = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, **params):
        normalized = " ".join(query.split()).lower()
        role_name = params["name"]

        if normalized.startswith("match (r:role {name: $name}) return r"):
            role = self.existing_roles.get(role_name)
            return _FakeResult({"r": role} if role is not None else None)

        if "set r.permissions" in normalized:
            self.permission_updates.append(
                {
                    "name": role_name,
                    "permissions": params["perms"],
                    "query": normalized,
                }
            )

        return _FakeResult(None)


class _SeedRoleDriver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session


@pytest.mark.asyncio
async def test_reseed_existing_system_operator_adds_mqtt_permissions_without_clobbering_unrelated_permissions(
    monkeypatch,
):
    """Reseeding must upgrade protected OPERATOR roles additively for PR2 MQTT permissions."""

    existing_operator_permissions = [
        UserPermission.EVENT_VIEW.value,
        "CUSTOM_KEEP",
    ]
    session = _SeedRoleSession(
        {
            "OPERATOR": {
                "name": "OPERATOR",
                "description": "Existing protected operator role",
                "permissions": existing_operator_permissions,
                "is_system": True,
            }
        }
    )
    monkeypatch.setattr(seed_roles, "get_db", lambda: _SeedRoleDriver(session))
    monkeypatch.setattr(seed_roles, "close_db", lambda: None)

    await seed_roles.seed_roles()

    operator_updates = [
        update for update in session.permission_updates if update["name"] == "OPERATOR"
    ]
    assert len(operator_updates) == 1
    updated_permissions = operator_updates[0]["permissions"]
    assert UserPermission.MQTT_READ.value in updated_permissions
    assert UserPermission.MQTT_MAPPING_MANAGE.value in updated_permissions
    assert "CUSTOM_KEEP" in updated_permissions
    assert UserPermission.EVENT_VIEW.value in updated_permissions


@pytest.mark.asyncio
async def test_reseed_existing_system_operator_only_adds_explicit_mqtt_upgrade_permissions(
    monkeypatch,
):
    """Protected OPERATOR reseeds must not backfill unrelated missing seeded permissions."""

    session = _SeedRoleSession(
        {
            "OPERATOR": {
                "name": "OPERATOR",
                "description": "Existing protected operator role",
                "permissions": [UserPermission.EVENT_VIEW.value],
                "is_system": True,
            }
        }
    )
    monkeypatch.setattr(seed_roles, "get_db", lambda: _SeedRoleDriver(session))
    monkeypatch.setattr(seed_roles, "close_db", lambda: None)

    await seed_roles.seed_roles()

    operator_update = next(
        update for update in session.permission_updates if update["name"] == "OPERATOR"
    )
    updated_permissions = operator_update["permissions"]

    assert UserPermission.MQTT_READ.value in updated_permissions
    assert UserPermission.MQTT_MAPPING_MANAGE.value in updated_permissions
    assert UserPermission.EVENT_ACK.value not in updated_permissions
    assert UserPermission.CI_EDIT.value not in updated_permissions
    assert UserPermission.RUN_DIAGNOSTICS.value not in updated_permissions
    assert UserPermission.METRICS_VIEW.value not in updated_permissions


@pytest.mark.asyncio
async def test_reseed_existing_system_admin_adds_mqtt_permissions_without_clobbering_unrelated_permissions(
    monkeypatch,
):
    """Reseeding must upgrade protected ADMIN roles additively for PR2 MQTT permissions."""

    existing_admin_permissions = [
        UserPermission.EVENT_VIEW.value,
        "CUSTOM_ADMIN_KEEP",
    ]
    session = _SeedRoleSession(
        {
            "ADMIN": {
                "name": "ADMIN",
                "description": "Existing protected admin role",
                "permissions": existing_admin_permissions,
                "is_system": True,
            }
        }
    )
    monkeypatch.setattr(seed_roles, "get_db", lambda: _SeedRoleDriver(session))
    monkeypatch.setattr(seed_roles, "close_db", lambda: None)

    await seed_roles.seed_roles()

    admin_updates = [update for update in session.permission_updates if update["name"] == "ADMIN"]
    assert len(admin_updates) == 1
    updated_permissions = admin_updates[0]["permissions"]
    assert UserPermission.MQTT_READ.value in updated_permissions
    assert UserPermission.MQTT_MAPPING_MANAGE.value in updated_permissions
    assert "CUSTOM_ADMIN_KEEP" in updated_permissions
    assert UserPermission.EVENT_VIEW.value in updated_permissions


@pytest.mark.asyncio
async def test_reseed_existing_system_admin_only_adds_explicit_mqtt_upgrade_permissions(
    monkeypatch,
):
    """Protected ADMIN reseeds must not backfill all missing admin permissions."""

    session = _SeedRoleSession(
        {
            "ADMIN": {
                "name": "ADMIN",
                "description": "Existing protected admin role",
                "permissions": [UserPermission.EVENT_VIEW.value],
                "is_system": True,
            }
        }
    )
    monkeypatch.setattr(seed_roles, "get_db", lambda: _SeedRoleDriver(session))
    monkeypatch.setattr(seed_roles, "close_db", lambda: None)

    await seed_roles.seed_roles()

    admin_update = next(
        update for update in session.permission_updates if update["name"] == "ADMIN"
    )
    updated_permissions = admin_update["permissions"]

    assert UserPermission.MQTT_READ.value in updated_permissions
    assert UserPermission.MQTT_MAPPING_MANAGE.value in updated_permissions
    assert UserPermission.USER_MANAGE.value not in updated_permissions
    assert UserPermission.ROLE_MANAGE.value not in updated_permissions
    assert UserPermission.AUDIT_VIEW.value not in updated_permissions
    assert UserPermission.CI_DELETE.value not in updated_permissions


@pytest.mark.asyncio
async def test_reseed_existing_system_operator_does_not_overwrite_protected_role_metadata(
    monkeypatch,
):
    """System-role upgrades may add permissions but must not rewrite protected role metadata."""

    session = _SeedRoleSession(
        {
            "OPERATOR": {
                "name": "OPERATOR",
                "description": "Existing protected operator role",
                "permissions": [UserPermission.EVENT_VIEW.value],
                "is_system": True,
            }
        }
    )
    monkeypatch.setattr(seed_roles, "get_db", lambda: _SeedRoleDriver(session))
    monkeypatch.setattr(seed_roles, "close_db", lambda: None)

    await seed_roles.seed_roles()

    operator_update = next(
        update for update in session.permission_updates if update["name"] == "OPERATOR"
    )
    assert "description" not in operator_update["query"]
    assert "is_system" not in operator_update["query"]
