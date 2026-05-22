"""Integration tests for auth router cookie and refresh token flow."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Patch Neo4j driver BEFORE importing anything
_mock_neo4j_driver = MagicMock()
with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
    from main import app
    from postgres_db import get_pg_db
    from services.auth_service import get_current_active_user
    from models.refresh_token import RefreshTokenResponse


client = TestClient(app)


def _make_mock_pg_user(
    username: str = "testuser",
    role: str = "OPERATOR",
    permissions: list | None = None,
    is_active: bool = True,
    hashed_password: str = "$pbkdf2-sha256$29000$abc",
    tier: str = "T1",
    user_id: int = 1,
):
    """Create a mock SQLAlchemy User object."""
    mock = MagicMock()
    mock.id = user_id
    mock.username = username
    mock.role = role
    mock.tier = tier
    mock.permissions = permissions or []
    mock.is_active = is_active
    mock.hashed_password = hashed_password
    mock.allowed_locations = []
    mock.allowed_ci_types = None
    mock.phone = None
    mock.email = None
    mock.force_password_change = False
    return mock


class TestAuthTokenCookie:
    """Tests for POST /api/auth/token cookie behavior."""

    def test_login_sets_access_token_cookie(self):
        """Login should set HttpOnly cookie on the response."""
        mock_user = _make_mock_pg_user(username="testuser", role="OPERATOR")
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.auth.verify_password", return_value=True):
            response = client.post(
                "/api/auth/token",
                data={"username": "testuser", "password": "correct_password"},
            )

        assert response.status_code == 200
        # Check Set-Cookie header is present
        set_cookie = response.headers.get("set-cookie", "")
        assert "access_token=" in set_cookie
        assert "HttpOnly" in set_cookie or "httpOnly" in set_cookie.lower()
        assert "SameSite=Strict" in set_cookie or "samesite=strict" in set_cookie.lower()

        app.dependency_overrides.pop(get_pg_db, None)


class TestAuthRefresh:
    """Tests for POST /api/auth/refresh endpoint."""

    def test_refresh_returns_new_tokens(self):
        """Refresh should return new access_token and new refresh_token in body."""
        mock_user = _make_mock_pg_user(
            username="testuser",
            role="OPERATOR",
            user_id=42,
        )

        # Mock the refresh token verification to return the user_id
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        # Patch verify_refresh_token to return user_id
        with patch("routers.auth.verify_refresh_token", return_value=42):
            with patch("routers.auth.create_refresh_token", return_value="new_refresh_token"):
                with patch("routers.auth.create_access_token", return_value="new_access_token"):
                    response = client.post(
                        "/api/auth/refresh",
                        content="old_refresh_token",
                    )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["access_token"] == "new_access_token"
        assert data["refresh_token"] == "new_refresh_token"

        app.dependency_overrides.pop(get_pg_db, None)

    def test_refresh_invalid_token_returns_401(self):
        """Invalid refresh token should return 401."""
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.auth.verify_refresh_token", return_value=None):
            response = client.post(
                "/api/auth/refresh",
                content="bad_token",
            )

        assert response.status_code == 401

        app.dependency_overrides.pop(get_pg_db, None)


class TestAuthLogout:
    """Tests for POST /api/auth/logout endpoint."""

    def test_logout_revokes_tokens_and_clears_cookie(self):
        """Logout should revoke all refresh tokens and clear access cookie."""
        mock_db = MagicMock(spec=Session)

        # Set up mock db user with integer id
        mock_db_user = MagicMock()
        mock_db_user.id = 1
        mock_db_user.username = "testuser"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_db_user
        mock_db.query.return_value.filter.return_value.all.return_value = []

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        async def override_get_current_active_user():
            from models.user import User
            return User(
                id=1,
                username="testuser",
                role="OPERATOR",
                permissions=[],
                allowed_locations=[],
            )

        app.dependency_overrides[get_current_active_user] = override_get_current_active_user

        with patch("routers.auth.revoke_all_user_refresh_tokens", return_value=3) as mock_revoke:
            response = client.post("/api/auth/logout")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        mock_revoke.assert_called_once_with(1, mock_db)

        # Cookie should be cleared
        set_cookie = response.headers.get("set-cookie", "")
        assert "access_token=" in set_cookie
        assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie.lower()

        app.dependency_overrides.pop(get_pg_db, None)
        app.dependency_overrides.pop(get_current_active_user, None)