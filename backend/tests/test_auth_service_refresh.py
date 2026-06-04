"""Unit tests for services/auth_service.py refresh token functions."""

import secrets
import hashlib
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# Import from auth_service after env is set via conftest
from services.auth_service import (
    create_access_token,
    verify_refresh_token,
    revoke_refresh_token,
    revoke_all_user_refresh_tokens,
    create_refresh_token,
    SECRET_KEY,
    ALGORITHM,
)
from models.refresh_token import hash_token, generate_opaque_token
from services.session_policy import get_standard_session_policy, get_operational_session_policy


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

    def _mock_rt(self, token_hash: str, user_id: int, expires_at: datetime, revoked_at: datetime | None = None, session_id: str | None = None):
        """Create a mock RefreshToken object."""
        rt = MagicMock()
        rt.token_hash = token_hash
        rt.user_id = user_id
        rt.expires_at = expires_at
        rt.revoked_at = revoked_at
        rt.session_id = session_id
        return rt

    def test_returns_user_id_for_valid_token(self):
        token = "valid-refresh-token"
        token_hash = hash_token(token)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = self._mock_rt(
            token_hash=token_hash,
            user_id=42,
            expires_at=datetime.utcnow() + timedelta(days=7),
        )

        result = verify_refresh_token(token, mock_db)
        assert result == 42

    def test_returns_none_for_unknown_token(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = verify_refresh_token("unknown-token", mock_db)
        assert result is None

    def test_returns_none_for_revoked_token(self):
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
        assert result is None

    def test_returns_none_for_expired_token(self):
        token = "expired-token"
        token_hash = hash_token(token)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = self._mock_rt(
            token_hash=token_hash,
            user_id=1,
            expires_at=datetime.utcnow() - timedelta(hours=1),  # expired
        )

        result = verify_refresh_token(token, mock_db)
        assert result is None

    def test_returns_session_metadata_when_requested(self):
        token = "token-with-session"
        token_hash = hash_token(token)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = self._mock_rt(
            token_hash=token_hash,
            user_id=77,
            expires_at=datetime.utcnow() + timedelta(days=7),
            session_id="sess-77",
        )

        result = verify_refresh_token(token, mock_db, include_session_metadata=True)
        assert result == (77, "sess-77")


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