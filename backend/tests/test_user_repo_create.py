"""Tests for user_repo.create_user — verifies the fix for accessing
non-existent fields (disabled, force_password_change) on UserCreate.

Bug: user_repo.create_user accessed user.disabled and
user.force_password_change which don't exist on UserCreate (they only
exist on the User response model). This caused AttributeError at runtime
whenever a new user was created via POST /api/users/.

Fix: Hardcode is_active=True and force_password_change=False in
create_user, since UserCreate has no fields for these concepts.
"""

from unittest.mock import MagicMock, patch

# Patch Neo4j before importing main
_mock_neo4j_driver = MagicMock()
with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
    from models.refresh_token import RefreshToken  # noqa: F401 - register SQLAlchemy relationship
    from models.user import UserCreate, UserPermission, UserUpdate
    from repositories import user_repo


class TestUserCreateModelFields:
    """Verify UserCreate does NOT have disabled or force_password_change."""

    def test_user_create_has_no_disabled_field(self):
        """UserCreate should not expose a disabled field."""
        uc = UserCreate(username="test", password="pass123")
        assert not hasattr(uc, "disabled") or "disabled" not in uc.model_fields

    def test_user_create_has_no_force_password_change_field(self):
        """UserCreate should not expose a force_password_change field."""
        uc = UserCreate(username="test", password="pass123")
        assert (
            not hasattr(uc, "force_password_change")
            or "force_password_change" not in uc.model_fields
        )

    def test_user_response_model_has_disabled(self):
        """The User response model SHOULD have disabled (for API responses)."""
        from models.user import User

        u = User(username="test", role="VIEWER")
        assert hasattr(u, "disabled")
        assert u.disabled is False

    def test_user_response_model_has_force_password_change(self):
        """The User response model SHOULD have force_password_change."""
        from models.user import User

        u = User(username="test", role="VIEWER")
        assert hasattr(u, "force_password_change")
        assert u.force_password_change is False


class TestUserRepoCreateUser:
    """Test user_repo.create_user does NOT access non-existent fields."""

    def _make_mock_db(self):
        """Create a mock DB session that captures the User() constructor call."""
        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        return db

    def test_create_user_does_not_access_disabled(self):
        """create_user must NOT access user.disabled on UserCreate.

        If the bug exists, this raises AttributeError.
        """
        db = self._make_mock_db()
        user_in = UserCreate(
            username="newuser",
            password="SecureP@ss123",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_VIEW],
        )

        # This will raise AttributeError if create_user accesses user.disabled
        result = user_repo.create_user(db, user_in)

        # Verify the DB User was created with is_active=True (default)
        call_kwargs = db.add.call_args[0][0]
        assert call_kwargs.is_active is True

    def test_create_user_does_not_access_force_password_change(self):
        """create_user must NOT access user.force_password_change on UserCreate.

        If the bug exists, this raises AttributeError.
        """
        db = self._make_mock_db()
        user_in = UserCreate(
            username="newuser",
            password="SecureP@ss123",
            role="VIEWER",
        )

        # This will raise AttributeError if create_user accesses user.force_password_change
        result = user_repo.create_user(db, user_in)

        # Verify the DB User was created with force_password_change=False (default)
        call_kwargs = db.add.call_args[0][0]
        assert call_kwargs.force_password_change is False

    def test_create_user_sets_correct_defaults(self):
        """New users should be active and not forced to change password."""
        db = self._make_mock_db()
        user_in = UserCreate(
            username="newuser",
            password="SecureP@ss123",
            role="OPERATOR",
        )

        user_repo.create_user(db, user_in)

        db_user = db.add.call_args[0][0]
        assert db_user.username == "newuser"
        assert db_user.role == "OPERATOR"
        assert db_user.is_active is True
        assert db_user.force_password_change is False
        assert db_user.hashed_password is not None
        assert db_user.hashed_password != "SecureP@ss123"  # Should be hashed

    def test_create_user_preserves_all_user_create_fields(self):
        """All fields from UserCreate should be correctly mapped."""
        db = self._make_mock_db()
        user_in = UserCreate(
            username="fulluser",
            password="SecureP@ss123",
            role="ADMIN",
            permissions=[UserPermission.USER_MANAGE, UserPermission.CI_EDIT],
            allowed_locations=["NYC", "LDN"],
            allowed_ci_types=["router", "switch"],
            phone="+1234567890",
            email="user@example.com",
        )

        user_repo.create_user(db, user_in)

        db_user = db.add.call_args[0][0]
        assert db_user.username == "fulluser"
        assert db_user.role == "ADMIN"
        assert db_user.permissions == ["USER_MANAGE", "CI_EDIT"]
        assert db_user.allowed_locations == ["NYC", "LDN"]
        assert db_user.allowed_ci_types == ["router", "switch"]
        assert db_user.phone == "+1234567890"
        assert db_user.email == "user@example.com"

    def test_create_user_accepts_raw_string_permissions(self):
        """create_user should persist raw string permissions from API/UI payloads."""
        db = self._make_mock_db()
        user_in = UserCreate(
            username="stringperms",
            password="SecureP@ss123",
            role="OPERATOR",
            permissions=["EVENT_VIEW", "CI_EDIT"],
        )

        user_repo.create_user(db, user_in)

        db_user = db.add.call_args[0][0]
        assert db_user.permissions == ["EVENT_VIEW", "CI_EDIT"]

    def test_create_user_commits_and_refreshes(self):
        """create_user should commit and refresh the new user."""
        db = self._make_mock_db()
        user_in = UserCreate(username="test", password="pass123")

        user_repo.create_user(db, user_in)

        db.commit.assert_called_once()
        db.refresh.assert_called_once()

    def test_create_user_default_tier_is_T1(self):
        """New users created without explicit tier should default to 'T1'."""
        db = self._make_mock_db()
        user_in = UserCreate(username="tiertest", password="pass123")

        user_repo.create_user(db, user_in)

        db_user = db.add.call_args[0][0]
        assert db_user.tier == "T1"

    def test_create_user_explicit_tier_is_persisted(self):
        """New users with explicit tier should have it persisted to the DB model."""
        db = self._make_mock_db()
        user_in = UserCreate(username="adminuser", password="pass123", tier="T3")

        user_repo.create_user(db, user_in)

        db_user = db.add.call_args[0][0]
        assert db_user.tier == "T3"

    def test_create_user_accepts_enum_like_permissions(self):
        """create_user should remain compatible with enum-like permission values."""
        db = self._make_mock_db()
        permission = MagicMock(value="EVENT_VIEW")
        user_in = UserCreate.model_construct(
            username="enumlike",
            password="SecureP@ss123",
            role="OPERATOR",
            tier="T1",
            permissions=[permission],
            allowed_locations=[],
            allowed_ci_types=None,
            phone=None,
            email=None,
        )

        user_repo.create_user(db, user_in)

        db_user = db.add.call_args[0][0]
        assert db_user.permissions == ["EVENT_VIEW"]


