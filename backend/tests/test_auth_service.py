"""Unit tests for services/auth_service.py — pure logic functions (no DB)."""

from datetime import timedelta
from jose import jwt, JWTError
from services.auth_service import (
    create_access_token,
    check_permission,
    SECRET_KEY,
    ALGORITHM,
)
from models.user import UserPermission, User


class TestCreateAccessToken:
    """Tests for JWT token creation."""

    def test_token_contains_subject(self):
        token = create_access_token(data={"sub": "testuser"})
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == "testuser"

    def test_token_contains_expiration(self):
        token = create_access_token(data={"sub": "testuser"})
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert "exp" in payload

    def test_token_with_custom_expiry(self):
        delta = timedelta(minutes=30)
        token = create_access_token(data={"sub": "testuser"}, expires_delta=delta)
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert "exp" in payload

    def test_token_contains_extra_data(self):
        token = create_access_token(data={"sub": "admin", "role": "ADMIN"})
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["role"] == "ADMIN"

    def test_token_contains_tier_claim(self):
        """JWT should include 'tier' claim when provided."""
        token = create_access_token(
            data={"sub": "admin", "role": "ADMIN", "tier": "T3"}
        )
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["tier"] == "T3"

    def test_token_tier_defaults_fallback(self):
        """When tier is absent from token data, the claim is simply not present (caller provides it)."""
        token = create_access_token(data={"sub": "user1", "role": "OPERATOR"})
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # No tier in data → not present in JWT; get_current_user applies the 'or T1' fallback
        assert payload.get("tier") is None

    def test_token_invalid_after_tampering(self):
        token = create_access_token(data={"sub": "testuser"})
        tampered = token[:-5] + "XXXXX"
        try:
            jwt.decode(tampered, SECRET_KEY, algorithms=[ALGORITHM])
            assert False, "Should have raised an exception"
        except JWTError:
            pass  # Expected


class TestCheckPermission:
    """Tests for the role-based permission checker."""

    def _make_user(self, role: str, permissions: list[UserPermission] | None = None):
        return User(
            username="testuser",
            role=role,
            permissions=permissions or [],
            allowed_locations=[],
        )

    def test_admin_has_all_permissions(self):
        admin = self._make_user("ADMIN")
        for perm in UserPermission:
            assert check_permission(perm, admin) is True

    def test_user_with_explicit_permission(self):
        user = self._make_user("OPERATOR", [UserPermission.EVENT_VIEW])
        assert check_permission(UserPermission.EVENT_VIEW, user) is True

    def test_user_without_permission(self):
        user = self._make_user("VIEWER", [UserPermission.EVENT_VIEW])
        assert check_permission(UserPermission.CI_DELETE, user) is False

    def test_user_with_no_permissions(self):
        user = self._make_user("VIEWER", [])
        assert check_permission(UserPermission.EVENT_ACK, user) is False

    def test_user_with_multiple_permissions(self):
        user = self._make_user(
            "OPERATOR",
            [
                UserPermission.EVENT_VIEW,
                UserPermission.EVENT_ACK,
                UserPermission.CI_VIEW,
            ],
        )
        assert check_permission(UserPermission.EVENT_ACK, user) is True
        assert check_permission(UserPermission.CI_VIEW, user) is True
        assert check_permission(UserPermission.CI_DELETE, user) is False
