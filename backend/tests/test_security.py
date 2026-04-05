"""Unit tests for utils/security.py — pure password hashing functions."""

from utils.security import verify_password, get_password_hash


class TestVerifyPassword:
    """Tests for the verify_password function."""

    def test_correct_password_returns_true(self, plain_password, hashed_password):
        assert verify_password(plain_password, hashed_password) is True

    def test_incorrect_password_returns_false(self, hashed_password):
        assert verify_password("WrongP@ss!", hashed_password) is False

    def test_empty_password_returns_false(self, hashed_password):
        assert verify_password("", hashed_password) is False

    def test_case_sensitive(self, hashed_password):
        # Passwords are case-sensitive
        assert verify_password("testp@ss123!", hashed_password) is False


class TestGetPasswordHash:
    """Tests for the get_password_hash function."""

    def test_hash_is_not_plain_text(self, plain_password):
        hashed = get_password_hash(plain_password)
        assert hashed != plain_password

    def test_hash_is_non_empty_string(self, plain_password):
        hashed = get_password_hash(plain_password)
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_same_password_produces_different_hashes(self, plain_password):
        """PBKDF2/SHA256 uses salt — same input should produce different hashes."""
        hash1 = get_password_hash(plain_password)
        hash2 = get_password_hash(plain_password)
        assert hash1 != hash2

    def test_both_hashes_verify_same_password(self, plain_password):
        hash1 = get_password_hash(plain_password)
        hash2 = get_password_hash(plain_password)
        assert verify_password(plain_password, hash1) is True
        assert verify_password(plain_password, hash2) is True
