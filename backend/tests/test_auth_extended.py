"""Phase 2: Extended auth and permission tests — pure logic + mocked DB.

Focus areas:
- get_current_active_user behavior (disabled users, inactive handling)
- Extended permission scenarios (CUSTOM roles, edge cases, boundary conditions)
- Token validation edge cases (expired tokens, missing claims, invalid formats)
- Auth-related model validation (UserUpdate, UserResetRequest, role enums)
- Permission enforcement patterns (role hierarchy, explicit vs implicit permissions)
"""

from datetime import datetime, timedelta

import pytest
from jose import JWTError, jwt
from models.user import (
    PasswordChangeRequest,
    TokenData,
    User,
    UserPermission,
    UserResetRequest,
    UserRole,
    UserUpdate,
)
from pydantic import ValidationError
from services.auth_service import (
    ALGORITHM,
    SECRET_KEY,
    check_permission,
    create_access_token,
    get_current_active_user,
)

# ---------------------------------------------------------------------------
# Fixtures — extended Phase 2
# ---------------------------------------------------------------------------


@pytest.fixture
def custom_role_user():
    """User with CUSTOM role and explicit permissions."""
    return User(
        username="customuser",
        role="CUSTOM",
        permissions=[UserPermission.EVENT_VIEW, UserPermission.CI_VIEW],
        allowed_locations=["HQ-Madrid"],
        allowed_ci_types=["router"],
    )


@pytest.fixture
def disabled_operator():
    """Disabled operator user."""
    return User(
        username="disabled_op",
        role="OPERATOR",
        permissions=[UserPermission.EVENT_VIEW, UserPermission.EVENT_ACK],
        allowed_locations=[],
        disabled=True,
    )


@pytest.fixture
def viewer_with_no_permissions():
    """Viewer with absolutely no permissions."""
    return User(
        username="blank_viewer",
        role="VIEWER",
        permissions=[],
        allowed_locations=[],
    )


@pytest.fixture
def expired_token(test_secret_key: str) -> str:
    """A JWT token that is already expired."""
    to_encode = {
        "sub": "expired_user",
        "role": "VIEWER",
        "exp": datetime.utcnow() - timedelta(hours=1),
    }
    return jwt.encode(to_encode, test_secret_key, algorithm=ALGORITHM)


@pytest.fixture
def token_without_sub(test_secret_key: str) -> str:
    """A JWT token missing the 'sub' claim."""
    to_encode = {
        "role": "OPERATOR",
        "exp": datetime.utcnow() + timedelta(minutes=15),
    }
    return jwt.encode(to_encode, test_secret_key, algorithm=ALGORITHM)


@pytest.fixture
def token_with_invalid_role(test_secret_key: str) -> str:
    """A JWT token with an invalid role value."""
    to_encode = {
        "sub": "rogue_user",
        "role": "SUPERADMIN",
        "exp": datetime.utcnow() + timedelta(minutes=15),
    }
    return jwt.encode(to_encode, test_secret_key, algorithm=ALGORITHM)


# ---------------------------------------------------------------------------
# Tests: get_current_active_user behavior
# ---------------------------------------------------------------------------


