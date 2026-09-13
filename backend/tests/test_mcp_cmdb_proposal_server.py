"""Tests for the CMDB proposal MCP server wrapper — feat-cmdb-ai-handoff (T-2.6).

The MCP server is a thin in-process wrapper that delegates to
``services.cmdb_proposal_service`` directly (no HTTP loopback) — matching
the precedent in ``ai_guard_service`` for in-process delegation.

Exposes 4 tools:
- propose_ci
- list_proposals
- approve_proposal
- revoke_proposal

Each tool:
- Resolves a bearer token + scope claim (CI_PROPOSAL_SCOPE or similar).
- Validates scope permissions.
- Calls the service layer.
- Rate-limits per token (60/min) and per user (30/min) — CMDB_PROPOSAL_RPM.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_service(monkeypatch):
    """Patch cmdb_proposal_service methods with controllable stubs."""
    fake = MagicMock()
    monkeypatch.setattr("mcp.cmdb_proposal_server._service", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset the in-process rate limiter between tests so state doesn't leak."""
    from mcp import cmdb_proposal_server as mcp

    mcp._rate_limiter._token_calls.clear()
    mcp._rate_limiter._user_calls.clear()
    yield
    mcp._rate_limiter._token_calls.clear()
    mcp._rate_limiter._user_calls.clear()


class TestProposeCiTool:
    def test_propose_ci_tool_201(self, monkeypatch, fake_service):
        """propose_ci tool delegates to create_proposal and returns proposal_id."""
        from mcp import cmdb_proposal_server as mcp

        # Stub the resolver + rate limit so we exercise the tool's core logic.
        monkeypatch.setattr(
            mcp,
            "_resolve_user_from_bearer",
            lambda t: MagicMock(
                username="ai-bot",
                role="AI_OPERATOR",
                permissions=["AI_PROPOSE_CI"],
                allowed_locations=[],
                disabled=False,
            ),
        )
        monkeypatch.setattr(mcp, "_check_tool_rate_limit", lambda *a, **kw: True)
        fake_service.create_proposal.return_value = {
            "id": "prop-1",
            "status": "DRAFT",
            "version": 1,
        }

        result = mcp.tool_propose_ci(
            token="Bearer.tok",
            manifest={
                "schema_version": 1,
                "ci": {
                    "id": "CI-NEW",
                    "label": "Core Router",
                    "category": "Router",
                    "type": "Router",
                },
            },
        )
        assert result["proposal_id"] == "prop-1"
        assert result["status"] == "DRAFT"
        fake_service.create_proposal.assert_called_once()


class TestListProposalsTool:
    def test_list_proposals_tool_200(self, monkeypatch, fake_service):
        """list_proposals tool delegates to service.list_proposals."""
        from mcp import cmdb_proposal_server as mcp

        monkeypatch.setattr(
            mcp,
            "_resolve_user_from_bearer",
            lambda t: MagicMock(
                username="viewer",
                role="VIEWER",
                permissions=["CI_VIEW"],
                allowed_locations=[],
                disabled=False,
            ),
        )
        monkeypatch.setattr(mcp, "_check_tool_rate_limit", lambda *a, **kw: True)
        fake_service.list_proposals.return_value = {
            "rows": [{"id": "prop-1", "status": "DRAFT"}],
            "total": 1,
            "page": 1,
            "page_size": 50,
        }

        result = mcp.tool_list_proposals(
            token="Bearer.tok",
            status="DRAFT",
            page=1,
            page_size=50,
        )
        assert "rows" in result
        assert result["total"] == 1
        fake_service.list_proposals.assert_called_once()


class TestApproveProposalTool:
    def test_approve_proposal_tool_200(self, monkeypatch, fake_service):
        """approve_proposal tool delegates to service.approve_proposal."""
        from mcp import cmdb_proposal_server as mcp

        monkeypatch.setattr(
            mcp,
            "_resolve_user_from_bearer",
            lambda t: MagicMock(
                username="alice",
                role="OPERATOR",
                permissions=["CI_APPROVE_PROPOSAL"],
                allowed_locations=[],
                disabled=False,
            ),
        )
        monkeypatch.setattr(mcp, "_check_tool_rate_limit", lambda *a, **kw: True)
        fake_service.approve_proposal.return_value = {
            "id": "prop-1",
            "status": "APPROVED",
            "version": 2,
            "resulted_ci_id": "CI-NEW",
        }

        result = mcp.tool_approve_proposal(
            token="Bearer.tok",
            proposal_id="prop-1",
            version=1,
        )
        assert result["status"] == "APPROVED"
        assert result["resulted_ci_id"] == "CI-NEW"
        fake_service.approve_proposal.assert_called_once()


