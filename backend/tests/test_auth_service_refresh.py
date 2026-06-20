"""Unit tests for services/auth_service.py refresh token functions."""

import secrets
import hashlib
import logging
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy.exc import SQLAlchemyError

# Import from auth_service after env is set via conftest
from services import auth_service
from services.auth_service import (
    create_access_token,
    verify_refresh_token,
    revoke_refresh_token,
    revoke_all_user_refresh_tokens,
    create_refresh_token,
    try_increment_refresh_recovery_count,
    record_session_activity,
    SECRET_KEY,
    ALGORITHM,
)
from models.refresh_token import (
    RefreshVerificationStatus,
    hash_token,
    generate_opaque_token,
)
from services.session_policy import (
    get_standard_session_policy,
    get_operational_session_policy,
    get_stale_recovery_grace_seconds,
)


class TestHashToken:
    """Tests for token hashing utility."""

    def test_hash_token_produces_sha256_hex(self):
        token = "test-token-123"
        result = hash_token(token)
        # SHA-256 produces 64 character hex string
        assert len(result) == 64
        assert all(c in '0123456789abcdef' for c in result)

    def test_hash_token_deterministic(self):
        token = "consistent-token"
        h1 = hash_token(token)
        h2 = hash_token(token)
        assert h1 == h2

    def test_different_tokens_produce_different_hashes(self):
        t1 = "token-one"
        t2 = "token-two"
        assert hash_token(t1) != hash_token(t2)

    def test_hash_token_not_reversible(self):
        token = secrets.token_urlsafe(32)
        hashed = hash_token(token)
        # Hash should not be the token itself
        assert hashed != token
        # Hash should not be trivially guessable from token
        assert token not in hashed


class TestGenerateOpaqueToken:
    """Tests for opaque token generation."""

    def test_generates_urlsafe_token(self):
        token = generate_opaque_token()
        # token_urlsafe(32) produces ~43 chars
        assert len(token) >= 40
        # Should be valid URL-safe base64
        assert all(c.isalnum() or c in '-_' for c in token)

    def test_tokens_are_unique(self):
        tokens = {generate_opaque_token() for _ in range(100)}
        # All should be unique (extremely high probability)
        assert len(tokens) == 100

    def test_generated_token_can_be_hashed(self):
        token = generate_opaque_token()
        hashed = hash_token(token)
        assert len(hashed) == 64


