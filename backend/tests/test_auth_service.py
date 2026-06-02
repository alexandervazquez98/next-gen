"""Unit tests for services/auth_service.py — pure logic functions (no DB)."""

import pytest
from datetime import timedelta
from fastapi import HTTPException
from jose import jwt, JWTError
from services.auth_service import (
    create_access_token,
    check_permission,
    get_current_ai_agent,
    AIAgentInfo,
    SECRET_KEY,
    ALGORITHM,
)
from models.user import UserPermission, User, AIPermission


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

    def test_token_includes_session_and_profile_claims(self):
        token = create_access_token(
            data={"sub": "admin", "role": "ADMIN", "sid": "sess-123", "profile": "operational"}
        )
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sid"] == "sess-123"
        assert payload["profile"] == "operational"

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


class TestGetCurrentAiAgent:
    """Tests for get_current_ai_agent permission claim hardening."""

    @staticmethod
    def _make_ai_token(extra_claims: dict):
        """Build a minimal AI-agent token with required claims."""
        base_payload = {
            "sub": "agent-1",
            "type": "ai_agent",
            "role": "AI_OPERATOR",
        }
        base_payload.update(extra_claims)
        return create_access_token(base_payload)

    @pytest.mark.asyncio
    async def test_ai_agent_with_missing_permissions_authenticates_with_empty_permissions(self):
        """Missing permissions claim must authenticate with an empty permission list."""
        token = self._make_ai_token({})
        result = await get_current_ai_agent(token=token, db=None)

        assert isinstance(result, AIAgentInfo)
        assert result.ai_agent_id == "agent-1"
        assert result.persona == "AI_OPERATOR"
        assert result.permissions == []

    @pytest.mark.asyncio
    async def test_ai_agent_with_valid_permissions_authenticates(self):
        """Valid AIPermission values are accepted and returned unchanged."""
        token = self._make_ai_token(
            {
                "permissions": [
                    AIPermission.AI_VIEW_ALL.value,
                    AIPermission.AI_RUN_DIAGNOSTIC.value,
                ]
            }
        )
        result = await get_current_ai_agent(token=token, db=None)

        assert result.permissions == [
            AIPermission.AI_VIEW_ALL.value,
            AIPermission.AI_RUN_DIAGNOSTIC.value,
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad_permissions",
        [
            ["ADMIN"],
            ["USER_MANAGE"],
            ["BOGUS"],
            ["AI_VIEW_ALL", 123],
            "AI_VIEW_ALL",
            {"permission": "AI_VIEW_ALL"},
            None,
        ],
    )
    async def test_ai_agent_permissions_are_strictly_validated(self, bad_permissions):
        """Malformed or unauthorized permissions fail closed with HTTP 403."""
        token = self._make_ai_token({"permissions": bad_permissions})

        with pytest.raises(HTTPException) as exc_info:
            await get_current_ai_agent(token=token, db=None)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_ai_agent_with_wrong_token_type_is_rejected(self):
        """AI agent auth must reject tokens whose `type` is not `ai_agent`."""
        token = self._make_ai_token({"type": "human"})

        with pytest.raises(HTTPException) as exc_info:
            await get_current_ai_agent(token=token, db=None)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_ai_agent_with_missing_persona_is_rejected(self):
        """AI agent auth must reject tokens without a persona/role claim."""
        payload = {
            "sub": "agent-1",
            "type": "ai_agent",
        }
        token = create_access_token(payload)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_ai_agent(token=token, db=None)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_ai_agent_with_unsupported_persona_is_rejected(self):
        """AI agent auth must reject persona values outside the allow-list."""
        token = self._make_ai_token({"role": "HUMAN_OPERATOR"})

        with pytest.raises(HTTPException) as exc_info:
            await get_current_ai_agent(token=token, db=None)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_ai_agent_with_missing_subject_is_rejected(self):
        """AI agent auth must reject tokens missing a `sub` claim."""
        payload = {
            "type": "ai_agent",
            "role": "AI_OPERATOR",
            "permissions": [AIPermission.AI_VIEW_ALL.value],
        }
        token = create_access_token(payload)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_ai_agent(token=token, db=None)

        assert exc_info.value.status_code == 401
