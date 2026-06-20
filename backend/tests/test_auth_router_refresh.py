"""Integration tests for auth router cookie and refresh token flow."""

import hashlib
import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from middleware import rate_limit
from middleware.rate_limit import MAX_ATTEMPTS, increment_attempts, refresh_token_rate_limit_key
from models.rate_limit_attempt import RateLimitAttempt
from jose import jwt
from postgres_db import Base
from services.auth_service import SECRET_KEY, ALGORITHM
from models.refresh_token import RefreshVerificationResult, RefreshVerificationStatus

# Patch Neo4j driver BEFORE importing anything
_mock_neo4j_driver = MagicMock()
with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
    from main import app
    from postgres_db import get_pg_db
    from services.auth_service import get_current_active_user
    from models.refresh_token import RefreshTokenResponse


client = TestClient(app)


def _extract_cookie_max_age(set_cookie_headers: list[str], cookie_name: str) -> int | None:
    """Return max-age value for a named Set-Cookie header."""
    marker = f"{cookie_name}="
    for header in set_cookie_headers:
        if not header.startswith(marker):
            continue
        for part in header.split(";"):
            item = part.strip().lower()
            if item.startswith("max-age="):
                value = item.split("=", 1)[1]
                return int(value)
    return None


@pytest.fixture(autouse=True)
def rate_limit_db(monkeypatch):
    """Ensure rate-limit state is isolated between tests."""
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

    def test_login_sets_access_and_refresh_token_cookies(self):
        """Login should set access and refresh HttpOnly cookies."""
        mock_user = _make_mock_pg_user(username="testuser", role="OPERATOR")
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.auth.verify_password", return_value=True):
            with patch("routers.auth.create_refresh_token", return_value="new_refresh_token") as mock_create_refresh:
                response = client.post(
                    "/api/auth/token",
                    data={"username": "testuser", "password": "correct_password"},
                )

        assert response.status_code == 200
        # Check Set-Cookie header is present for both cookies (may appear as two Set-Cookie headers)
        set_cookie = response.headers.get("set-cookie", "")
        assert "access_token=" in set_cookie
        assert "refresh_token=" in set_cookie or "refresh_token=new_refresh_token" in set_cookie
        assert "HttpOnly" in set_cookie or "httpOnly" in set_cookie.lower()
        assert "samesite=lax" in set_cookie.lower() or "samesite=strict" in set_cookie.lower()
        mock_create_refresh.assert_called_once()

        app.dependency_overrides.pop(get_pg_db, None)

    def test_login_uses_standard_profile_cookie_max_age(self):
        """Standard profile must apply standard refresh cookie max-age."""
        mock_user = _make_mock_pg_user(username="testuser", role="OPERATOR")
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch.dict(os.environ, {"SESSION_OPERATIONAL_ENABLED": "false", "SESSION_STANDARD_REFRESH_DAYS": "2"}):
            with patch("routers.auth.verify_password", return_value=True):
                response = client.post(
                    "/api/auth/token",
                    data={"username": "testuser", "password": "correct_password"},
                )

        assert response.status_code == 200
        set_cookie_headers = response.headers.get_list("set-cookie")
        refresh_max_age = _extract_cookie_max_age(set_cookie_headers, "refresh_token")
        assert refresh_max_age == 2 * 24 * 60 * 60

        app.dependency_overrides.pop(get_pg_db, None)

    def test_login_uses_operational_profile_cookie_max_age(self):
        """Operational profile must apply operational refresh cookie max-age."""
        mock_user = _make_mock_pg_user(username="ops_user", role="NOC")
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch.dict(
            os.environ,
            {
                "SESSION_OPERATIONAL_ENABLED": "true",
                "SESSION_OPERATIONAL_ROLES": "NOC,SOC",
                "SESSION_OPERATIONAL_REFRESH_DAYS": "4",
            },
        ):
            with patch("routers.auth.verify_password", return_value=True):
                response = client.post(
                    "/api/auth/token",
                    data={"username": "ops_user", "password": "correct_password"},
                )

        assert response.status_code == 200
        set_cookie_headers = response.headers.get_list("set-cookie")
        refresh_max_age = _extract_cookie_max_age(set_cookie_headers, "refresh_token")
        assert refresh_max_age == 4 * 24 * 60 * 60

        app.dependency_overrides.pop(get_pg_db, None)

    def test_login_access_token_includes_session_and_profile_claims(self):
        """Login access token should include session identifier and profile claims."""
        mock_user = _make_mock_pg_user(username="ops_user", role="NOC", user_id=19)
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch.dict(
            os.environ,
            {
                "SESSION_OPERATIONAL_ENABLED": "true",
                "SESSION_OPERATIONAL_ROLES": "NOC,SOC",
                "SESSION_OPERATIONAL_ACCESS_MINUTES": "20",
                "SESSION_OPERATIONAL_REFRESH_DAYS": "10",
            },
        ):
            with patch("routers.auth.verify_password", return_value=True):
                response = client.post(
                    "/api/auth/token",
                    data={"username": "ops_user", "password": "correct_password"},
                )

        assert response.status_code == 200
        payload = jwt.decode(response.json()["access_token"], SECRET_KEY, algorithms=[ALGORITHM])

        assert payload["sid"]
        assert payload["profile"] == "operational"

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

        verification = RefreshVerificationResult(
            status=RefreshVerificationStatus.VALID,
            user_id=42,
            session_id="sid-regular-001",
            policy_profile="standard",
        )

        with patch("routers.auth.verify_refresh_token", return_value=verification):
            with patch("routers.auth.user_repo.get_user_by_id", return_value=mock_user):
                with patch(
                    "routers.auth.create_refresh_token",
                    return_value=("new_refresh_token", MagicMock(id=123)),
                ):
                    with patch("routers.auth.create_access_token", return_value="new_access_token"):
                        response = client.post(
                            "/api/auth/refresh",
                            cookies={"refresh_token": "old_refresh_token"},
                        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" not in data
        assert data["access_token"] == "new_access_token"

        # Check that the new refresh token cookie was set on response
        set_cookie = response.headers.get("set-cookie", "")
        assert "refresh_token=new_refresh_token" in set_cookie

        app.dependency_overrides.pop(get_pg_db, None)

    def test_refresh_includes_session_claim_continuity_and_profile(self):
        """Refresh must propagate prior session ID and policy profile into new access token."""
        mock_user = _make_mock_pg_user(
            username="ops_user",
            role="NOC",
            user_id=99,
        )

        mock_db = MagicMock(spec=Session)
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch.dict(
            os.environ,
            {
                "SESSION_OPERATIONAL_ENABLED": "true",
                "SESSION_OPERATIONAL_ROLES": "NOC,SOC",
                "SESSION_OPERATIONAL_REFRESH_DAYS": "10",
            },
        ):
            with patch(
                "routers.auth.verify_refresh_token",
                return_value=RefreshVerificationResult(
                    status=RefreshVerificationStatus.VALID,
                    user_id=99,
                    session_id="sid-ops-001",
                    policy_profile="operational",
                ),
            ):
                with patch("routers.auth.user_repo.get_user_by_id", return_value=mock_user):
                    response = client.post(
                        "/api/auth/refresh",
                        cookies={"refresh_token": "old_refresh_token"},
                    )

        assert response.status_code == 200
        payload = jwt.decode(response.json()["access_token"], SECRET_KEY, algorithms=[ALGORITHM])

        assert payload["sid"] == "sid-ops-001"
        assert payload["profile"] == "operational"

        set_cookie = response.headers.get("set-cookie", "")
        assert "refresh_token=" in set_cookie

        app.dependency_overrides.pop(get_pg_db, None)

    def test_refresh_invalid_token_returns_401(self):
        """Invalid refresh token should return 401."""
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch(
            "routers.auth.verify_refresh_token",
            return_value=RefreshVerificationResult(status=RefreshVerificationStatus.MISSING),
        ):
            response = client.post(
                "/api/auth/refresh",
                cookies={"refresh_token": "bad_token"},
            )

        assert response.status_code == 401

        app.dependency_overrides.pop(get_pg_db, None)

    def test_refresh_token_rate_limits_after_repeated_failures(self):
        """Too many invalid refresh token attempts should eventually return 429."""
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch(
            "routers.auth.verify_refresh_token",
            return_value=RefreshVerificationResult(status=RefreshVerificationStatus.MISSING),
        ) as mock_verify:
            responses = []
            for _ in range(MAX_ATTEMPTS + 1):  # 4th failure locks immediately
                response = client.post(
                    "/api/auth/refresh",
                    cookies={"refresh_token": "bad_refresh_token"},
                )
                responses.append(response)

        assert [r.status_code for r in responses[:MAX_ATTEMPTS]] == [401] * MAX_ATTEMPTS
        assert responses[MAX_ATTEMPTS].status_code == 429
        assert "Retry-After" in responses[MAX_ATTEMPTS].headers
        assert mock_verify.call_count == MAX_ATTEMPTS + 1

        app.dependency_overrides.pop(get_pg_db, None)

    def test_refresh_rate_limit_persists_hashed_token_key(self, rate_limit_db):
        """Refresh rate limiting should persist a token hash, never the raw token."""
        raw_token = "bad_refresh_token"
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch(
            "routers.auth.verify_refresh_token",
            return_value=RefreshVerificationResult(status=RefreshVerificationStatus.MISSING),
        ):
            response = client.post(
                "/api/auth/refresh",
                cookies={"refresh_token": raw_token},
            )

        assert response.status_code == 401

        session = rate_limit_db()
        try:
            attempts = session.query(RateLimitAttempt).all()
        finally:
            session.close()

        assert len(attempts) == 1
        assert attempts[0].identity_key == f"refresh:{hashlib.sha256(raw_token.encode()).hexdigest()}"
        assert attempts[0].identity_key != raw_token
        assert attempts[0].identity_type == "refresh_token"

        app.dependency_overrides.pop(get_pg_db, None)

    def test_refresh_success_clears_rate_limit_counter(self, rate_limit_db):
        """Successful refresh should reset rate-limit state for that token."""
        refresh_token = "old_refresh_token"
        rate_limit_key = refresh_token_rate_limit_key(refresh_token)
        increment_attempts(rate_limit_key, identity_type="refresh_token")
        increment_attempts(rate_limit_key, identity_type="refresh_token")

        mock_user = _make_mock_pg_user(
            username="testuser",
            role="OPERATOR",
            user_id=42,
        )

        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch(
            "routers.auth.verify_refresh_token",
            return_value=RefreshVerificationResult(
                status=RefreshVerificationStatus.VALID,
                user_id=42,
                session_id="sid-success",
            ),
        ):
            with patch(
                "routers.auth.create_refresh_token",
                return_value=("new_refresh_token", MagicMock(id=123)),
            ):
                with patch("routers.auth.create_access_token", return_value="new_access_token"):
                    response = client.post(
                        "/api/auth/refresh",
                        cookies={"refresh_token": refresh_token},
                    )

        assert response.status_code == 200

        session = rate_limit_db()
        try:
            assert session.query(RateLimitAttempt).filter_by(identity_key=rate_limit_key).first() is None
        finally:
            session.close()

        app.dependency_overrides.pop(get_pg_db, None)

    def test_stale_refresh_recoverable_does_not_increment_rate_limit(self, rate_limit_db):
        """Concurrent stale refresh should recover without adding rate-limit failures."""
        stale_refresh_token = "stale_refresh_token"
        rate_limit_key = refresh_token_rate_limit_key(stale_refresh_token)

        # Seed one failure in DB so we can detect accidental increments.
        increment_attempts(rate_limit_key, identity_type="refresh_token")

        mock_user = _make_mock_pg_user(
            username="testuser",
            role="OPERATOR",
            user_id=42,
        )
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch(
            "routers.auth.verify_refresh_token",
            return_value=RefreshVerificationResult(
                status=RefreshVerificationStatus.ROTATED_STALE_RECOVERABLE,
                user_id=42,
                session_id="sid-recovered",
                token_id=99,
            ),
        ):
            with patch(
                "routers.auth.create_refresh_token",
                return_value=("recovered-refresh-token", MagicMock(id=124)),
            ):
                with patch("routers.auth.try_increment_refresh_recovery_count", return_value=True) as recovery_count:
                    response = client.post(
                        "/api/auth/refresh",
                        cookies={"refresh_token": stale_refresh_token},
                    )

        assert response.status_code == 200
        # stale recovery should reuse session and keep it active
        payload = jwt.decode(response.json()["access_token"], SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sid"] == "sid-recovered"
        recovery_count.assert_called_once_with(mock_db, 99, 3)

        session = rate_limit_db()
        try:
            row = session.query(RateLimitAttempt).filter_by(identity_key=rate_limit_key).first()
            # no extra failures were added by recoverable stale path
            assert row is None
        finally:
            session.close()

        app.dependency_overrides.pop(get_pg_db, None)

    def test_refresh_success_records_session_activity(self):
        """Successful refresh must call record_session_activity once with the
        rotated refresh's session_id and the resolved user_id."""
        mock_user = _make_mock_pg_user(
            username="testuser",
            role="OPERATOR",
            user_id=42,
        )

        mock_db = MagicMock(spec=Session)
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch(
            "routers.auth.verify_refresh_token",
            return_value=RefreshVerificationResult(
                status=RefreshVerificationStatus.VALID,
                user_id=42,
                session_id="sid-bump",
            ),
        ):
            with patch("routers.auth.user_repo.get_user_by_id", return_value=mock_user):
                with patch(
                    "routers.auth.create_refresh_token",
                    return_value=("new_refresh_token", MagicMock(id=123)),
                ):
                    with patch("routers.auth.create_access_token", return_value="new_access_token"):
                        with patch("routers.auth.record_session_activity", return_value=True) as mock_record:
                            response = client.post(
                                "/api/auth/refresh",
                                cookies={"refresh_token": "old_refresh_token"},
                            )

        assert response.status_code == 200
        mock_record.assert_called_once()
        call_args = mock_record.call_args
        assert call_args.args[0] == "sid-bump"
        assert call_args.args[1] == 42

        app.dependency_overrides.pop(get_pg_db, None)

    def test_refresh_idle_expired_clears_cookies_and_emits_audit_event(self):
        """Idle-expired refresh returns 401, clears both cookies, and persists
        a `session.idle_expired` audit event with safe context."""
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.add = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch(
            "routers.auth.verify_refresh_token",
            return_value=RefreshVerificationResult(
                status=RefreshVerificationStatus.IDLE_EXPIRED,
                user_id=42,
                session_id="sid-idle",
                policy_profile="standard",
                token_id=99,
            ),
        ):
            with patch("routers.auth.audit_service") as mock_audit:
                response = client.post(
                    "/api/auth/refresh",
                    cookies={"refresh_token": "old_refresh_token"},
                )

        assert response.status_code == 401
        assert "session timed out" in response.json()["detail"]

        # Both access_token and refresh_token cookies must be cleared (Max-Age=0).
        set_cookie = response.headers.get("set-cookie", "")
        assert "access_token=" in set_cookie
        assert "refresh_token=" in set_cookie
        lowered = set_cookie.lower()
        assert "max-age=0" in lowered

        # Audit event emitted with safe lifecycle context.
        mock_audit.record_auth_event.assert_called_once()
        kwargs = mock_audit.record_auth_event.call_args.kwargs
        assert kwargs["event_type"] == "session.idle_expired"
        assert kwargs["outcome"] == "DENIED"
        assert kwargs["context"]["session_id"] == "sid-idle"
        assert kwargs["context"]["user_id"] == 42
        assert kwargs["context"]["policy_profile"] == "standard"
        assert kwargs["context"]["activity_anchor"] in ("last_activity_at", "created_at")
        # Consistency with `session.activity_recorded`: the throttle window
        # value must appear in both lifecycle events so dashboards and
        # cross-event correlation stay coherent.
        assert isinstance(kwargs["context"]["throttle_seconds"], int)
        assert kwargs["context"]["throttle_seconds"] > 0

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


class TestCookieDomainAndSecure:
    """
    Unit tests for _get_cookie_domain_and_secure() and cookie header behavior.

    Tests different FRONTEND_ORIGIN scenarios to verify:
    - domain is correctly extracted from the origin hostname
    - secure flag is True ONLY when scheme is https
    """

    def test_get_cookie_domain_and_secure_http_ip_origin(self):
        """HTTP origin with IP address: domain=IP, secure=False."""
        from routers.auth import _get_cookie_domain_and_secure
        with patch.dict(os.environ, {"FRONTEND_ORIGIN": "http://10.53.1.22:3010"}):
            domain, secure = _get_cookie_domain_and_secure()
        assert domain == "10.53.1.22"
        assert secure is False

    def test_get_cookie_domain_and_secure_https_hostname(self):
        """HTTPS origin with hostname: domain=hostname, secure=True."""
        from routers.auth import _get_cookie_domain_and_secure
        with patch.dict(os.environ, {"FRONTEND_ORIGIN": "https://app.example.com"}):
            domain, secure = _get_cookie_domain_and_secure()
        assert domain == "app.example.com"
        assert secure is True

    def test_get_cookie_domain_and_secure_localhost(self):
        """Localhost origin: domain=localhost, secure=False."""
        from routers.auth import _get_cookie_domain_and_secure
        with patch.dict(os.environ, {"FRONTEND_ORIGIN": "http://localhost:5173"}):
            domain, secure = _get_cookie_domain_and_secure()
        assert domain == "localhost"
        assert secure is False

    def test_get_cookie_domain_and_secure_missing_origin(self):
        """Missing FRONTEND_ORIGIN: domain=None, secure=False."""
        from routers.auth import _get_cookie_domain_and_secure
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FRONTEND_ORIGIN", None)
            with patch.dict(os.environ, {"FRONTEND_ORIGIN": ""}):
                domain, secure = _get_cookie_domain_and_secure()
        assert domain is None
        assert secure is False

    def test_get_cookie_domain_and_secure_cookie_domain_override(self):
        """COOKIE_DOMAIN override takes precedence and respects FRONTEND_ORIGIN scheme."""
        from routers.auth import _get_cookie_domain_and_secure
        with patch.dict(os.environ, {
            "COOKIE_DOMAIN": "custom.example.com",
            "FRONTEND_ORIGIN": "https://secure.example.com",
        }):
            domain, secure = _get_cookie_domain_and_secure()
        assert domain == "custom.example.com"
        assert secure is True  # derived from FRONTEND_ORIGIN scheme

    def test_get_cookie_domain_and_secure_cookie_domain_none(self):
        """COOKIE_DOMAIN=none disables domain."""
        from routers.auth import _get_cookie_domain_and_secure
        with patch.dict(os.environ, {"COOKIE_DOMAIN": "none", "FRONTEND_ORIGIN": "http://10.53.1.22:3010"}):
            domain, secure = _get_cookie_domain_and_secure()
        assert domain is None
        assert secure is False

    def test_get_cookie_domain_and_secure_cookie_secure_override_true(self):
        """COOKIE_SECURE=true overrides HTTP scheme to secure=True."""
        from routers.auth import _get_cookie_domain_and_secure
        with patch.dict(os.environ, {"COOKIE_SECURE": "true", "FRONTEND_ORIGIN": "http://10.53.1.22:3010"}):
            domain, secure = _get_cookie_domain_and_secure()
        assert domain == "10.53.1.22"
        assert secure is True

    def test_get_cookie_domain_and_secure_cookie_secure_override_false(self):
        """COOKIE_SECURE=false overrides HTTPS scheme to secure=False."""
        from routers.auth import _get_cookie_domain_and_secure
        with patch.dict(os.environ, {"COOKIE_SECURE": "false", "FRONTEND_ORIGIN": "https://secure.example.com"}):
            domain, secure = _get_cookie_domain_and_secure()
        assert domain == "secure.example.com"
        assert secure is False

    def test_login_cookie_has_domain_for_http_ip_origin(self):
        """Login response Set-Cookie header contains correct domain for HTTP IP origin."""
        mock_user = _make_mock_pg_user(username="testuser", role="OPERATOR")
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch.dict(os.environ, {"FRONTEND_ORIGIN": "http://10.53.1.22:3010"}):
            with patch("routers.auth._get_cookie_domain_and_secure", return_value=("10.53.1.22", False)):
                with patch("routers.auth._COOKIE_DOMAIN", "10.53.1.22"):
                    with patch("routers.auth._COOKIE_SECURE", False):
                        with patch("routers.auth.verify_password", return_value=True):
                            response = client.post(
                                "/api/auth/token",
                                data={"username": "testuser", "password": "correct_password"},
                            )

        assert response.status_code == 200
        set_cookie = response.headers.get("set-cookie", "")
        assert "10.53.1.22" in set_cookie
        # Secure=False for HTTP — no Secure flag in cookie
        assert "secure" not in set_cookie.lower() or "Secure" not in set_cookie

        app.dependency_overrides.pop(get_pg_db, None)

    def test_login_cookie_has_secure_flag_for_https_origin(self):
        """Login response Set-Cookie header contains Secure flag for HTTPS origin."""
        mock_user = _make_mock_pg_user(username="testuser", role="OPERATOR")
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        with patch("routers.auth._COOKIE_DOMAIN", "app.example.com"):
            with patch("routers.auth._COOKIE_SECURE", True):
                with patch("routers.auth.verify_password", return_value=True):
                    response = client.post(
                        "/api/auth/token",
                        data={"username": "testuser", "password": "correct_password"},
                    )

        assert response.status_code == 200
        set_cookie = response.headers.get("set-cookie", "")
        assert "app.example.com" in set_cookie
        # Secure=True should appear in cookie header
        assert "Secure" in set_cookie

        app.dependency_overrides.pop(get_pg_db, None)