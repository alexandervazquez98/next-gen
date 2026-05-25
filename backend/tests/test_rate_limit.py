"""Unit tests for middleware/rate_limit.py — persistent auth rate limiting."""

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from middleware import rate_limit
from middleware.rate_limit import (
    MAX_ATTEMPTS,
    AttemptInfo,
    check_rate_limit,
    clear_attempts,
    get_attempt_info,
    increment_attempts,
    is_locked,
)
from models.rate_limit_attempt import RateLimitAttempt
from postgres_db import Base


@pytest.fixture
def rate_limit_db(monkeypatch):
    """Use an isolated SQLite DB for persistent rate-limit tests."""
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


class TestAttemptInfo:
    """Tests for AttemptInfo NamedTuple compatibility."""

    def test_attempt_info_default(self):
        info = AttemptInfo(count=0, locked_until=None)
        assert info.count == 0
        assert info.locked_until is None


class TestIncrementAttempts:
    """Tests for failed attempt tracking."""

    def test_first_attempt_increments_count(self, rate_limit_db):
        info = increment_attempts("user1")
        assert info.count == 1
        assert info.locked_until is None

    def test_third_attempt_still_no_lockout(self, rate_limit_db):
        """3 attempts should NOT trigger lockout; lockout is on the 4th failed attempt."""
        for _ in range(3):
            info = increment_attempts("user1")
        assert info.count == 3
        assert info.locked_until is None

    def test_fourth_attempt_triggers_lockout(self, rate_limit_db):
        """4th consecutive failed attempt triggers 15-minute lockout."""
        for _ in range(3):
            increment_attempts("user1")
        info = increment_attempts("user1")
        assert info.count == 4
        assert info.locked_until is not None
        assert info.locked_until > datetime.utcnow()

    def test_separate_users_have_separate_counters(self, rate_limit_db):
        increment_attempts("user1")
        increment_attempts("user1")
        info_user2 = increment_attempts("user2")
        assert info_user2.count == 1

    def test_user_and_refresh_namespaces_do_not_collide(self, rate_limit_db):
        shared_key = "refresh:shared"
        user_info = increment_attempts(shared_key)
        refresh_info = increment_attempts(shared_key, identity_type="refresh_token")

        assert user_info.count == 1
        assert refresh_info.count == 1

        session = rate_limit_db()
        try:
            rows = session.query(RateLimitAttempt).order_by(RateLimitAttempt.identity_type).all()
        finally:
            session.close()

        assert {(row.identity_type, row.identity_key) for row in rows} == {
            ("refresh_token", "refresh:shared"),
            ("username", "user:refresh:shared"),
        }

    def test_long_username_key_is_persisted_without_length_failure(self, rate_limit_db):
        long_username = "u" * 300
        info = increment_attempts(long_username)
        assert info.count == 1

        session = rate_limit_db()
        try:
            row = session.query(RateLimitAttempt).filter_by(identity_type="username").one()
        finally:
            session.close()

        assert row.identity_key == f"user:{long_username}"

    def test_username_prefix_sentinel_does_not_collide(self, rate_limit_db):
        increment_attempts("alice")
        increment_attempts("user:alice")

        session = rate_limit_db()
        try:
            rows = session.query(RateLimitAttempt).order_by(RateLimitAttempt.identity_key).all()
        finally:
            session.close()

        assert [row.identity_key for row in rows] == ["user:alice", "user:user:alice"]

    def test_expired_lock_resets_before_incrementing(self, rate_limit_db):
        session = rate_limit_db()
        try:
            session.add(
                RateLimitAttempt(
                    identity_key="user:expired_user",
                    identity_type="username",
                    attempt_count=4,
                    locked_until=datetime.utcnow() - timedelta(minutes=1),
                    updated_at=datetime.utcnow() - timedelta(minutes=20),
                )
            )
            session.commit()
        finally:
            session.close()

        info = increment_attempts("expired_user")
        assert info.count == 1
        assert info.locked_until is None


class TestClearAttempts:
    """Tests for clearing attempts on successful auth."""

    def test_clear_removes_user_from_store(self, rate_limit_db):
        increment_attempts("user1")
        increment_attempts("user1")
        clear_attempts("user1")
        assert get_attempt_info("user1") == AttemptInfo(count=0, locked_until=None)

    def test_clear_nonexistent_user_no_error(self, rate_limit_db):
        clear_attempts("nonexistent")  # Should not raise


class TestIsLocked:
    """Tests for lockout detection."""

    def test_not_locked_when_no_attempts(self, rate_limit_db):
        locked, retry_after = is_locked("anyone")
        assert locked is False
        assert retry_after is None

    def test_locked_after_exceeding_attempts(self, rate_limit_db):
        for _ in range(MAX_ATTEMPTS):
            increment_attempts("locked_user")
        increment_attempts("locked_user")  # 4th triggers lockout
        locked, retry_after = is_locked("locked_user")
        assert locked is True
        assert retry_after is not None
        assert retry_after > 0

    def test_expired_lock_returns_not_locked_and_cleans_row(self, rate_limit_db):
        session = rate_limit_db()
        try:
            session.add(
                RateLimitAttempt(
                    identity_key="user:user_with_expired_lock",
                    identity_type="username",
                    attempt_count=4,
                    locked_until=datetime.utcnow() - timedelta(minutes=1),
                    updated_at=datetime.utcnow() - timedelta(minutes=20),
                )
            )
            session.commit()
        finally:
            session.close()

        locked, retry_after = is_locked("user_with_expired_lock")
        assert locked is False
        assert retry_after is None

        session = rate_limit_db()
        try:
            assert session.query(RateLimitAttempt).filter_by(identity_key="user:user_with_expired_lock").first() is None
        finally:
            session.close()


class TestCheckRateLimit:
    """Tests for the check_rate_limit utility function."""

    def test_no_exception_for_unlocked_user(self, rate_limit_db):
        check_rate_limit("anyuser")

    def test_raises_http_429_for_locked_user(self, rate_limit_db):
        for _ in range(MAX_ATTEMPTS):
            increment_attempts("lockeduser")
        increment_attempts("lockeduser")

        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit("lockeduser")
        assert exc_info.value.status_code == 429
        assert "Retry-After" in exc_info.value.headers

    def test_retry_after_header_value(self, rate_limit_db):
        for _ in range(MAX_ATTEMPTS):
            increment_attempts("lockeduser")
        increment_attempts("lockeduser")

        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit("lockeduser")
        retry_after = int(exc_info.value.headers["Retry-After"])
        assert retry_after >= 800

    def test_retry_after_header_minimum_one_second(self, rate_limit_db, monkeypatch):
        monkeypatch.setattr(rate_limit, "is_locked", lambda *_args, **_kwargs: (True, 0))

        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit("lockeduser")

        assert exc_info.value.headers["Retry-After"] == "1"
