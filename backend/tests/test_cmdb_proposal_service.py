"""Service tests for CMDB proposal lifecycle — feat-cmdb-ai-handoff.

Stub-based unit tests (no live driver). Service composes:
- cmdb_proposal_repo (for the :CIProposal writes)
- node_service (for the actual :CI write on approve)
- audit_service (for the CI_PROPOSAL_* rows)
- ai_guard_service (for propose_ci cooldown + bulk threshold)
- catalog_service (for live Category resolution)

Each scenario uses a focused stub so the assertions exercise the service
contract, not the underlying drivers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from models.user import AIPermission, User, UserPermission
from services import audit_service

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


@dataclass
class _RepoStub:
    """Stub of CmdbProposalRepo with controllable returns."""

    created_kwargs: dict | None = None
    create_draft_raises: Exception | None = None
    approve_returns: dict | None = None
    approve_raises: Exception | None = None
    revoke_returns: dict | None = None
    revoke_raises: Exception | None = None
    get_returns: dict | None = None
    list_returns: list[dict] = field(default_factory=list)

    def create_draft(self, **kwargs):
        if self.create_draft_raises:
            raise self.create_draft_raises
        self.created_kwargs = kwargs
        return {
            "id": kwargs["proposal_id"],
            "status": "DRAFT",
            "version": 1,
            "manifest_json": kwargs["manifest_json"],
            "applied_manifest_json": None,
            "proposed_by": kwargs["proposed_by"],
            "proposed_role": kwargs["proposed_role"],
            "reviewed_by": None,
            "reviewed_at": None,
            "created_at": "2026-09-13T00:00:00Z",
            "updated_at": "2026-09-13T00:00:00Z",
            "resulted_ci_id": None,
            "revoke_reason": None,
            "proposed_category": kwargs.get("proposed_category"),
            "ci_id": kwargs.get("ci_id"),
        }

    def approve(self, **kwargs):
        if self.approve_raises:
            raise self.approve_raises
        return self.approve_returns or {
            "id": kwargs["proposal_id"],
            "status": "APPROVED",
            "version": 2,
            "manifest_json": self._manifest_for_approve(),
            "applied_manifest_json": kwargs.get("applied_manifest_json"),
            "proposed_by": "ai-bot",
            "proposed_role": "AI_OPERATOR",
            "reviewed_by": "alice",
            "reviewed_at": "2026-09-13T00:00:00Z",
            "created_at": "2026-09-13T00:00:00Z",
            "updated_at": "2026-09-13T00:00:00Z",
            "resulted_ci_id": kwargs.get("resulted_ci_id"),
            "revoke_reason": None,
            "proposed_category": "Router",
            "ci_id": kwargs.get("resulted_ci_id"),
        }

    def revoke(self, **kwargs):
        if self.revoke_raises:
            raise self.revoke_raises
        return self.revoke_returns or {
            "id": kwargs["proposal_id"],
            "status": "REVOKED",
            "version": kwargs.get("expected_version", 1) + 1,
            "manifest_json": self._manifest_for_revoke(),
            "applied_manifest_json": None,
            "proposed_by": "ai-bot",
            "proposed_role": "AI_OPERATOR",
            "reviewed_by": "alice",
            "reviewed_at": "2026-09-13T00:00:00Z",
            "created_at": "2026-09-13T00:00:00Z",
            "updated_at": "2026-09-13T00:00:00Z",
            "resulted_ci_id": None,
            "revoke_reason": kwargs.get("reason"),
            "proposed_category": "Router",
            "ci_id": "CI-NEW",
        }

    def _manifest_for_approve(self) -> str:
        return json.dumps(
            {
                "schema_version": 1,
                "ci": {
                    "id": "CI-NEW",
                    "label": "Core Router",
                    "category": "Router",
                    "type": "Router",
                },
                "rationale": "Spoke router",
            }
        )

    def _manifest_for_revoke(self) -> str:
        return json.dumps(
            {
                "schema_version": 1,
                "ci": {
                    "id": "CI-NEW",
                    "label": "Core Router",
                    "category": "Router",
                    "type": "Router",
                },
                "rationale": "Spoke router",
            }
        )

    def get(self, proposal_id):
        if self.get_returns is not None:
            return self.get_returns
        # Default: return a DRAFT proposal with valid manifest for the requested id.
        return {
            "id": proposal_id,
            "status": "DRAFT",
            "version": 1,
            "manifest_json": self._manifest_for_approve(),
            "applied_manifest_json": None,
            "proposed_by": "ai-bot",
            "proposed_role": "AI_OPERATOR",
            "reviewed_by": None,
            "reviewed_at": None,
            "created_at": "2026-09-13T00:00:00Z",
            "updated_at": "2026-09-13T00:00:00Z",
            "resulted_ci_id": None,
            "revoke_reason": None,
            "proposed_category": "Router",
            "ci_id": "CI-NEW",
        }

    def list(self, **kwargs):
        return self.list_returns


@dataclass
class _GuardStub:
    """Stub of ai_guard_service result tuple semantics."""

    allowed: bool = True
    reason: str | None = None
    reason_code: str | None = None

    def check_all_guards(self, *args, **kwargs):
        return MagicMock(
            allowed=self.allowed,
            reason=self.reason,
            cooldown_remaining_seconds=0,
        )

    def record_operation(self, *args, **kwargs):
        return None


def _user(role: str = "AI_OPERATOR", permissions: list[str] | None = None) -> User:
    return User(
        username="ai-bot-bogota",
        role=role,
        permissions=permissions or [],
        allowed_locations=[],
    )


@pytest.fixture
def audit_calls(monkeypatch):
    """Capture record_critical_change kwargs."""
    calls: list[dict] = []

    def _record(**kwargs):
        calls.append(kwargs)
        return None

    def _denied(**kwargs):
        raise AssertionError("record_denied hardcodes ACCESS_DENIED; use record_critical_change")

    monkeypatch.setattr(audit_service, "record_critical_change", _record)
    monkeypatch.setattr(audit_service, "record_denied", _denied)
    return calls


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateProposalHappyPath:
    def test_create_proposal_happy_path(self, monkeypatch, audit_calls):
        """An AI agent with AI_PROPOSE_CI can submit a manifest; gets a proposal_id back."""
        from services import cmdb_proposal_service as svc

        repo = _RepoStub()
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)
        # category resolve — Router is valid
        monkeypatch.setattr(
            svc, "_resolve_category", lambda cat: ["Router", "Server"] if cat == "Router" else None
        )
        # CI collision check — none
        monkeypatch.setattr(svc, "_ci_id_exists", lambda ci_id: False)
        guard = _GuardStub(allowed=True)
        monkeypatch.setattr(svc, "_get_guard", lambda: guard)
        # Skip actual node_service import — we don't call create_update_node here

        user = _user(role="AI_OPERATOR", permissions=[AIPermission.AI_PROPOSE_CI.value])
        manifest = {
            "schema_version": 1,
            "ci": {
                "id": "CI-NEW",
                "label": "Core Router Bogotá",
                "category": "Router",
                "type": "Router",
            },
            "rationale": "Spoke router",
        }

        result = svc.create_proposal(
            manifest=manifest,
            user=user,
            ai_agent_id="ai-bot-bogota",
            db=object(),
        )

        assert result["status"] == "DRAFT"
        assert result["version"] == 1
        assert result["id"] == repo.created_kwargs["proposal_id"]
        # Audit row written
        assert len(audit_calls) == 1
        audit = audit_calls[0]
        assert audit["event_type"] == "CI_PROPOSAL_CREATE"
        assert audit["outcome"] == "SUCCESS"
        assert audit["context"]["proposal_id"] == result["id"]
        assert audit["context"]["next_state"] == "DRAFT"
        assert audit["context"]["version"] == 1


class TestCreateProposalValidation:
    def test_create_unknown_category_422(self, monkeypatch):
        """An unknown category MUST raise HTTPException(422, reason='unknown_category') (REQ-CMAP-002)."""
        from services import cmdb_proposal_service as svc

        monkeypatch.setattr(svc, "_get_repo", lambda: _RepoStub())
        monkeypatch.setattr(svc, "_resolve_category", lambda cat: None)  # not in live catalog
        monkeypatch.setattr(svc, "_ci_id_exists", lambda ci_id: False)
        monkeypatch.setattr(svc, "_get_guard", lambda: _GuardStub(allowed=True))

        user = _user(permissions=[AIPermission.AI_PROPOSE_CI.value])
        manifest = {
            "schema_version": 1,
            "ci": {
                "id": "X",
                "label": "Y",
                "category": "FictionalDevice",
                "type": "FictionalDevice",
            },
        }

        with pytest.raises(HTTPException) as exc:
            svc.create_proposal(manifest=manifest, user=user, ai_agent_id="ai", db=object())
        assert exc.value.status_code == 422
        assert "unknown_category" in str(exc.value.detail)

    def test_create_ci_id_collision_409(self, monkeypatch):
        """A proposal whose ci.id already exists on :CI MUST raise 409 (REQ-CMAP-009)."""
        from services import cmdb_proposal_service as svc

        monkeypatch.setattr(svc, "_get_repo", lambda: _RepoStub())
        monkeypatch.setattr(svc, "_resolve_category", lambda cat: ["Router"])
        monkeypatch.setattr(svc, "_ci_id_exists", lambda ci_id: True)  # collision!
        monkeypatch.setattr(svc, "_get_guard", lambda: _GuardStub(allowed=True))

        user = _user(permissions=[AIPermission.AI_PROPOSE_CI.value])
        manifest = {
            "schema_version": 1,
            "ci": {"id": "CI-EXISTING", "label": "Y", "category": "Router", "type": "Router"},
        }

        with pytest.raises(HTTPException) as exc:
            svc.create_proposal(manifest=manifest, user=user, ai_agent_id="ai", db=object())
        assert exc.value.status_code == 409
        assert "ci_id_collision" in str(exc.value.detail)

    def test_create_permission_denied_403(self, monkeypatch):
        """A caller without AI_PROPOSE_CI and not ADMIN MUST raise 403 (REQ-CMAP-004)."""
        from services import cmdb_proposal_service as svc

        monkeypatch.setattr(svc, "_get_repo", lambda: _RepoStub())
        monkeypatch.setattr(svc, "_resolve_category", lambda cat: ["Router"])
        monkeypatch.setattr(svc, "_ci_id_exists", lambda ci_id: False)
        monkeypatch.setattr(svc, "_get_guard", lambda: _GuardStub(allowed=True))

        user = _user(role="VIEWER", permissions=[])
        manifest = {
            "schema_version": 1,
            "ci": {"id": "X", "label": "Y", "category": "Router", "type": "Router"},
        }

        with pytest.raises(HTTPException) as exc:
            svc.create_proposal(manifest=manifest, user=user, ai_agent_id="ai", db=object())
        assert exc.value.status_code == 403
        assert "AI_PROPOSE_CI" in str(exc.value.detail)

    def test_create_guardrail_denial_returns_harness_denied(self, monkeypatch):
        """Guardrail denial MUST return 200-equivalent harness_result.denied=true (REQ-CMAP-011)."""
        from services import cmdb_proposal_service as svc

        repo = _RepoStub()
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)
        monkeypatch.setattr(svc, "_resolve_category", lambda cat: ["Router"])
        monkeypatch.setattr(svc, "_ci_id_exists", lambda ci_id: False)
        guard = _GuardStub(allowed=False, reason="Cooldown active", reason_code="cooldown_active")
        monkeypatch.setattr(svc, "_get_guard", lambda: guard)

        user = _user(permissions=[AIPermission.AI_PROPOSE_CI.value])
        manifest = {
            "schema_version": 1,
            "ci": {"id": "X", "label": "Y", "category": "Router", "type": "Router"},
        }

        result = svc.create_proposal(manifest=manifest, user=user, ai_agent_id="ai", db=object())
        assert result["harness_result"]["denied"] is True
        assert result["harness_result"]["status"] == "denied"
        assert result["harness_result"]["reason_code"] == "cooldown_active"
        # No proposal was created.
        assert repo.created_kwargs is None


class TestApproveProposal:
    def test_approve_calls_node_service_and_links_resulted_in(self, monkeypatch, audit_calls):
        """Approve MUST call node_service.create_update_node with the manifest's CI (REQ-CMAP-006)."""
        from services import cmdb_proposal_service as svc

        repo = _RepoStub(
            approve_returns={
                "id": "prop-1",
                "status": "APPROVED",
                "version": 2,
                "manifest_json": "{}",
                "applied_manifest_json": '{"ci":{"id":"CI-NEW"}}',
                "proposed_by": "ai-bot",
                "proposed_role": "AI_OPERATOR",
                "reviewed_by": "alice",
                "reviewed_at": "2026-09-13T00:00:00Z",
                "created_at": "2026-09-13T00:00:00Z",
                "updated_at": "2026-09-13T00:00:00Z",
                "resulted_ci_id": "CI-NEW",
                "revoke_reason": None,
                "proposed_category": "Router",
                "ci_id": "CI-NEW",
            }
        )
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        # Stub node_service.create_update_node to capture invocation
        node_calls = []

        def _fake_create_update_node(node, user):
            node_calls.append({"id": node.id, "label": node.label})
            return {"message": "Node created/updated", "id": node.id}

        fake_node_service = MagicMock()
        fake_node_service.create_update_node = _fake_create_update_node
        monkeypatch.setattr(svc, "node_service", fake_node_service, raising=False)

        monkeypatch.setattr(svc, "_resolve_category", lambda cat: ["Router"])
        monkeypatch.setattr(
            svc, "_ci_id_exists", lambda ci_id: False
        )  # collision-free at approve time

        user = _user(role="OPERATOR", permissions=[UserPermission.CI_APPROVE_PROPOSAL.value])
        result = svc.approve_proposal(
            proposal_id="prop-1",
            expected_version=1,
            user=user,
            db=object(),
        )
        assert result["status"] == "APPROVED"
        assert result["resulted_ci_id"] == "CI-NEW"
        assert len(node_calls) == 1
        assert node_calls[0]["id"] == "CI-NEW"

    def test_approve_from_non_draft_409(self, monkeypatch):
        """Approve of an APPROVED/REVOKED proposal MUST raise 409 (REQ-CMAP-006 scenario 2)."""
        from repositories.cmdb_proposal_repo import CmdbProposalVersionConflictError
        from services import cmdb_proposal_service as svc

        repo = _RepoStub(
            approve_raises=CmdbProposalVersionConflictError("stale"),
            get_returns={
                "id": "prop-1",
                "status": "APPROVED",  # not DRAFT
                "version": 2,
                "manifest_json": json.dumps(
                    {
                        "schema_version": 1,
                        "ci": {
                            "id": "CI-NEW",
                            "label": "Core Router",
                            "category": "Router",
                            "type": "Router",
                        },
                    }
                ),
                "applied_manifest_json": None,
                "proposed_by": "ai-bot",
                "proposed_role": "AI_OPERATOR",
                "reviewed_by": None,
                "reviewed_at": None,
                "created_at": "2026-09-13T00:00:00Z",
                "updated_at": "2026-09-13T00:00:00Z",
                "resulted_ci_id": None,
                "revoke_reason": None,
                "proposed_category": "Router",
                "ci_id": "CI-NEW",
            },
        )
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)
        monkeypatch.setattr(svc, "_resolve_category", lambda cat: ["Router"])
        monkeypatch.setattr(svc, "_ci_id_exists", lambda ci_id: False)

        user = _user(role="OPERATOR", permissions=[UserPermission.CI_APPROVE_PROPOSAL.value])
        with pytest.raises(HTTPException) as exc:
            svc.approve_proposal(proposal_id="prop-1", expected_version=99, user=user, db=object())
        assert exc.value.status_code == 409
        assert "invalid_state" in str(exc.value.detail)

    def test_approve_permission_denied_403(self, monkeypatch):
        """Approve without CI_APPROVE_PROPOSAL MUST raise 403."""
        from services import cmdb_proposal_service as svc

        repo = _RepoStub()
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)
        monkeypatch.setattr(svc, "_resolve_category", lambda cat: ["Router"])
        monkeypatch.setattr(svc, "_ci_id_exists", lambda ci_id: False)

        user = _user(role="VIEWER", permissions=[])
        with pytest.raises(HTTPException) as exc:
            svc.approve_proposal(proposal_id="prop-1", expected_version=1, user=user, db=object())
        assert exc.value.status_code == 403

    def test_approve_409_when_category_renamed(self, monkeypatch):
        """Approve MUST 409 if the category is no longer in the live catalog (REQ-CMAP-002 scenario 2)."""
        from services import cmdb_proposal_service as svc

        monkeypatch.setattr(svc, "_get_repo", lambda: _RepoStub())
        monkeypatch.setattr(svc, "_resolve_category", lambda cat: None)  # renamed
        monkeypatch.setattr(svc, "_ci_id_exists", lambda ci_id: False)

        user = _user(role="OPERATOR", permissions=[UserPermission.CI_APPROVE_PROPOSAL.value])
        with pytest.raises(HTTPException) as exc:
            svc.approve_proposal(proposal_id="prop-1", expected_version=1, user=user, db=object())
        assert exc.value.status_code == 409
        assert "category_renamed" in str(exc.value.detail)

    def test_approve_409_when_ci_id_collision_at_approve_time(self, monkeypatch):
        """Approve MUST 409 if the ci.id collides at approve time (race)."""
        from services import cmdb_proposal_service as svc

        monkeypatch.setattr(svc, "_get_repo", lambda: _RepoStub())
        monkeypatch.setattr(svc, "_resolve_category", lambda cat: ["Router"])
        monkeypatch.setattr(svc, "_ci_id_exists", lambda ci_id: True)  # race collision

        user = _user(role="OPERATOR", permissions=[UserPermission.CI_APPROVE_PROPOSAL.value])
        with pytest.raises(HTTPException) as exc:
            svc.approve_proposal(proposal_id="prop-1", expected_version=1, user=user, db=object())
        assert exc.value.status_code == 409
        assert "ci_id_collision" in str(exc.value.detail)


