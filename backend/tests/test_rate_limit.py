"""Unit tests for middleware/rate_limit.py — login rate limiting logic."""

import pytest
from datetime import datetime, timedelta

from middleware.rate_limit import (
    RATE_LIMIT_STORE,
    MAX_ATTEMPTS,
    LOCKOUT_DURATION,
    AttemptInfo,
    get_attempt_info,
    increment_attempts,
    clear_attempts,
    is_locked,
    check_rate_limit,
)


@pytest.fixture(autouse=True)
def clean_store():
    """Clear the rate limit store before and after each test."""
    RATE_LIMIT_STORE.clear()
    yield
    RATE_LIMIT_STORE.clear()


class TestAttemptInfo:
    """Tests for AttemptInfo NamedTuple."""

    def test_attempt_info_default(self):
        info = AttemptInfo(count=0, locked_until=None)
        assert info.count == 0
        assert info.locked_until is None


class TestIncrementAttempts:
    """Tests for failed attempt tracking."""

    def test_first_attempt_increments_count(self):
        info = increment_attempts("user1")
        assert info.count == 1
        assert info.locked_until is None

    def test_third_attempt_still_no_lockout(self):
        """3 attempts should NOT trigger lockout — lockout is on the 4th attempt (after 3 consecutive failures)."""
        for _ in range(3):
            info = increment_attempts("user1")
        assert info.count == 3
        assert info.locked_until is None

    def test_fourth_attempt_triggers_lockout(self):
        """
        4th consecutive failed attempt triggers 15-min lockout.
        Spec: "After 3 consecutive failed attempts, account is locked for 15 minutes"
        → 3 failures → lockout → 4th attempt blocked.
        """
        for _ in range(3):
            increment_attempts("user1")
        info = increment_attempts("user1")
        assert info.count == 4
        assert info.locked_until is not None
        assert info.locked_until > datetime.utcnow()

    def test_separate_users_have_separate_counters(self):
        increment_attempts("user1")
        increment_attempts("user1")
        info_user2 = increment_attempts("user2")
        assert info_user2.count == 1


class TestClearAttempts:
    """Tests for clearing attempts on successful login."""

    def test_clear_removes_user_from_store(self):
        increment_attempts("user1")
        increment_attempts("user1")
        clear_attempts("user1")
        assert "user1" not in RATE_LIMIT_STORE

    def test_clear_nonexistent_user_no_error(self):
        clear_attempts("nonexistent")  # Should not raise


class TestIsLocked:
    """Tests for lockout detection."""

    def test_not_locked_when_no_attempts(self):
        locked, retry_after = is_locked("anyone")
        assert locked is False
        assert retry_after is None

    def test_locked_after_exceeding_attempts(self):
        for _ in range(MAX_ATTEMPTS):
            increment_attempts("locked_user")
        increment_attempts("locked_user")  # 4th triggers lockout
        locked, retry_after = is_locked("locked_user")
        assert locked is True
        assert retry_after is not None
        assert retry_after > 0

    def test_expired_lock_returns_not_locked(self):
        # Manually set an expired lock
        RATE_LIMIT_STORE["user_with_expired_lock"] = AttemptInfo(
            count=4,
            locked_until=datetime.utcnow() - timedelta(minutes=1),  # expired
        )
        locked, retry_after = is_locked("user_with_expired_lock")
        assert locked is False
        # Lock should be cleared from store
        assert "user_with_expired_lock" not in RATE_LIMIT_STORE


class TestCheckRateLimit:
    """Tests for the check_rate_limit utility function."""

    def test_no_exception_for_unlocked_user(self):
        # Should not raise
        check_rate_limit("anyuser")

    def test_raises_http_429_for_locked_user(self):
        for _ in range(MAX_ATTEMPTS):
            increment_attempts("lockeduser")
        increment_attempts("lockeduser")

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit("lockeduser")
        assert exc_info.value.status_code == 429
        assert "Retry-After" in exc_info.value.headers

    def test_retry_after_header_value(self):
        for _ in range(MAX_ATTEMPTS):
            increment_attempts("lockeduser")
        increment_attempts("lockeduser")

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit("lockeduser")
        retry_after = int(exc_info.value.headers["Retry-After"])
        # Should be approximately 15 minutes in seconds (900), allow some tolerance
        assert retry_after >= 800