class TestRevokeProposalTool:
    def test_revoke_proposal_tool_200(self, monkeypatch, fake_service):
        """revoke_proposal tool delegates to service.revoke_proposal."""
        from mcp import cmdb_proposal_server as mcp

        monkeypatch.setattr(
            mcp,
            "_resolve_user_from_bearer",
            lambda t: MagicMock(
                username="alice",
                role="OPERATOR",
                permissions=["CI_APPROVE_PROPOSAL"],
                allowed_locations=[],
                disabled=False,
            ),
        )
        monkeypatch.setattr(mcp, "_check_tool_rate_limit", lambda *a, **kw: True)
        fake_service.revoke_proposal.return_value = {
            "id": "prop-1",
            "status": "REVOKED",
            "version": 2,
        }

        result = mcp.tool_revoke_proposal(
            token="Bearer.tok",
            proposal_id="prop-1",
            version=1,
            reason="stale",
        )
        assert result["status"] == "REVOKED"
        fake_service.revoke_proposal.assert_called_once()


class TestAuthAndRateLimit:
    def test_mcp_401_without_bearer(self, monkeypatch, fake_service):
        """A missing/invalid bearer MUST raise HTTPException(401)."""
        from fastapi import HTTPException
        from mcp import cmdb_proposal_server as mcp

        monkeypatch.setattr(
            mcp,
            "_resolve_user_from_bearer",
            lambda t: (_ for _ in ()).throw(
                HTTPException(status_code=401, detail="Not authenticated")
            ),
        )
        with pytest.raises(HTTPException) as exc:
            mcp.tool_propose_ci(token=None, manifest={})
        assert exc.value.status_code == 401

    def test_mcp_403_with_wrong_scope(self, monkeypatch, fake_service):
        """A user without the right permission MUST raise HTTPException(403)."""
        from fastapi import HTTPException
        from mcp import cmdb_proposal_server as mcp

        # The resolver returns a user that lacks AI_PROPOSE_CI.
        monkeypatch.setattr(
            mcp,
            "_resolve_user_from_bearer",
            lambda t: MagicMock(
                username="viewer",
                role="VIEWER",
                permissions=[],
                allowed_locations=[],
                disabled=False,
            ),
        )

        with pytest.raises(HTTPException) as exc:
            mcp.tool_propose_ci(
                token="Bearer.tok",
                manifest={
                    "schema_version": 1,
                    "ci": {"id": "X", "label": "Y", "category": "Router", "type": "Router"},
                },
            )
        assert exc.value.status_code == 403


class TestRateLimit:
    def test_check_tool_rate_limit_enforces_per_token(self, monkeypatch):
        """Rate limit MUST enforce CMDB_PROPOSAL_RPM per token."""
        from mcp import cmdb_proposal_server as mcp

        monkeypatch.setenv("CMDB_PROPOSAL_RPM", "2")
        # First 2 calls succeed
        assert mcp._check_tool_rate_limit("token-1", "user-1") is True
        assert mcp._check_tool_rate_limit("token-1", "user-1") is True
        # Third call MUST be blocked
        assert mcp._check_tool_rate_limit("token-1", "user-1") is False

    def test_check_tool_rate_limit_per_user_separate_from_token(self, monkeypatch):
        """Per-user limit (30/min) is a separate counter from per-token."""
        from mcp import cmdb_proposal_server as mcp

        monkeypatch.setenv("CMDB_PROPOSAL_RPM", "60")
        monkeypatch.setenv("CMDB_PROPOSAL_USER_RPM", "2")
        # 2 calls from different tokens but same user — third call blocked by user limit.
        assert mcp._check_tool_rate_limit("token-1", "user-1") is True
        assert mcp._check_tool_rate_limit("token-2", "user-1") is True
        assert mcp._check_tool_rate_limit("token-3", "user-1") is False