class TestVerifyRefreshToken:
    """Tests for refresh token verification with mocked DB."""

    def _mock_rt(
        self,
        token_hash: str,
        user_id: int,
        expires_at: datetime,
        revoked_at: datetime | None = None,
        session_id: str | None = None,
        *,
        revoked_reason: str | None = None,
        rotated_at: datetime | None = None,
        stale_recovery_count: int = 0,
        policy_profile: str = "standard",
        last_activity_at: datetime | None = None,
    ):
        """Create a mock RefreshToken object."""
        rt = MagicMock()
        rt.id = 1
        rt.token_hash = token_hash
        rt.user_id = user_id
        rt.expires_at = expires_at
        rt.revoked_at = revoked_at
        rt.session_id = session_id or "sess-default"
        rt.revoked_reason = revoked_reason
        rt.rotated_at = rotated_at
        rt.stale_recovery_count = stale_recovery_count
        rt.policy_profile = policy_profile
        rt.last_activity_at = last_activity_at or datetime.utcnow() - timedelta(minutes=1)
        return rt

    def test_valid_token_returns_valid_status(self):
        token = "valid-refresh-token"
        token_hash = hash_token(token)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = self._mock_rt(
            token_hash=token_hash,
            user_id=42,
            expires_at=datetime.utcnow() + timedelta(days=7),
            session_id="sess-valid",
            policy_profile="standard",
        )

        result = verify_refresh_token(token, mock_db)
        assert result.status == RefreshVerificationStatus.VALID
        assert result.user_id == 42
        assert result.session_id == "sess-valid"

    def test_unknown_token_returns_missing(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = verify_refresh_token("unknown-token", mock_db)
        assert result.status == RefreshVerificationStatus.MISSING

    def test_revoked_token_returns_revoked(self):
        token = "revoked-token"
        token_hash = hash_token(token)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = self._mock_rt(
            token_hash=token_hash,
            user_id=1,
            expires_at=datetime.utcnow() + timedelta(days=7),
            revoked_at=datetime.utcnow() - timedelta(hours=1),  # revoked in the past
        )

        result = verify_refresh_token(token, mock_db)
        assert result.status == RefreshVerificationStatus.REVOKED

    def test_expired_token_returns_expired(self):
        token = "expired-token"
        token_hash = hash_token(token)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = self._mock_rt(
            token_hash=token_hash,
            user_id=1,
            expires_at=datetime.utcnow() - timedelta(hours=1),  # expired
        )

        result = verify_refresh_token(token, mock_db)
        assert result.status == RefreshVerificationStatus.EXPIRED

    def test_standard_session_idles_out(self):
        token = "idle-token"
        token_hash = hash_token(token)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = self._mock_rt(
            token_hash=token_hash,
            user_id=1,
            expires_at=datetime.utcnow() + timedelta(days=7),
            last_activity_at=datetime.utcnow() - timedelta(minutes=25),
            policy_profile="standard",
        )

        result = verify_refresh_token(token, mock_db)
        assert result.status == RefreshVerificationStatus.IDLE_EXPIRED

    def test_recently_rotated_token_is_recoverable(self):
        token = "stale-token"
        token_hash = hash_token(token)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = self._mock_rt(
            token_hash=token_hash,
            user_id=88,
            expires_at=datetime.utcnow() + timedelta(days=7),
            session_id="sess-88",
            revoked_at=datetime.utcnow() - timedelta(seconds=1),
            revoked_reason="rotated",
            rotated_at=datetime.utcnow() - timedelta(seconds=10),
            stale_recovery_count=0,
            policy_profile="standard",
            last_activity_at=datetime.utcnow(),
        )

        result = verify_refresh_token(token, mock_db)
        assert result.status == RefreshVerificationStatus.ROTATED_STALE_RECOVERABLE
        assert result.should_count_rate_limit is False

    def test_rotated_token_beyond_grace_is_rejected(self):
        token = "late-stale-token"
        token_hash = hash_token(token)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = self._mock_rt(
            token_hash=token_hash,
            user_id=88,
            expires_at=datetime.utcnow() + timedelta(days=7),
            session_id="sess-88",
            revoked_at=datetime.utcnow() - timedelta(seconds=1),
            revoked_reason="rotated",
            rotated_at=datetime.utcnow() - timedelta(seconds=get_stale_recovery_grace_seconds() + 1),
            stale_recovery_count=0,
            policy_profile="standard",
            last_activity_at=datetime.utcnow(),
        )

        result = verify_refresh_token(token, mock_db)
        assert result.status == RefreshVerificationStatus.ROTATED_STALE_REJECTED

    def test_recovery_count_cap_rejects_stale_token(self):
        token = "stale-token-cap"
        token_hash = hash_token(token)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = self._mock_rt(
            token_hash=token_hash,
            user_id=88,
            expires_at=datetime.utcnow() + timedelta(days=7),
            session_id="sess-88",
            revoked_at=datetime.utcnow() - timedelta(seconds=1),
            revoked_reason="rotated",
            rotated_at=datetime.utcnow() - timedelta(seconds=1),
            stale_recovery_count=3,
            policy_profile="standard",
            last_activity_at=datetime.utcnow(),
        )

        result = verify_refresh_token(token, mock_db)
        assert result.status == RefreshVerificationStatus.ROTATED_STALE_REJECTED


class TestTryIncrementRefreshRecoveryCount:
    """Tests for atomic stale recovery reservation."""

    def test_returns_true_when_atomic_update_reserves_recovery(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.update.return_value = 1

        result = try_increment_refresh_recovery_count(mock_db, token_id=123, max_recoveries=3)

        assert result is True
        mock_db.query.return_value.filter.return_value.update.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_returns_false_when_recovery_cap_is_already_consumed(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.update.return_value = 0

        result = try_increment_refresh_recovery_count(mock_db, token_id=123, max_recoveries=3)

        assert result is False
        mock_db.query.return_value.filter.return_value.update.assert_called_once()
        mock_db.commit.assert_called_once()


class TestRevokeRefreshToken:
    """Tests for refresh token revocation."""

    def test_revokes_token_and_sets_revoked_at(self):
        token = "token-to-revoke"
        token_hash = hash_token(token)
        mock_rt = MagicMock()
        mock_rt.revoked_at = None

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_rt

        result = revoke_refresh_token(token, mock_db)

        assert result is True
        assert mock_rt.revoked_at is not None
        mock_db.commit.assert_called_once()

    def test_returns_false_for_unknown_token(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = revoke_refresh_token("unknown-token", mock_db)
        assert result is False


class TestRevokeAllUserRefreshTokens:
    """Tests for revoking all refresh tokens for a user."""

    def test_revokes_all_unrevoked_tokens(self):
        now = datetime.utcnow()
        mock_rts = [
            MagicMock(id=1, revoked_at=None, expires_at=now + timedelta(days=7)),
            MagicMock(id=2, revoked_at=None, expires_at=now + timedelta(days=7)),
        ]

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = mock_rts

        count = revoke_all_user_refresh_tokens(user_id=42, db=mock_db)

        assert count == 2
        assert all(rt.revoked_at is not None for rt in mock_rts)
        mock_db.commit.assert_called_once()

    def test_returns_zero_when_no_tokens(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        count = revoke_all_user_refresh_tokens(user_id=99, db=mock_db)
        assert count == 0


class TestCreateRefreshToken:
    """Tests for refresh token creation."""

    def test_stores_hash_not_plaintext(self):
        mock_db = MagicMock()
        added_rt = None

        def capture_add(rt):
            nonlocal added_rt
            added_rt = rt

        mock_db.add = capture_add
        mock_db.commit = MagicMock()

        token = create_refresh_token(user_id=1, db=mock_db)

        # Token returned is the raw opaque token
        assert token is not None
        assert len(token) >= 40

        # The stored object should have the hash, not the plaintext
        assert added_rt is not None
        assert added_rt.token_hash != token  # hash is different from plaintext
        assert len(added_rt.token_hash) == 64  # SHA-256 hex
        assert added_rt.user_id == 1

    def test_token_hash_can_be_verified_later(self):
        mock_db = MagicMock()
        added_rt = None

        def capture_add(rt):
            nonlocal added_rt
            added_rt = rt

        mock_db.add = capture_add
        mock_db.commit = MagicMock()

        raw_token = create_refresh_token(user_id=99, db=mock_db)

        # The stored hash should match what hash_token produces
        assert added_rt.token_hash == hash_token(raw_token)

    def test_standard_policy_metadata_stored(self):
        mock_db = MagicMock()
        added_rt = None

        def capture_add(rt):
            nonlocal added_rt
            added_rt = rt

        policy = get_standard_session_policy()
        mock_db.add = capture_add
        mock_db.commit = MagicMock()

        session_id = "sess-standard-123"
        token = create_refresh_token(user_id=11, db=mock_db, policy=policy, session_id=session_id)

        assert token is not None
        assert added_rt is not None
        assert added_rt.user_id == 11
        assert added_rt.session_id == session_id
        assert added_rt.policy_profile == "standard"
        assert added_rt.last_activity_at is not None
        assert added_rt.expires_at is not None
        assert added_rt.revoked_reason is None

    def test_operational_policy_stored_with_profile(self):
        mock_db = MagicMock()
        added_rt = None

        def capture_add(rt):
            nonlocal added_rt
            added_rt = rt

        policy = get_operational_session_policy()
        mock_db.add = capture_add
        mock_db.commit = MagicMock()

        session_id = "sess-op-456"
        token = create_refresh_token(user_id=22, db=mock_db, policy=policy, session_id=session_id)

        assert token is not None
        assert added_rt is not None
        assert added_rt.session_id == session_id
        assert added_rt.policy_profile == "operational"
        assert added_rt.last_activity_at is not None
        assert isinstance(added_rt.expires_at, datetime)


class TestRecordSessionActivity:
    """Tests for record_session_activity (PR1 #287).

    Contract (per design.md §PR1 and tasks.md §1.1):
    - Returns False for missing session_id
    - 5 calls within the throttle window on the same session_id produce
      exactly one `db.execute` against the refresh_tokens table
    - Operational profile returns False and writes nothing
    - A raised SQLAlchemyError is caught, returns False, and logs exception
    """

    def setup_method(self):
        # Reset the in-process throttle cache between tests to avoid bleed.
        cache = getattr(auth_service, "_ACTIVITY_THROTTLE_CACHE", None)
        if isinstance(cache, dict):
            cache.clear()

    def test_missing_session_id_returns_false_without_db_write(self):
        mock_db = MagicMock()
        policy = get_standard_session_policy()

        result = record_session_activity(None, user_id=42, db=mock_db, policy=policy)

        assert result is False
        mock_db.execute.assert_not_called()

    def test_five_calls_within_throttle_window_produce_single_db_execute(self, monkeypatch):
        monkeypatch.setenv("SESSION_ACTIVITY_WRITE_THROTTLE_SECONDS", "60")
        mock_db = MagicMock()
        # rowcount=1 simulates a successful UPDATE; the SQL is irrelevant for
        # the contract — only the call count matters.
        result_proxy = MagicMock()
        result_proxy.rowcount = 1
        mock_db.execute.return_value = result_proxy
        policy = get_standard_session_policy()

        outcomes = [
            record_session_activity(
                session_id="sess-throttle",
                user_id=42,
                db=mock_db,
                policy=policy,
            )
            for _ in range(5)
        ]

        assert outcomes.count(True) == 1
        assert outcomes.count(False) == 4
        assert mock_db.execute.call_count == 1

    def test_operational_profile_returns_false_and_writes_nothing(self):
        mock_db = MagicMock()
        policy = get_operational_session_policy()

        result = record_session_activity(
            session_id="sess-operational",
            user_id=42,
            db=mock_db,
            policy=policy,
        )

        assert result is False
        mock_db.execute.assert_not_called()

    def test_sqlalchemy_error_is_caught_returns_false_and_logs_exception(self, caplog):
        mock_db = MagicMock()
        mock_db.execute.side_effect = SQLAlchemyError("boom")
        policy = get_standard_session_policy()

        with caplog.at_level(logging.DEBUG, logger="services.auth_service"):
            result = record_session_activity(
                session_id="sess-failing",
                user_id=42,
                db=mock_db,
                policy=policy,
            )

        assert result is False
        # logger.exception() records an ERROR-level log; caplog records the
        # formatted exception text.
        assert any(
            record.levelno == logging.ERROR
            and "boom" in record.getMessage()
            for record in caplog.records
        )