class TestRevokeProposal:
    def test_revoke_from_draft_no_ci_created(self, monkeypatch, audit_calls):
        """Revoke from DRAFT MUST NOT create a :CI (REQ-CMAP-007 scenario 1)."""
        from services import cmdb_proposal_service as svc

        fake_node_service = MagicMock()
        fake_node_service.create_update_node = MagicMock()
        monkeypatch.setattr(svc, "node_service", fake_node_service, raising=False)

        repo = _RepoStub(
            revoke_returns={
                "id": "prop-1",
                "status": "REVOKED",
                "version": 2,
                "manifest_json": "{}",
                "applied_manifest_json": None,
                "proposed_by": "ai-bot",
                "proposed_role": "AI_OPERATOR",
                "reviewed_by": "alice",
                "reviewed_at": "2026-09-13T00:00:00Z",
                "created_at": "2026-09-13T00:00:00Z",
                "updated_at": "2026-09-13T00:00:00Z",
                "resulted_ci_id": None,
                "revoke_reason": "stale",
                "proposed_category": "Router",
                "ci_id": "CI-NEW",
            }
        )
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        user = _user(role="OPERATOR", permissions=[UserPermission.CI_APPROVE_PROPOSAL.value])
        result = svc.revoke_proposal(
            proposal_id="prop-1", expected_version=1, user=user, reason="stale", db=object()
        )
        assert result["status"] == "REVOKED"
        # node_service was NOT called.
        fake_node_service.create_update_node.assert_not_called()

    def test_revoke_from_approved_keeps_ci(self, monkeypatch, audit_calls):
        """Revoke from APPROVED MUST keep the :CI (REQ-CMAP-007 scenario 2)."""
        from services import cmdb_proposal_service as svc

        fake_node_service = MagicMock()
        fake_node_service.create_update_node = MagicMock()
        monkeypatch.setattr(svc, "node_service", fake_node_service, raising=False)

        repo = _RepoStub(
            revoke_returns={
                "id": "prop-1",
                "status": "REVOKED",
                "version": 3,
                "manifest_json": "{}",
                "applied_manifest_json": '{"ci":{"id":"CI-NEW"}}',
                "proposed_by": "ai-bot",
                "proposed_role": "AI_OPERATOR",
                "reviewed_by": "alice",
                "reviewed_at": "2026-09-13T00:00:00Z",
                "created_at": "2026-09-13T00:00:00Z",
                "updated_at": "2026-09-13T00:00:00Z",
                "resulted_ci_id": "CI-NEW",
                "revoke_reason": "audit_revoke",
                "proposed_category": "Router",
                "ci_id": "CI-NEW",
            }
        )
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        user = _user(role="OPERATOR", permissions=[UserPermission.CI_APPROVE_PROPOSAL.value])
        result = svc.revoke_proposal(
            proposal_id="prop-1", expected_version=2, user=user, reason="audit_revoke", db=object()
        )
        assert result["status"] == "REVOKED"
        # The :CI is preserved — node_service.create_update_node is NOT called on revoke.
        fake_node_service.create_update_node.assert_not_called()
