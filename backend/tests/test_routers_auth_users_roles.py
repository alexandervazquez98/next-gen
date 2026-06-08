"""Router-level tests for auth/users/roles endpoints — mocked dependencies.

Focus areas:
- POST /api/auth/token — login success, wrong password, inactive user, missing user
- GET /api/auth/users/me — authenticated user retrieval, unauthenticated access
- POST /api/auth/change-password — success, wrong old password
- GET /api/users/ — permission enforcement (USER_MANAGE)
- POST /api/users/ — creation with duplicate check
- PUT /api/users/{username} — update + permission check
- DELETE /api/users/{username} — delete + permission check
- POST /api/users/{username}/reset — admin password reset
- GET /api/roles/ — permission enforcement (USER_MANAGE or ROLE_MANAGE)
- POST /api/roles/ — creation + ROLE_MANAGE check
- PUT /api/roles/{name} — update + is_system protection
- DELETE /api/roles/{name} — delete + system role protection

Strategy:
- Use FastAPI TestClient
- Override DB dependency (get_pg_db) with a mock session
- Override get_current_active_user to inject fake Pydantic User objects
- Override Neo4j driver (database.get_db) for roles router
"""

import pytest
from datetime import datetime, timedelta
from fastapi import HTTPException
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Patch Neo4j driver BEFORE importing anything that touches database.py
# The driver is created at module import time and tries to connect immediately
_mock_neo4j_driver = MagicMock()
with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
    # Import the main app (which imports database.py)
    from main import app
    from database import get_db

from models.user import (
    User,
    UserInDB,
    CurrentUser,
    CurrentUserSessionPolicy,
    UserCreate,
    UserUpdate,
    UserPermission,
    PasswordChangeRequest,
    UserResetRequest,
    Role,
    RoleCreate,
)
from postgres_db import Base, get_pg_db
from services.auth_service import get_current_active_user
from repositories import user_repo
from middleware import rate_limit
from models.rate_limit_attempt import RateLimitAttempt
from routers.auth import (
    AUDIT_OUTCOME_DENIED,
    AUDIT_OUTCOME_FAILURE,
    AUDIT_OUTCOME_SUCCESS,
    AUTH_EVENT_LOGIN_FAILURE,
    AUTH_EVENT_LOGIN_SUCCESS,
    AUTH_EVENT_LOGOUT,
    AUTH_REASON_INCORRECT_CREDENTIALS,
    AUTH_REASON_INACTIVE_USER,
    AUTH_REASON_RATE_LIMITED,
    AUTH_REASON_LOGIN_SUCCESS,
    AUTH_REASON_LOGOUT_SUCCESS,
)

# ---------------------------------------------------------------------------
# TestClient
# ---------------------------------------------------------------------------
client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pydantic_user(
    username: str = "testuser",
    role: str = "OPERATOR",
    permissions: list[UserPermission] | None = None,
    disabled: bool = False,
    tier: str = "T1",
) -> User:
    """Create a Pydantic User for injection via dependency override."""
    return User(
        username=username,
        role=role,
        permissions=permissions or [],
        allowed_locations=[],
        disabled=disabled,
        tier=tier,
    )


def _make_pydantic_current_user(
    username: str = "testuser",
    role: str = "OPERATOR",
    permissions: list[UserPermission] | None = None,
    disabled: bool = False,
    tier: str = "T1",
    session_id: str = "sess-current-user",
    profile: str = "standard",
    idle_timeout_minutes: int | None = 15,
    persistent: bool = False,
) -> CurrentUser:
    """Create a current-user payload matching the users/me response contract."""
    return CurrentUser(
        username=username,
        role=role,
        permissions=permissions or [],
        allowed_locations=[],
        disabled=disabled,
        tier=tier,
        session_id=session_id,
        session_policy=CurrentUserSessionPolicy(
            profile=profile,
            idle_timeout_minutes=idle_timeout_minutes,
            persistent=persistent,
        ),
    )

def _make_pydantic_user_in_db(
    username: str = "testuser",
    role: str = "OPERATOR",
    permissions: list[UserPermission] | None = None,
    disabled: bool = False,
    hashed_password: str = "$pbkdf2-sha256$fakehash",
    tier: str = "T1",
) -> UserInDB:
    """Create a UserInDB for auth endpoint tests."""
    return UserInDB(
        username=username,
        role=role,
        permissions=permissions or [],
        allowed_locations=[],
        disabled=disabled,
        password=hashed_password,
        tier=tier,
    )


def _make_mock_pg_user(
    username: str = "testuser",
    role: str = "OPERATOR",
    permissions: list | None = None,
    is_active: bool = True,
    hashed_password: str = "$pbkdf2-sha256$fakehash",
    tier: str = "T1",
):
    """Create a mock SQLAlchemy User object (simulates DB row)."""
    mock = MagicMock()
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


def _assert_audit_request_context(kwargs: dict, user_agent: str | None = None, request_id: str | None = None) -> None:
    """Assert auth audit calls receive a Request with context needed for IP/UA enrichment."""
    request = kwargs["request"]
    if user_agent:
        assert request.headers["user-agent"] == user_agent
    if request_id:
        assert request.headers["x-request-id"] == request_id
    assert request.client is not None
    assert request.client.host


