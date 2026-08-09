"""Router tests for POST /api/users/{username}/deactivate (PR 3 — WU3)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from models.user import User, UserPermission
from repositories.user_repo import UserRepository
from routers import users as users_router
from services.auth_service import get_current_active_user


app = FastAPI()
app.include_router(users_router.router, prefix="/api")
client = TestClient(app)


def _override_user(perms):
    async def _dep():
        return User(
            username="admin",
            role="ADMIN",
            permissions=[p.value for p in (perms or [])],
            allowed_locations=[],
        )

    app.dependency_overrides[get_current_active_user] = _dep


@pytest.fixture(autouse=True)
def _clear_overrides():
    saved = app.dependency_overrides.copy()
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


def test_deactivate_requires_auth():
    response = client.post("/api/users/op1/deactivate")
    assert response.status_code == 401


def test_deactivate_requires_user_manage_permission():
    _override_user([])
    response = client.post("/api/users/op1/deactivate")
    assert response.status_code == 403


def test_deactivate_returns_204_on_success():
    _override_user([UserPermission.USER_MANAGE])

    with patch.object(UserRepository, "deactivate") as mock_deact:
        mock_deact.return_value = MagicMock(is_active=False)
        response = client.post("/api/users/op1/deactivate")

    assert response.status_code == 204
    mock_deact.assert_called_once()
    assert mock_deact.call_args.args[1] == "op1"


def test_deactivate_missing_returns_404():
    _override_user([UserPermission.USER_MANAGE])

    with patch.object(UserRepository, "deactivate", return_value=None):
        response = client.post("/api/users/ghost/deactivate")

    assert response.status_code == 404


def test_deactivate_already_inactive_returns_409():
    _override_user([UserPermission.USER_MANAGE])

    with patch.object(
        UserRepository,
        "deactivate",
        side_effect=HTTPException(status_code=409, detail="user_already_inactive"),
    ):
        response = client.post("/api/users/op1/deactivate")

    assert response.status_code == 409