class TestUserRepoUpdateUser:
    """Test user_repo.update_user permission normalization behavior."""

    def _make_mock_db_with_user(self, existing_permissions=None):
        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        db_user = MagicMock()
        db_user.permissions = list(existing_permissions or [])
        db.query.return_value.filter.return_value.first.return_value = db_user
        return db, db_user

    def test_update_user_accepts_raw_string_permissions(self):
        """update_user should persist raw string permissions from API/UI payloads."""
        db, db_user = self._make_mock_db_with_user(["USER_MANAGE"])
        update = UserUpdate(permissions=["EVENT_VIEW", "CI_EDIT"])

        result = user_repo.update_user(db, "stringperms", update)

        assert result is db_user
        assert db_user.permissions == ["EVENT_VIEW", "CI_EDIT"]
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(db_user)

    def test_update_user_accepts_enum_like_permissions(self):
        """update_user should remain compatible with enum-like permission values."""
        db, db_user = self._make_mock_db_with_user(["USER_MANAGE"])
        permission = MagicMock(value="EVENT_VIEW")
        update = UserUpdate.model_construct(
            password=None,
            role=None,
            tier=None,
            permissions=[permission],
            allowed_locations=None,
            allowed_ci_types=None,
        )

        user_repo.update_user(db, "enumlike", update)

        assert db_user.permissions == ["EVENT_VIEW"]

    def test_update_user_preserves_permissions_when_omitted(self):
        """permissions=None should leave existing permissions unchanged."""
        db, db_user = self._make_mock_db_with_user(["EVENT_VIEW", "CI_EDIT"])
        update = UserUpdate(permissions=None)

        user_repo.update_user(db, "noperms", update)

        assert db_user.permissions == ["EVENT_VIEW", "CI_EDIT"]

    def test_update_user_clears_permissions_with_empty_list(self):
        """permissions=[] should explicitly clear existing permissions."""
        db, db_user = self._make_mock_db_with_user(["EVENT_VIEW", "CI_EDIT"])
        update = UserUpdate(permissions=[])

        user_repo.update_user(db, "clearperms", update)

        assert db_user.permissions == []