class TestGetCurrentActiveUser:
    """Tests for the active user check decorator/dependency."""

    @pytest.mark.asyncio
    async def test_active_user_returns_user(self):
        """Active user should be returned as-is."""
        active_user = User(
            username="active_user",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_VIEW],
            allowed_locations=[],
            disabled=False,
        )
        result = await get_current_active_user(active_user)
        assert result == active_user
        assert result.disabled is False

    @pytest.mark.asyncio
    async def test_disabled_user_raises_http_400(self):
        """Disabled user should raise HTTPException with 400 status."""
        from fastapi import HTTPException

        disabled_user = User(
            username="disabled_user",
            role="VIEWER",
            permissions=[],
            allowed_locations=[],
            disabled=True,
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(disabled_user)

        assert exc_info.value.status_code == 400
        assert "Inactive user" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_disabled_operator_raises_400(self, disabled_operator):
        """Even operators with permissions get blocked when disabled."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(disabled_operator)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_disabled_admin_raises_400(self):
        """Admins are not exempt from the disabled check."""
        from fastapi import HTTPException

        admin_user = User(
            username="disabled_admin",
            role="ADMIN",
            permissions=[],
            allowed_locations=[],
            disabled=True,
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(admin_user)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_active_user_tier_is_preserved(self):
        """get_current_active_user should preserve tier on the returned user."""
        active_user = User(
            username="tier_user",
            role="OPERATOR",
            permissions=[],
            allowed_locations=[],
            disabled=False,
            tier="T2",
        )
        result = await get_current_active_user(active_user)
        assert result.tier == "T2"

    @pytest.mark.asyncio
    async def test_active_user_default_tier_is_T1(self):
        """When no tier is provided, it should default to 'T1'."""
        active_user = User(
            username="default_tier_user",
            role="VIEWER",
            permissions=[],
            allowed_locations=[],
            disabled=False,
        )
        result = await get_current_active_user(active_user)
        assert result.tier == "T1"


# ---------------------------------------------------------------------------
# Tests: Extended permission scenarios
# ---------------------------------------------------------------------------


class TestExtendedPermissions:
    """Extended permission tests covering edge cases and CUSTOM roles."""

    def test_custom_role_respects_explicit_permissions_only(self, custom_role_user):
        """CUSTOM role users should only have their explicitly assigned permissions."""
        assert check_permission(UserPermission.EVENT_VIEW, custom_role_user) is True
        assert check_permission(UserPermission.CI_VIEW, custom_role_user) is True
        assert check_permission(UserPermission.EVENT_ACK, custom_role_user) is False
        assert check_permission(UserPermission.CI_DELETE, custom_role_user) is False
        assert check_permission(UserPermission.USER_MANAGE, custom_role_user) is False

    def test_custom_role_with_no_permissions_has_none(self):
        """CUSTOM role with empty permissions list should have no access."""
        user = User(
            username="empty_custom",
            role="CUSTOM",
            permissions=[],
            allowed_locations=[],
        )
        for perm in UserPermission:
            assert check_permission(perm, user) is False

    def test_operator_not_admin_does_not_get_all_permissions(self):
        """OPERATOR role should NOT have all permissions like ADMIN."""
        user = User(
            username="operator",
            role="OPERATOR",
            permissions=[],
            allowed_locations=[],
        )
        # OPERATOR with no explicit permissions should fail most checks
        assert check_permission(UserPermission.USER_MANAGE, user) is False
        assert check_permission(UserPermission.CI_DELETE, user) is False
        assert check_permission(UserPermission.ROLE_MANAGE, user) is False

    def test_viewer_with_some_permissions_still_restricted(self):
        """VIEWER with some permissions should still be restricted from admin actions."""
        user = User(
            username="privileged_viewer",
            role="VIEWER",
            permissions=[UserPermission.EVENT_VIEW, UserPermission.CI_VIEW],
            allowed_locations=[],
        )
        assert check_permission(UserPermission.EVENT_VIEW, user) is True
        assert check_permission(UserPermission.CI_VIEW, user) is True
        assert check_permission(UserPermission.CI_EDIT, user) is False
        assert check_permission(UserPermission.USER_MANAGE, user) is False

    def test_admin_with_empty_permissions_still_has_full_access(self):
        """ADMIN role should have full access even with empty permissions list."""
        admin = User(
            username="pure_admin",
            role="ADMIN",
            permissions=[],
            allowed_locations=[],
        )
        for perm in UserPermission:
            assert check_permission(perm, admin) is True

    def test_admin_string_comparison_works(self):
        """Role comparison should work with string 'ADMIN' (not just enum)."""
        user = User(
            username="string_admin",
            role="ADMIN",  # String, not UserRole.ADMIN
            permissions=[],
            allowed_locations=[],
        )
        assert check_permission(UserPermission.USER_MANAGE, user) is True
        assert check_permission(UserPermission.CI_DELETE, user) is True

    def test_all_permissions_covered_by_admin(self):
        """Verify ADMIN has access to ALL defined permissions."""
        admin = User(
            username="full_admin",
            role="ADMIN",
            permissions=[],
            allowed_locations=[],
        )
        permission_count = len(list(UserPermission))
        assert permission_count > 0, "No permissions defined — test is meaningless"

        granted = sum(1 for perm in UserPermission if check_permission(perm, admin))
        assert granted == permission_count

    def test_permission_enum_values_are_unique(self):
        """All permission enum values should be unique strings."""
        values = [perm.value for perm in UserPermission]
        assert len(values) == len(set(values)), "Duplicate permission values found"

    def test_role_enum_values_are_unique(self):
        """All role enum values should be unique strings."""
        values = [role.value for role in UserRole]
        assert len(values) == len(set(values)), "Duplicate role values found"


# ---------------------------------------------------------------------------
# Tests: Token validation edge cases
# ---------------------------------------------------------------------------


class TestTokenEdgeCases:
    """Tests for JWT token edge cases and validation."""

    def test_expired_token_raises_jwt_error(self, expired_token):
        """Expired tokens should raise JWTError when decoded."""
        with pytest.raises(JWTError):
            jwt.decode(expired_token, SECRET_KEY, algorithms=[ALGORITHM])

    def test_token_without_sub_decodes_but_has_no_sub(self, test_secret_key: str):
        """Token missing 'sub' claim should decode but have no subject."""
        to_encode = {
            "role": "OPERATOR",
            "exp": datetime.utcnow() + timedelta(minutes=15),
        }
        token = jwt.encode(to_encode, test_secret_key, algorithm=ALGORITHM)
        payload = jwt.decode(token, test_secret_key, algorithms=[ALGORITHM])
        assert "sub" not in payload or payload.get("sub") is None

    def test_token_with_extra_claims_preserves_them(self, test_secret_key: str):
        """Extra claims in token should be preserved."""
        to_encode = {
            "sub": "test_user",
            "role": "OPERATOR",
            "custom_claim": "custom_value",
            "exp": datetime.utcnow() + timedelta(minutes=15),
        }
        token = jwt.encode(to_encode, test_secret_key, algorithm=ALGORITHM)
        payload = jwt.decode(token, test_secret_key, algorithms=[ALGORITHM])
        assert payload["custom_claim"] == "custom_value"
        assert payload["role"] == "OPERATOR"

    def test_token_with_wrong_secret_raises_error(self, test_secret_key: str):
        """Token signed with wrong secret should fail validation."""
        token = create_access_token(data={"sub": "testuser"})
        with pytest.raises(JWTError):
            jwt.decode(token, "wrong-secret-key", algorithms=[ALGORITHM])

    def test_token_with_wrong_algorithm_raises_error(self, test_secret_key: str):
        """Token decoded with wrong algorithm should fail."""
        token = create_access_token(data={"sub": "testuser"})
        with pytest.raises(JWTError):
            jwt.decode(token, SECRET_KEY, algorithms=["RS256"])

    def test_empty_token_string_raises_error(self):
        """Empty string should raise JWTError."""
        with pytest.raises(JWTError):
            jwt.decode("", SECRET_KEY, algorithms=[ALGORITHM])

    def test_garbage_token_string_raises_error(self):
        """Random string should raise JWTError."""
        with pytest.raises(JWTError):
            jwt.decode("not.a.valid.jwt.token", SECRET_KEY, algorithms=[ALGORITHM])

    def test_token_expiry_boundary_just_valid(self, test_secret_key: str):
        """Token expiring in 1 second should still be valid."""
        to_encode = {
            "sub": "boundary_user",
            "exp": datetime.utcnow() + timedelta(seconds=1),
        }
        token = jwt.encode(to_encode, test_secret_key, algorithm=ALGORITHM)
        payload = jwt.decode(token, test_secret_key, algorithms=[ALGORITHM])
        assert payload["sub"] == "boundary_user"

    def test_token_expiry_boundary_just_expired(self, test_secret_key: str):
        """Token expired 1 second ago should be invalid."""
        to_encode = {
            "sub": "just_expired",
            "exp": datetime.utcnow() - timedelta(seconds=1),
        }
        token = jwt.encode(to_encode, test_secret_key, algorithm=ALGORITHM)
        with pytest.raises(JWTError):
            jwt.decode(token, test_secret_key, algorithms=[ALGORITHM])


# ---------------------------------------------------------------------------
# Tests: Auth-related model validation
# ---------------------------------------------------------------------------


class TestUserUpdateModel:
    """Tests for UserUpdate Pydantic model validation."""

    def test_empty_update_is_valid(self):
        """UserUpdate should allow empty updates (all fields optional)."""
        update = UserUpdate()
        assert update.password is None
        assert update.role is None
        assert update.permissions is None

    def test_partial_update(self):
        """UserUpdate should allow partial updates."""
        update = UserUpdate(role="OPERATOR")
        assert update.role == "OPERATOR"
        assert update.password is None

    def test_full_update(self):
        """UserUpdate should allow full updates."""
        update = UserUpdate(
            password="newpass123",
            role="ADMIN",
            permissions=[UserPermission.EVENT_VIEW],
            allowed_locations=["HQ-Madrid"],
            allowed_ci_types=["router", "switch"],
        )
        assert update.password == "newpass123"
        assert update.role == "ADMIN"
        assert len(update.permissions) == 1

    def test_permissions_update_with_empty_list(self):
        """UserUpdate should accept empty permissions list."""
        update = UserUpdate(permissions=[])
        assert update.permissions == []

    def test_allowed_locations_update(self):
        """UserUpdate should handle allowed_locations."""
        update = UserUpdate(allowed_locations=["Location-A", "Location-B"])
        assert len(update.allowed_locations) == 2


class TestUserResetRequest:
    """Tests for UserResetRequest model validation."""

    def test_valid_reset_request(self):
        """UserResetRequest should accept valid password."""
        req = UserResetRequest(new_password="NewSecureP@ss123")
        assert req.new_password == "NewSecureP@ss123"

    def test_missing_new_password_raises_error(self):
        """UserResetRequest should require new_password."""
        with pytest.raises(ValidationError):
            UserResetRequest()

    def test_empty_string_password_is_valid_model(self):
        """Empty string is technically valid for the model (validation happens elsewhere)."""
        req = UserResetRequest(new_password="")
        assert req.new_password == ""


class TestTokenDataModel:
    """Tests for TokenData model validation."""

    def test_valid_token_data(self):
        """TokenData should accept valid username."""
        data = TokenData(username="testuser")
        assert data.username == "testuser"

    def test_none_username_is_valid(self):
        """TokenData should allow None username (used during validation)."""
        data = TokenData(username=None)
        assert data.username is None

    def test_default_username_is_none(self):
        """TokenData should default to None."""
        data = TokenData()
        assert data.username is None


class TestUserRoleEnum:
    """Tests for UserRole enum values."""

    def test_admin_role_value(self):
        assert UserRole.ADMIN.value == "ADMIN"

    def test_operator_role_value(self):
        assert UserRole.OPERATOR.value == "OPERATOR"

    def test_viewer_role_value(self):
        assert UserRole.VIEWER.value == "VIEWER"

    def test_custom_role_value(self):
        assert UserRole.CUSTOM.value == "CUSTOM"

    def test_all_roles_are_string_compatible(self):
        """All role enum values should be comparable to strings."""
        for role in UserRole:
            assert isinstance(role.value, str)
            assert role.value == role  # str enum comparison


# ---------------------------------------------------------------------------
# Tests: Password change flow validation
# ---------------------------------------------------------------------------


class TestPasswordChangeFlow:
    """Tests for password change request validation and edge cases."""

    def test_valid_password_change_request(self):
        """PasswordChangeRequest should accept valid old and new passwords."""
        req = PasswordChangeRequest(old_password="OldP@ss123", new_password="NewP@ss456")
        assert req.old_password == "OldP@ss123"
        assert req.new_password == "NewP@ss456"

    def test_same_old_and_new_password_is_valid_model(self):
        """Model allows same old/new password (business logic should reject)."""
        req = PasswordChangeRequest(old_password="SamePass123", new_password="SamePass123")
        assert req.old_password == req.new_password

    def test_empty_old_password_is_valid_model(self):
        """Model allows empty strings (validation happens in endpoint)."""
        req = PasswordChangeRequest(old_password="", new_password="NewP@ss123")
        assert req.old_password == ""

    def test_empty_new_password_is_valid_model(self):
        """Model allows empty strings (validation happens in endpoint)."""
        req = PasswordChangeRequest(old_password="OldP@ss123", new_password="")
        assert req.new_password == ""

    def test_missing_both_passwords_raises_error(self):
        """PasswordChangeRequest requires both fields."""
        with pytest.raises(ValidationError):
            PasswordChangeRequest()


# ---------------------------------------------------------------------------
# Tests: Permission boundary and security edge cases
# ---------------------------------------------------------------------------


class TestPermissionSecurity:
    """Security-focused permission tests."""

    def test_case_sensitive_role_check(self):
        """Role check should be case-sensitive — 'admin' != 'ADMIN'."""
        user = User(
            username="lowercase_admin",
            role="admin",  # lowercase
            permissions=[],
            allowed_locations=[],
        )
        # This should NOT grant admin privileges
        assert check_permission(UserPermission.USER_MANAGE, user) is False

    def test_none_permissions_rejected_by_pydantic(self):
        """Pydantic User model rejects None for permissions — must be a list."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            User(
                username="null_perms",
                role="VIEWER",
                permissions=None,
                allowed_locations=[],
            )

    def test_none_permissions_raw_dict_bypass_crashes(self):
        """If permissions is None via raw dict (bypassing Pydantic), check_permission crashes."""
        # Simulate what could happen if data comes directly from DB without Pydantic validation
        raw_user = type(
            "RawUser",
            (),
            {
                "username": "null_perms",
                "role": "VIEWER",
                "permissions": None,
            },
        )()
        with pytest.raises(TypeError):
            check_permission(UserPermission.EVENT_VIEW, raw_user)

    def test_permission_check_with_mixed_role_types(self):
        """Role should work whether it's UserRole enum or string."""
        enum_admin = User(
            username="enum_admin",
            role=UserRole.ADMIN,
            permissions=[],
            allowed_locations=[],
        )
        string_admin = User(
            username="string_admin",
            role="ADMIN",
            permissions=[],
            allowed_locations=[],
        )

        assert check_permission(UserPermission.CI_DELETE, enum_admin) is True
        assert check_permission(UserPermission.CI_DELETE, string_admin) is True

    def test_operator_with_all_permissions_except_one(self):
        """Operator with most permissions should still be restricted."""
        all_perms = list(UserPermission)
        all_perms.remove(UserPermission.USER_MANAGE)

        user = User(
            username="almost_admin",
            role="OPERATOR",
            permissions=all_perms,
            allowed_locations=[],
        )

        # Should have all explicitly granted permissions
        for perm in all_perms:
            assert check_permission(perm, user) is True

        # Should NOT have the one they don't have
        assert check_permission(UserPermission.USER_MANAGE, user) is False

    def test_permission_enum_completeness(self):
        """All permission types should be covered by at least one test."""
        # This ensures we don't miss any new permissions added later
        tested_permissions = {
            UserPermission.EVENT_VIEW,
            UserPermission.EVENT_ACK,
            UserPermission.EVENT_CLOSE,
            UserPermission.EVENT_FORCED_CLOSE,
            UserPermission.CI_VIEW,
            UserPermission.CI_EDIT,
            UserPermission.CI_DELETE,
            UserPermission.RUN_DIAGNOSTICS,
            UserPermission.USER_MANAGE,
            UserPermission.ROLE_MANAGE,
            UserPermission.AUDIT_VIEW,
            UserPermission.METRICS_VIEW,
        }

        defined_permissions = set(UserPermission)
        missing = defined_permissions - tested_permissions
        assert not missing, f"Permissions not covered by tests: {missing}"