# ---------------------------------------------------------------------------
# Fixtures — mock DB session
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def rate_limit_db(monkeypatch):
    """Use an isolated DB for auth rate-limit helpers in router tests."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[RateLimitAttempt.__table__])
    monkeypatch.setattr(rate_limit, "SessionLocal", TestingSessionLocal)
    yield TestingSessionLocal
    Base.metadata.drop_all(bind=engine, tables=[RateLimitAttempt.__table__])


@pytest.fixture
def mock_db():
    """Provide a mock SQLAlchemy session."""
    db = MagicMock(spec=Session)
    return db


@pytest.fixture
def mock_neo4j_driver():
    """Provide a mock Neo4j driver."""
    driver = MagicMock()
    driver.execute_query.return_value = ([], None, None)
    return driver


# ---------------------------------------------------------------------------
# Tests: POST /api/auth/token
# ---------------------------------------------------------------------------


class TestAuthToken:
    """Tests for POST /api/auth/token endpoint."""

    def test_login_success(self, mock_db):
        """Valid credentials should return a token."""
        mock_user = _make_mock_pg_user(
            username="testuser",
            role="OPERATOR",
            is_active=True,
            hashed_password="$pbkdf2-sha256$29000$abc",
        )
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        # We need to patch verify_password to return True
        with patch("routers.auth.verify_password", return_value=True):
            response = client.post(
                "/api/auth/token",
                data={"username": "testuser", "password": "correct_password"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

        app.dependency_overrides.pop(get_pg_db, None)

    def test_login_wrong_password(self, mock_db):
        """Wrong password should return 401."""
        mock_user = _make_mock_pg_user(
            username="testuser",
            is_active=True,
            hashed_password="$pbkdf2-sha256$29000$abc",
        )
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.auth.verify_password", return_value=False):
            response = client.post(
                "/api/auth/token",
                data={"username": "testuser", "password": "wrong_password"},
            )

        assert response.status_code == 401

        app.dependency_overrides.pop(get_pg_db, None)

    def test_login_user_not_found(self, mock_db):
        """Non-existent user should return 401."""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        response = client.post(
            "/api/auth/token",
            data={"username": "nobody", "password": "any"},
        )

        assert response.status_code == 401

        app.dependency_overrides.pop(get_pg_db, None)

    def test_login_rate_limits_on_threshold_crossing_failure(self, mock_db):
        """Fourth failed login attempt should lock immediately with HTTP 429."""
        mock_user = _make_mock_pg_user(
            username="testuser",
            is_active=True,
            hashed_password="$pbkdf2-sha256$29000$abc",
        )
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.auth.verify_password", return_value=False) as mock_verify:
            responses = [
                client.post(
                    "/api/auth/token",
                    data={"username": "testuser", "password": "wrong_password"},
                )
                for _ in range(4)
            ]

        assert [response.status_code for response in responses[:3]] == [401, 401, 401]
        assert responses[3].status_code == 429
        assert "Retry-After" in responses[3].headers
        assert mock_verify.call_count == 4

        app.dependency_overrides.pop(get_pg_db, None)

    def test_login_inactive_user(self, mock_db):
        """Inactive (disabled) user should return 400."""
        mock_user = _make_mock_pg_user(
            username="testuser",
            is_active=False,
            hashed_password="$pbkdf2-sha256$29000$abc",
        )
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.auth.verify_password", return_value=True):
            response = client.post(
                "/api/auth/token",
                data={"username": "testuser", "password": "correct_password"},
            )

        assert response.status_code == 400

        app.dependency_overrides.pop(get_pg_db, None)

    def test_login_wrong_credentials_records_audit_failure(self, mock_db):
        # Failed login should emit a LOGIN_FAILURE audit event with safe context.
        mock_user = _make_mock_pg_user(
            username="testuser",
            is_active=True,
            hashed_password="$pbkdf2-sha256$29000$abc",
        )
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with (
            patch("routers.auth.verify_password", return_value=False),
            patch("routers.auth.audit_service.record_auth_event") as mock_record,
        ):
            response = client.post(
                "/api/auth/token",
                data={"username": "testuser", "password": "wrong_password"},
                headers={"User-Agent": "pytest-agent", "X-Request-ID": "req-auth-1"},
            )

        assert response.status_code == 401
        mock_record.assert_called_once()
        kwargs = mock_record.call_args.kwargs
        assert kwargs["event_type"] == AUTH_EVENT_LOGIN_FAILURE
        assert kwargs["outcome"] == AUDIT_OUTCOME_FAILURE
        assert kwargs["actor_username"] == "testuser"
        assert kwargs["reason"] == AUTH_REASON_INCORRECT_CREDENTIALS
        _assert_audit_request_context(kwargs, user_agent="pytest-agent", request_id="req-auth-1")
        context = kwargs.get("context") or {}
        assert "password" not in context
        assert "token" not in context
        assert "raw_body" not in context

        app.dependency_overrides.pop(get_pg_db, None)

    def test_login_precheck_rate_limit_records_audit_denied(self, mock_db):
        # Already locked identities should emit audit before the pre-check 429 response.
        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with (
            patch(
                "routers.auth.check_rate_limit",
                side_effect=HTTPException(status_code=429, detail="Too many failed login attempts."),
            ),
            patch("routers.auth.audit_service.record_auth_event") as mock_record,
        ):
            response = client.post(
                "/api/auth/token",
                data={"username": "testuser", "password": "wrong_password"},
                headers={"User-Agent": "pytest-agent", "X-Request-ID": "req-auth-precheck"},
            )

        assert response.status_code == 429
        mock_record.assert_called_once()
        kwargs = mock_record.call_args.kwargs
        assert kwargs["event_type"] == AUTH_EVENT_LOGIN_FAILURE
        assert kwargs["outcome"] == AUDIT_OUTCOME_DENIED
        assert kwargs["actor_username"] == "testuser"
        assert kwargs["reason"] == AUTH_REASON_RATE_LIMITED
        _assert_audit_request_context(kwargs, user_agent="pytest-agent", request_id="req-auth-precheck")

        app.dependency_overrides.pop(get_pg_db, None)

    def test_login_rate_limit_locked_records_audit_denied(self, mock_db):
        # Rate-limited login should emit a denied audit event before 429.
        mock_user = _make_mock_pg_user(
            username="testuser",
            is_active=True,
            hashed_password="$pbkdf2-sha256$29000$abc",
        )
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        lock_time = datetime.utcnow() + timedelta(minutes=15)
        attempt_info = type("AttemptInfo", (), {"locked_until": lock_time, "count": 4})

        with (
            patch("routers.auth.verify_password", return_value=False),
            patch("routers.auth.increment_attempts", return_value=attempt_info),
            patch("routers.auth.audit_service.record_auth_event") as mock_record,
            patch(
                "routers.auth.raise_rate_limit_locked",
                side_effect=HTTPException(status_code=429, detail="Too many failed login attempts. Account temporarily locked.", headers={"Retry-After": "900"}),
            ),
        ):
            response = client.post(
                "/api/auth/token",
                data={"username": "testuser", "password": "wrong_password"},
            )

        assert response.status_code == 429
        assert mock_record.call_count == 1
        kwargs = mock_record.call_args.kwargs
        assert kwargs["event_type"] == AUTH_EVENT_LOGIN_FAILURE
        assert kwargs["outcome"] == AUDIT_OUTCOME_DENIED
        assert kwargs["actor_username"] == "testuser"
        assert kwargs["reason"] == AUTH_REASON_RATE_LIMITED

        app.dependency_overrides.pop(get_pg_db, None)

    def test_login_inactive_user_records_audit_denied(self, mock_db):
        # Inactive users should emit denied login audits before 400 response.
        mock_user = _make_mock_pg_user(
            username="testuser",
            is_active=False,
            hashed_password="$pbkdf2-sha256$29000$abc",
        )
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with (
            patch("routers.auth.verify_password", return_value=True),
            patch("routers.auth.audit_service.record_auth_event") as mock_record,
        ):
            response = client.post(
                "/api/auth/token",
                data={"username": "testuser", "password": "correct_password"},
            )

        assert response.status_code == 400
        assert mock_record.call_count == 1
        kwargs = mock_record.call_args.kwargs
        assert kwargs["event_type"] == AUTH_EVENT_LOGIN_FAILURE
        assert kwargs["outcome"] == AUDIT_OUTCOME_DENIED
        assert kwargs["actor_username"] == "testuser"
        assert kwargs["reason"] == AUTH_REASON_INACTIVE_USER

        app.dependency_overrides.pop(get_pg_db, None)

    def test_login_success_records_audit_success(self, mock_db):
        # Successful login should emit LOGIN_SUCCESS audit event.
        mock_user = _make_mock_pg_user(
            username="testuser",
            role="OPERATOR",
            is_active=True,
            hashed_password="$pbkdf2-sha256$29000$abc",
        )
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with (
            patch("routers.auth.verify_password", return_value=True),
            patch("routers.auth.audit_service.record_auth_event") as mock_record,
        ):
            response = client.post(
                "/api/auth/token",
                data={"username": "testuser", "password": "correct_password"},
                headers={"User-Agent": "pytest-agent", "X-Request-ID": "req-auth-2"},
            )

        assert response.status_code == 200
        assert mock_record.call_count == 1
        kwargs = mock_record.call_args.kwargs
        assert kwargs["event_type"] == AUTH_EVENT_LOGIN_SUCCESS
        assert kwargs["outcome"] == AUDIT_OUTCOME_SUCCESS
        assert kwargs["actor_username"] == "testuser"
        assert kwargs["reason"] == AUTH_REASON_LOGIN_SUCCESS

        app.dependency_overrides.pop(get_pg_db, None)

    def test_login_mixed_outcome_sequence_records_distinct_audit_events(self, mock_db):
        # Mixed failure/success login attempts should capture both outcomes.
        mock_user = _make_mock_pg_user(
            username="testuser",
            role="OPERATOR",
            is_active=True,
            hashed_password="$pbkdf2-sha256$29000$abc",
        )
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with (
            patch(
                "routers.auth.verify_password",
                side_effect=[False, True],
            ),
            patch("routers.auth.audit_service.record_auth_event") as mock_record,
        ):
            failure = client.post(
                "/api/auth/token",
                data={"username": "testuser", "password": "wrong"},
            )
            success = client.post(
                "/api/auth/token",
                data={"username": "testuser", "password": "right"},
            )

        assert failure.status_code == 401
        assert success.status_code == 200
        assert len(mock_record.call_args_list) >= 2
        calls = mock_record.call_args_list
        assert calls[0].kwargs["event_type"] == AUTH_EVENT_LOGIN_FAILURE
        assert calls[0].kwargs["outcome"] == AUDIT_OUTCOME_FAILURE
        assert calls[1].kwargs["event_type"] == AUTH_EVENT_LOGIN_SUCCESS
        assert calls[1].kwargs["outcome"] == AUDIT_OUTCOME_SUCCESS

        app.dependency_overrides.pop(get_pg_db, None)

    def test_logout_records_audit_event(self, mock_db):
        # Successful logout should emit LOGOUT audit event.
        fake_user = _make_pydantic_user(username="testuser", role="OPERATOR")

        def override_get_db():
            yield mock_db

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_pg_db] = override_get_db
        app.dependency_overrides[get_current_active_user] = override_get_current_active_user

        with patch("routers.auth.audit_service.record_auth_event") as mock_record:
            response = client.post(
                "/api/auth/logout",
                headers={"User-Agent": "pytest-agent", "X-Request-ID": "req-auth-3"},
            )

        assert response.status_code == 200
        assert mock_record.call_count == 1
        kwargs = mock_record.call_args.kwargs
        assert kwargs["event_type"] == AUTH_EVENT_LOGOUT
        assert kwargs["outcome"] == AUDIT_OUTCOME_SUCCESS
        assert kwargs["actor_username"] == "testuser"
        assert kwargs["reason"] == AUTH_REASON_LOGOUT_SUCCESS

        app.dependency_overrides.pop(get_pg_db, None)
        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: GET /api/auth/users/me
# ---------------------------------------------------------------------------


class TestAuthUsersMe:
    """Tests for GET /api/auth/users/me endpoint."""

    def test_get_current_user_success(self):
        """Authenticated user should receive their own profile."""
        fake_user = _make_pydantic_user(
            username="testuser",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_VIEW],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.get("/api/auth/users/me")

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert data["role"] == "OPERATOR"

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_get_current_user_includes_session_policy(self):
        """Session policy metadata must be returned for frontend inactivity decisions."""
        fake_user = _make_pydantic_current_user(
            username="testuser",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_VIEW],
            profile="standard",
            idle_timeout_minutes=15,
            persistent=False,
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.get("/api/auth/users/me")

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        policy = data["session_policy"]
        assert policy["profile"] == "standard"
        assert policy["idle_timeout_minutes"] == 15
        assert policy["persistent"] is False

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_get_current_user_includes_operational_session_policy(self):
        """Operational policy metadata should be stable for frontend timeout decisions."""
        fake_user = _make_pydantic_current_user(
            username="nocuser",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_VIEW],
            session_id="sess-operational",
            profile="operational",
            idle_timeout_minutes=None,
            persistent=True,
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.get("/api/auth/users/me")

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "sess-operational"
        policy = data["session_policy"]
        assert policy["profile"] == "operational"
        assert policy["idle_timeout_minutes"] is None
        assert policy["persistent"] is True

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_get_current_user_allows_missing_session_id(self):
        """Legacy tokens without sid should produce explicit null session_id."""
        fake_user = _make_pydantic_current_user(
            username="legacyuser",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_VIEW],
            session_id=None,
            profile="standard",
            idle_timeout_minutes=15,
            persistent=False,
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.get("/api/auth/users/me")

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] is None
        assert data["session_policy"]["profile"] == "standard"

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_get_current_user_disabled(self):
        """Disabled user should get 400 from get_current_active_user."""
        disabled_user = _make_pydantic_user(
            username="disabled_user",
            role="VIEWER",
            disabled=True,
        )

        async def override_get_current_active_user():
            from fastapi import HTTPException

            if disabled_user.disabled:
                raise HTTPException(status_code=400, detail="Inactive user")
            return disabled_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.get("/api/auth/users/me")

        assert response.status_code == 400

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_get_current_user_unauthenticated(self):
        """No token should result in 401 from OAuth2PasswordBearer."""
        # Don't override get_current_active_user — let the real OAuth2 scheme reject
        response = client.get("/api/auth/users/me")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Tests: POST /api/auth/change-password
# ---------------------------------------------------------------------------


class TestAuthChangePassword:
    """Tests for POST /api/auth/change-password endpoint."""

    def test_change_password_success(self, mock_db):
        """Valid old password should allow change."""
        fake_user = _make_pydantic_user(username="testuser", role="OPERATOR")
        mock_pg_user = _make_mock_pg_user(
            username="testuser",
            hashed_password="$pbkdf2-sha256$29000$oldhash",
        )
        mock_db.query.return_value.filter.return_value.first.return_value = mock_pg_user

        async def override_get_current_active_user():
            return fake_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )
        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.auth.verify_password", return_value=True):
            response = client.post(
                "/api/auth/change-password",
                json={"old_password": "OldPass123", "new_password": "NewPass456"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_pg_db, None)

    def test_change_password_wrong_old(self, mock_db):
        """Wrong old password should return 400."""
        fake_user = _make_pydantic_user(username="testuser", role="OPERATOR")
        mock_pg_user = _make_mock_pg_user(
            username="testuser",
            hashed_password="$pbkdf2-sha256$29000$oldhash",
        )
        mock_db.query.return_value.filter.return_value.first.return_value = mock_pg_user

        async def override_get_current_active_user():
            return fake_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )
        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.auth.verify_password", return_value=False):
            response = client.post(
                "/api/auth/change-password",
                json={"old_password": "WrongOld", "new_password": "NewPass456"},
            )

        assert response.status_code == 400

        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_pg_db, None)

    def test_change_password_user_not_found(self, mock_db):
        """If DB user doesn't exist, return 404."""
        fake_user = _make_pydantic_user(username="ghost_user", role="OPERATOR")
        mock_db.query.return_value.filter.return_value.first.return_value = None

        async def override_get_current_active_user():
            return fake_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )
        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.auth.verify_password", return_value=True):
            response = client.post(
                "/api/auth/change-password",
                json={"old_password": "OldPass123", "new_password": "NewPass456"},
            )

        assert response.status_code == 404

        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_pg_db, None)


# ---------------------------------------------------------------------------
# Tests: Users CRUD — /api/users/
# ---------------------------------------------------------------------------


class TestUsersList:
    """Tests for GET /api/users/ — list users."""

    def test_list_users_admin_success(self, mock_db):
        """Admin should be able to list users."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")
        mock_pg_user = _make_mock_pg_user(
            username="testuser",
            role="OPERATOR",
            is_active=True,
        )
        mock_db.query.return_value.offset.return_value.limit.return_value.all.return_value = [
            mock_pg_user
        ]

        async def override_get_current_active_user():
            return fake_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )
        app.dependency_overrides[get_pg_db] = override_get_db

        response = client.get("/api/users/")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["username"] == "testuser"

        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_pg_db, None)

    def test_list_users_viewer_forbidden(self):
        """Viewer without USER_MANAGE should get 403."""
        fake_user = _make_pydantic_user(
            username="viewer",
            role="VIEWER",
            permissions=[],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.get("/api/users/")

        assert response.status_code == 403

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_list_users_unauthenticated(self):
        """No auth should return 401."""
        response = client.get("/api/users/")
        assert response.status_code == 401


class TestUsersCreate:
    """Tests for POST /api/users/ — create user."""

    def test_create_user_admin_success(self, mock_db):
        """Admin should be able to create a user."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")
        new_pg_user = _make_mock_pg_user(
            username="newuser",
            role="OPERATOR",
            is_active=True,
            permissions=["EVENT_VIEW"],
        )

        def override_get_db():
            yield mock_db

        async def override_get_current_active_user():
            return fake_user

        # user_repo.create_user has a pre-existing bug: it accesses
        # user.disabled and user.force_password_change which don't exist
        # on UserCreate. We must mock the repo call entirely.
        with patch.object(user_repo, "get_user_by_username", return_value=None):
            with (
                patch.object(user_repo, "create_user", return_value=new_pg_user),
                patch("routers.users.audit_service.record_critical_change") as mock_record,
            ):
                app.dependency_overrides[get_current_active_user] = (
                    override_get_current_active_user
                )
                app.dependency_overrides[get_pg_db] = override_get_db

                response = client.post(
                    "/api/users/",
                    json={
                        "username": "newuser",
                        "password": "SecureP@ss123",
                        "role": "OPERATOR",
                        "permissions": ["EVENT_VIEW"],
                    },
                )

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "newuser"
        mock_record.assert_called_once()
        kwargs = mock_record.call_args.kwargs
        assert kwargs["event_type"] == "USER_CREATE"
        assert kwargs["outcome"] == "SUCCESS"
        assert kwargs["target_type"] == "user"
        assert kwargs["target_id"] == "newuser"

        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_pg_db, None)
    def test_create_user_duplicate_username(self, mock_db):
        """Creating a user with existing username should return 400."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")
        existing_pg_user = _make_mock_pg_user(username="existing_user")

        def override_get_db():
            yield mock_db

        async def override_get_current_active_user():
            return fake_user

        mock_db.query.return_value.filter.return_value.first.return_value = (
            existing_pg_user
        )

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )
        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.users.audit_service.record_critical_change") as mock_record:
            response = client.post(
                "/api/users/",
                json={
                    "username": "existing_user",
                    "password": "SecureP@ss123",
                },
            )

        assert response.status_code == 400
        mock_record.assert_called_once()
        kwargs = mock_record.call_args.kwargs
        assert kwargs["event_type"] == "USER_CREATE"
        assert kwargs["outcome"] == "VALIDATION_FAILURE"

        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_pg_db, None)

    def test_create_user_viewer_forbidden(self):
        """Viewer without USER_MANAGE should get 403."""
        fake_user = _make_pydantic_user(
            username="viewer",
            role="VIEWER",
            permissions=[],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        with patch("routers.users.audit_service.record_denied") as mock_record:
            response = client.post(
                "/api/users/",
                json={
                    "username": "newuser",
                    "password": "SecureP@ss123",
                },
            )

        assert response.status_code == 403
        mock_record.assert_called_once()

        app.dependency_overrides.pop(get_current_active_user, None)


class TestUsersUpdate:
    """Tests for PUT /api/users/{username} — update user."""

    def test_update_user_admin_success(self, mock_db):
        """Admin should be able to update a user."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")
        updated_pg_user = _make_mock_pg_user(
            username="testuser",
            role="ADMIN",
            is_active=True,
        )

        def override_get_db():
            yield mock_db

        async def override_get_current_active_user():
            return fake_user

        # update_user calls get_user_by_username internally
        mock_db.query.return_value.filter.return_value.first.return_value = (
            updated_pg_user
        )

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )
        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.users.audit_service.record_critical_change") as mock_record:
            response = client.put(
                "/api/users/testuser",
                json={"role": "ADMIN"},
            )

        assert response.status_code == 200
        mock_record.assert_called_once()
        kwargs = mock_record.call_args.kwargs
        assert kwargs["event_type"] == "USER_UPDATE"
        assert kwargs["outcome"] == "SUCCESS"

        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_pg_db, None)

    def test_update_user_not_found(self, mock_db):
        """Updating non-existent user should return 404."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        def override_get_db():
            yield mock_db

        async def override_get_current_active_user():
            return fake_user

        mock_db.query.return_value.filter.return_value.first.return_value = None

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )
        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.users.audit_service.record_critical_change") as mock_record:
            response = client.put(
                "/api/users/nonexistent",
                json={"role": "ADMIN"},
            )

        assert response.status_code == 404
        mock_record.assert_called_once()
        kwargs = mock_record.call_args.kwargs
        assert kwargs["event_type"] == "USER_UPDATE"
        assert kwargs["outcome"] == "VALIDATION_FAILURE"

        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_pg_db, None)

    def test_update_user_viewer_forbidden(self):
        """Viewer should get 403."""
        fake_user = _make_pydantic_user(
            username="viewer",
            role="VIEWER",
            permissions=[],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        with patch("routers.users.audit_service.record_denied") as mock_record:
            response = client.put(
                "/api/users/testuser",
                json={"role": "ADMIN"},
            )

        assert response.status_code == 403
        mock_record.assert_called_once()

        app.dependency_overrides.pop(get_current_active_user, None)


class TestUsersDelete:
    """Tests for DELETE /api/users/{username} — delete user."""

    def test_delete_user_admin_success(self, mock_db):
        """Admin should be able to delete a user."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        def override_get_db():
            yield mock_db

        async def override_get_current_active_user():
            return fake_user

        # delete_user calls get_user_by_username
        mock_db.query.return_value.filter.return_value.first.return_value = (
            _make_mock_pg_user(username="testuser")
        )

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )
        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.users.audit_service.record_critical_change") as mock_record:
            response = client.delete("/api/users/testuser")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        mock_record.assert_called_once()
        kwargs = mock_record.call_args.kwargs
        assert kwargs["event_type"] == "USER_DELETE"
        assert kwargs["outcome"] == "SUCCESS"

        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_pg_db, None)

    def test_delete_user_not_found(self, mock_db):
        """Deleting non-existent user should return 404."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        def override_get_db():
            yield mock_db

        async def override_get_current_active_user():
            return fake_user

        mock_db.query.return_value.filter.return_value.first.return_value = None

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )
        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.users.audit_service.record_critical_change") as mock_record:
            response = client.delete("/api/users/nonexistent")

        assert response.status_code == 404
        mock_record.assert_called_once()
        kwargs = mock_record.call_args.kwargs
        assert kwargs["event_type"] == "USER_DELETE"
        assert kwargs["outcome"] == "VALIDATION_FAILURE"

        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_pg_db, None)

    def test_delete_user_viewer_forbidden(self):
        """Viewer should get 403."""
        fake_user = _make_pydantic_user(
            username="viewer",
            role="VIEWER",
            permissions=[],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        with patch("routers.users.audit_service.record_denied") as mock_record:
            response = client.delete("/api/users/testuser")

        assert response.status_code == 403
        mock_record.assert_called_once()

        app.dependency_overrides.pop(get_current_active_user, None)


class TestUsersResetPassword:
    """Tests for POST /api/users/{username}/reset — admin password reset."""

    def test_reset_password_admin_success(self, mock_db):
        """Admin should be able to reset a user's password."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")
        target_pg_user = _make_mock_pg_user(
            username="target_user",
            is_active=True,
        )

        def override_get_db():
            yield mock_db

        async def override_get_current_active_user():
            return fake_user

        mock_db.query.return_value.filter.return_value.first.return_value = (
            target_pg_user
        )

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )
        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.users.audit_service.record_critical_change") as mock_record:
            response = client.post(
                "/api/users/target_user/reset",
                json={"new_password": "ResetP@ss123"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "Password reset" in data["message"]
        mock_record.assert_called_once()
        kwargs = mock_record.call_args.kwargs
        assert kwargs["event_type"] == "USER_PASSWORD_RESET"
        assert kwargs["outcome"] == "SUCCESS"

        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_pg_db, None)

    def test_reset_password_no_password(self, mock_db):
        """Reset without new_password should return 422 (Pydantic validation)."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        def override_get_db():
            yield mock_db

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )
        app.dependency_overrides[get_pg_db] = override_get_db

        # Sending empty JSON body triggers Pydantic validation error (422)
        # because UserResetRequest requires new_password.
        response = client.post(
            "/api/users/target_user/reset",
            json={},
        )

        assert response.status_code == 422

        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_pg_db, None)

    def test_reset_password_missing_body_records_validation_audit(self, mock_db):
        """Reset without a body should exercise the handler validation audit branch."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        def override_get_db():
            yield mock_db

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )
        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.users.audit_service.record_critical_change") as mock_record:
            response = client.post("/api/users/target_user/reset")

        assert response.status_code == 400
        mock_record.assert_called_once()
        kwargs = mock_record.call_args.kwargs
        assert kwargs["event_type"] == "USER_PASSWORD_RESET"
        assert kwargs["outcome"] == "VALIDATION_FAILURE"
        assert kwargs["reason"] == "password_required"
        assert kwargs["target_id"] == "target_user"

        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_pg_db, None)

    def test_reset_password_viewer_forbidden(self):
        """Viewer should get 403."""
        fake_user = _make_pydantic_user(
            username="viewer",
            role="VIEWER",
            permissions=[],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        with patch("routers.users.audit_service.record_denied") as mock_record:
            response = client.post(
                "/api/users/target_user/reset",
                json={"new_password": "ResetP@ss123"},
            )

        assert response.status_code == 403
        mock_record.assert_called_once()

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: Roles CRUD — /api/roles/
# ---------------------------------------------------------------------------


class _FakeNeo4jNode:
    """Mimics a Neo4j node so that dict(node) and node.get() work correctly."""

    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()

    def __iter__(self):
        return iter(self._data)

    def items(self):
        return self._data.items()


class TestRolesList:
    """Tests for GET /api/roles/ — list roles."""

    def test_list_roles_admin_success(self, mock_neo4j_driver):
        """Admin should be able to list roles."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        # roles.py calls get_db_driver() directly, not via Depends()
        # so we must patch the function at the router module level
        with patch("routers.roles.get_db_driver", return_value=mock_neo4j_driver):
            # Mock Neo4j results — use FakeNeo4jNode so dict(node) works
            mock_node = _FakeNeo4jNode(
                {
                    "name": "ADMIN",
                    "description": "System admin",
                    "permissions": ["EVENT_VIEW", "CI_EDIT"],
                    "is_system": True,
                }
            )
            mock_record = {"r": mock_node}
            mock_neo4j_driver.execute_query.return_value = (
                [mock_record],
                None,
                None,
            )

            response = client.get("/api/roles/")

            assert response.status_code == 200

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_list_roles_viewer_forbidden(self):
        """Viewer without USER_MANAGE or ROLE_MANAGE should get 403."""
        fake_user = _make_pydantic_user(
            username="viewer",
            role="VIEWER",
            permissions=[],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.get("/api/roles/")

        assert response.status_code == 403

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_list_roles_operator_with_user_manage(self, mock_neo4j_driver):
        """Operator with USER_MANAGE should be able to list roles."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.USER_MANAGE],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        with patch("routers.roles.get_db_driver", return_value=mock_neo4j_driver):
            mock_neo4j_driver.execute_query.return_value = ([], None, None)
            response = client.get("/api/roles/")

        # The key assertion: it should NOT be 403
        assert response.status_code != 403

        app.dependency_overrides.pop(get_current_active_user, None)


class TestRolesCreate:
    """Tests for POST /api/roles/ — create role."""

    def test_create_role_admin_success(self, mock_neo4j_driver):
        """Admin with ROLE_MANAGE should create a role."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        # First execute_query: check exists (empty results)
        # Second execute_query: create (with result)
        mock_create_node = _FakeNeo4jNode(
            {
                "name": "CustomRole",
                "description": "A custom role",
                "permissions": ["EVENT_VIEW"],
                "is_system": False,
            }
        )
        mock_create_record = {"r": mock_create_node}

        call_count = [0]

        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return ([], None, None)
            return ([mock_create_record], None, None)

        mock_neo4j_driver.execute_query.side_effect = mock_execute

        with patch("routers.roles.get_db_driver", return_value=mock_neo4j_driver):
            response = client.post(
                "/api/roles/",
                json={
                    "name": "CustomRole",
                    "description": "A custom role",
                    "permissions": ["EVENT_VIEW", "EVENT_VIEW", " EVENT_VIEW ", "METRICS_VIEW"],
                },
            )

            assert response.status_code == 200
            assert response.json()["name"] == "CustomRole"

            # Create query should receive normalized, deduped, trimmed permissions
            create_query_params = mock_neo4j_driver.execute_query.call_args_list[1].kwargs
            assert create_query_params["permissions"] == ["EVENT_VIEW", "METRICS_VIEW"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_create_role_invalid_permission_is_rejected(self, mock_neo4j_driver):
        """Create should reject unknown permissions and avoid persistence."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        mock_neo4j_driver.execute_query.return_value = ([], None, None)

        with patch("routers.roles.get_db_driver", return_value=mock_neo4j_driver):
            response = client.post(
                "/api/roles/",
                json={
                    "name": "CustomRole",
                    "description": "A bad role",
                    "permissions": ["EVENT_VIEW", "BOGUS_PERMISSION"],
                },
            )

            assert response.status_code == 400
            error = response.json()
            assert "invalid_permissions" in error["detail"]

        # only existence check should run; create query must not run
        assert mock_neo4j_driver.execute_query.call_count == 1

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_create_role_rejects_empty_permission(self, mock_neo4j_driver):
        """Create should reject blank permission strings."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        mock_neo4j_driver.execute_query.return_value = ([], None, None)

        with patch("routers.roles.get_db_driver", return_value=mock_neo4j_driver):
            response = client.post(
                "/api/roles/",
                json={
                    "name": "CustomRole",
                    "description": "A bad role",
                    "permissions": [""],
                },
            )

            assert response.status_code == 400
            assert "invalid_permissions" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_create_role_duplicate(self, mock_neo4j_driver):
        """Creating a role that already exists should return 400."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        mock_existing_node = _FakeNeo4jNode({"name": "ExistingRole"})
        mock_record = {"r": mock_existing_node}
        mock_neo4j_driver.execute_query.return_value = ([mock_record], None, None)

        with patch("routers.roles.get_db_driver", return_value=mock_neo4j_driver):
            response = client.post(
                "/api/roles/",
                json={
                    "name": "ExistingRole",
                    "permissions": ["EVENT_VIEW"],
                },
            )

            assert response.status_code == 400

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_create_role_viewer_forbidden(self):
        """Viewer should get 403 on role creation."""
        fake_user = _make_pydantic_user(
            username="viewer",
            role="VIEWER",
            permissions=[],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.post(
            "/api/roles/",
            json={"name": "NewRole", "permissions": ["EVENT_VIEW"]},
        )

        assert response.status_code == 403

        app.dependency_overrides.pop(get_current_active_user, None)


class TestRolesUpdate:
    """Tests for PUT /api/roles/{name} — update role."""

    def test_update_role_admin_success(self, mock_neo4j_driver):
        """Admin should be able to update a non-system role."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        mock_record = {"r": _FakeNeo4jNode(
            {
                "name": "CustomRole",
                "description": "Updated description",
                "permissions": ["EVENT_ACK", "METRICS_VIEW"],
                "is_system": False,
            }
        )}

        def mock_execute(*args, **kwargs):
            # First call: lookup by name; second call: update
            if mock_execute.call_count == 0:
                mock_execute.call_count += 1
                return ([{"r": _FakeNeo4jNode({"name": "CustomRole", "is_system": False})}], None, None)
            mock_execute.call_count += 1
            return ([mock_record], None, None)

        mock_execute.call_count = 0
        mock_neo4j_driver.execute_query.side_effect = mock_execute

        with patch("routers.roles.get_db_driver", return_value=mock_neo4j_driver):
            response = client.put(
                "/api/roles/CustomRole",
                json={
                    "description": "Updated description",
                    "permissions": ["EVENT_ACK", " EVENT_ACK ", "METRICS_VIEW"],
                },
            )

            assert response.status_code == 200

            # Update payload should be normalized and deduped
            update_params = mock_neo4j_driver.execute_query.call_args_list[1].kwargs
            assert update_params["permissions"] == ["EVENT_ACK", "METRICS_VIEW"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_update_role_with_invalid_permission_rejected(self, mock_neo4j_driver):
        """Update should reject non-string permissions and avoid write query."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        mock_node = _FakeNeo4jNode(
            {"name": "CustomRole", "description": "Existing", "is_system": False}
        )
        mock_record = {"r": mock_node}
        mock_neo4j_driver.execute_query.return_value = ([mock_record], None, None)

        with patch("routers.roles.get_db_driver", return_value=mock_neo4j_driver):
            response = client.put(
                "/api/roles/CustomRole",
                json={"permissions": ["EVENT_VIEW", 123]},
            )

            assert response.status_code in (400, 422)
            if response.status_code == 400:
                assert "invalid_permissions" in response.json()["detail"]

        # either route rejected by service validation (400) or schema validation (422);
        # in neither case should an update write query run
        assert mock_neo4j_driver.execute_query.call_count <= 1

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_update_system_role_forbidden_no_update_query(self, mock_neo4j_driver):
        """System roles cannot be updated and should skip update write query."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        mock_node = _FakeNeo4jNode(
            {
                "name": "ADMIN",
                "is_system": True,
            }
        )
        mock_record = {"r": mock_node}

        mock_neo4j_driver.execute_query.return_value = ([mock_record], None, None)

        with patch("routers.roles.get_db_driver", return_value=mock_neo4j_driver):
            response = client.put(
                "/api/roles/ADMIN",
                json={"description": "Should not work"},
            )

            assert response.status_code == 400

        # Only initial lookup query should execute
        assert mock_neo4j_driver.execute_query.call_count == 1

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_update_system_role_forbidden(self, mock_neo4j_driver):
        """Updating a system role should return 400."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        mock_node = _FakeNeo4jNode(
            {
                "name": "ADMIN",
                "is_system": True,
            }
        )
        mock_record = {"r": mock_node}
        mock_neo4j_driver.execute_query.return_value = ([mock_record], None, None)

        with patch("routers.roles.get_db_driver", return_value=mock_neo4j_driver):
            response = client.put(
                "/api/roles/ADMIN",
                json={"description": "Should not work"},
            )

            assert response.status_code == 400

        # only lookup should have run
        assert mock_neo4j_driver.execute_query.call_count == 1

        app.dependency_overrides.pop(get_current_active_user, None)
    def test_update_role_not_found(self, mock_neo4j_driver):
        """Updating non-existent role should return 404."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        mock_neo4j_driver.execute_query.return_value = ([], None, None)

        with patch("routers.roles.get_db_driver", return_value=mock_neo4j_driver):
            response = client.put(
                "/api/roles/NonExistent",
                json={"description": "Should fail"},
            )

            assert response.status_code == 404

        app.dependency_overrides.pop(get_current_active_user, None)


class TestRolesDelete:
    """Tests for DELETE /api/roles/{name} — delete role."""

    def test_delete_role_admin_success(self, mock_neo4j_driver):
        """Admin should be able to delete a non-system, unassigned role."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        call_count = [0]

        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # Check existence
                mock_node = _FakeNeo4jNode(
                    {
                        "name": "CustomRole",
                        "is_system": False,
                    }
                )
                return ([{"r": mock_node}], None, None)
            elif call_count[0] == 2:
                # Usage check — no users
                return ([{"count": 0}], None, None)
            return ([], None, None)

        mock_neo4j_driver.execute_query.side_effect = mock_execute

        with patch("routers.roles.get_db_driver", return_value=mock_neo4j_driver):
            response = client.delete("/api/roles/CustomRole")

            assert response.status_code == 200

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_delete_system_role_forbidden(self, mock_neo4j_driver):
        """Deleting a system role should return 400."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        mock_node = _FakeNeo4jNode({"name": "ADMIN", "is_system": True})
        mock_record = {"r": mock_node}
        mock_neo4j_driver.execute_query.return_value = ([mock_record], None, None)

        with patch("routers.roles.get_db_driver", return_value=mock_neo4j_driver):
            response = client.delete("/api/roles/ADMIN")

            assert response.status_code == 400

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_delete_role_with_assigned_users(self, mock_neo4j_driver):
        """Deleting a role assigned to users should return 400."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        call_count = [0]

        def mock_execute(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                mock_node = _FakeNeo4jNode(
                    {
                        "name": "CustomRole",
                        "is_system": False,
                    }
                )
                return ([{"r": mock_node}], None, None)
            elif call_count[0] == 2:
                return ([{"count": 3}], None, None)
            return ([], None, None)

        mock_neo4j_driver.execute_query.side_effect = mock_execute

        with patch("routers.roles.get_db_driver", return_value=mock_neo4j_driver):
            response = client.delete("/api/roles/CustomRole")

            assert response.status_code == 400
            assert "assigned to users" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_delete_role_not_found(self, mock_neo4j_driver):
        """Deleting non-existent role should return 404."""
        fake_user = _make_pydantic_user(username="admin", role="ADMIN")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        mock_neo4j_driver.execute_query.return_value = ([], None, None)

        with patch("routers.roles.get_db_driver", return_value=mock_neo4j_driver):
            response = client.delete("/api/roles/NonExistent")

            assert response.status_code == 404

        app.dependency_overrides.pop(get_current_active_user, None)
