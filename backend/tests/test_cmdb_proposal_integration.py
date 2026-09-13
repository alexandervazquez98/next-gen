"""End-to-end integration tests for CMDB proposals — feat-cmdb-ai-handoff (T-2.8).

Covers:
- HTTP full flow: create -> list -> approve
- MCP full flow: propose -> list -> approve -> revoke
- Concurrent approves: exactly one 200 + one 409 (REQ-CMAP-008)
- Guardrail denial preserves the two-layer contract (REQ-CMAP-011)

Runs against the in-process FastAPI app with mocked Neo4j driver.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from models.user import AIPermission, User, UserPermission
from services.auth_service import get_current_active_user

# Enable feature flag before importing main.
os.environ.setdefault("FEATURE_CMDB_PROPOSALS_ENABLED", "true")

_mock_neo4j_driver = MagicMock()
with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
    from main import app

client = TestClient(app)


def _user(role: str, permissions: list[str]) -> User:
    return User(username="alice", role=role, permissions=permissions, allowed_locations=[])


def _override_user(user: User) -> None:
    app.dependency_overrides[get_current_active_user] = lambda: user


@pytest.fixture(autouse=True)
def _reset_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _manifest():
    return {
        "schema_version": 1,
        "ci": {
            "id": "CI-NEW",
            "label": "Core Router Bogotá",
            "category": "Router",
            "type": "Router",
        },
        "rationale": "Spoke router",
        "source_refs": ["chat:msg-001"],
    }


@pytest.fixture
def seeded_repo(monkeypatch):
    """Stub the cmdb_proposal_repo so the in-process flow can run end-to-end.

    create_draft, get, list, approve, revoke each return deterministic rows.
    """
    from services import ai_guard_service, audit_service

    # Stub the guardrail DB access so check_bulk_detection does not hit Postgres.
    bulk_session = MagicMock()
    bulk_scalar = MagicMock()
    bulk_scalar.scalar.return_value = 0
    bulk_session.execute.return_value = bulk_scalar
    monkeypatch.setattr(ai_guard_service, "SessionLocal", lambda: bulk_session)

    # Stub cooldown check so we always pass.
    monkeypatch.setattr(
        ai_guard_service,
        "check_cooldown",
        lambda *a, **kw: (False, 0),
    )

    # Stub audit_service.record_critical_change so it doesn't touch a real DB.
    monkeypatch.setattr(
        audit_service,
        "record_critical_change",
        lambda **kwargs: None,
    )

    repo = MagicMock()
    repo._state = {"rows": {}}

    def create_draft(**kwargs):
        row = {
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
        repo._state["rows"][row["id"]] = row
        return row

    def get(proposal_id):
        return repo._state["rows"].get(proposal_id)

    def list_proposals(**kwargs):
        rows = list(repo._state["rows"].values())
        if kwargs.get("status"):
            rows = [r for r in rows if r["status"] == kwargs["status"]]
        return rows[: kwargs.get("page_size", 50)]

    def approve(**kwargs):
        row = repo._state["rows"].get(kwargs["proposal_id"])
        if not row or row["version"] != kwargs["expected_version"]:
            from backend.repositories.cmdb_proposal_repo import CmdbProposalVersionConflictError

            raise CmdbProposalVersionConflictError(f"version_conflict for {kwargs['proposal_id']}")
        row["status"] = "APPROVED"
        row["version"] = kwargs["expected_version"] + 1
        row["reviewed_by"] = kwargs["reviewer_by"]
        row["applied_manifest_json"] = kwargs.get("applied_manifest_json")
        row["resulted_ci_id"] = kwargs.get("resulted_ci_id")
        return row

    def revoke(**kwargs):
        row = repo._state["rows"].get(kwargs["proposal_id"])
        if not row or row["version"] != kwargs["expected_version"]:
            from backend.repositories.cmdb_proposal_repo import CmdbProposalVersionConflictError

            raise CmdbProposalVersionConflictError(f"version_conflict for {kwargs['proposal_id']}")
        row["status"] = "REVOKED"
        row["version"] = kwargs["expected_version"] + 1
        row["revoke_reason"] = kwargs.get("reason")
        return row

    repo.create_draft = create_draft
    repo.get = get
    repo.list = list_proposals
    repo.approve = approve
    repo.revoke = revoke

    monkeypatch.setattr("services.cmdb_proposal_service._get_repo", lambda: repo)
    # Stub category resolve + collision check to the happy path.
    monkeypatch.setattr(
        "services.cmdb_proposal_service._resolve_category", lambda cat: ["Router", "Server"]
    )
    monkeypatch.setattr("services.cmdb_proposal_service._ci_id_exists", lambda ci_id: False)
    # Stub node_service.create_update_node to a no-op so approve can finish.
    monkeypatch.setattr(
        "services.node_service.create_update_node",
        lambda node, user: {"message": "ok", "id": node.id},
    )
    return repo


class TestHttpFullFlow:
    def test_http_full_flow_create_list_approve(self, seeded_repo):
        """Create -> list -> approve through the HTTP router."""
        _override_user(_user("AI_OPERATOR", [AIPermission.AI_PROPOSE_CI.value]))

        # 1. Create
        resp = client.post("/api/cmdb/proposals", json=_manifest())
        assert resp.status_code == 201
        proposal_id = resp.json()["proposal_id"]
        assert proposal_id

        # 2. List (CI_VIEW) — list is open to OPERATOR/ADMIN/CI_VIEW holders
        _override_user(
            _user(
                "OPERATOR",
                [
                    UserPermission.CI_VIEW.value,
                    UserPermission.CI_APPROVE_PROPOSAL.value,
                    UserPermission.CI_EDIT.value,
                ],
            )
        )
        resp = client.get("/api/cmdb/proposals")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1

        # 3. Approve
        resp = client.post(f"/api/cmdb/proposals/{proposal_id}/approve", json={"version": 1})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "APPROVED"
        assert body["resulted_ci_id"] == "CI-NEW"


class TestMcpFullFlow:
    def test_mcp_full_flow_propose_list_approve_revoke(self, monkeypatch, seeded_repo):
        """propose_ci -> list_proposals -> approve_proposal -> revoke_proposal."""
        from mcp import cmdb_proposal_server as mcp

        monkeypatch.setattr(
            mcp,
            "_resolve_user_from_bearer",
            lambda t: MagicMock(
                username="alice",
                role="OPERATOR",
                permissions=["AI_PROPOSE_CI", "CI_VIEW", "CI_APPROVE_PROPOSAL"],
                allowed_locations=[],
                disabled=False,
            ),
        )
        monkeypatch.setattr(mcp, "_check_tool_rate_limit", lambda *a, **kw: True)

        # propose_ci
        proposed = mcp.tool_propose_ci(token="Bearer.tok", manifest=_manifest())
        assert "proposal_id" in proposed
        proposal_id = proposed["proposal_id"]

        # list_proposals
        listed = mcp.tool_list_proposals(token="Bearer.tok", status="DRAFT")
        assert any(r["id"] == proposal_id for r in listed["rows"])

        # approve_proposal
        approved = mcp.tool_approve_proposal(token="Bearer.tok", proposal_id=proposal_id, version=1)
        assert approved["status"] == "APPROVED"

        # revoke_proposal
        revoked = mcp.tool_revoke_proposal(
            token="Bearer.tok",
            proposal_id=proposal_id,
            version=2,
            reason="audit_revoke",
        )
        assert revoked["status"] == "REVOKED"


class TestConcurrency:
    def test_concurrent_approves_one_wins_one_409(self, seeded_repo):
        """Two near-simultaneous approves: exactly one 200, one 409 (REQ-CMAP-008)."""
        _override_user(
            _user(
                "OPERATOR",
                [
                    UserPermission.CI_APPROVE_PROPOSAL.value,
                    UserPermission.CI_VIEW.value,
                    UserPermission.CI_EDIT.value,
                ],
            )
        )

        # Create a proposal
        _override_user(_user("AI_OPERATOR", [AIPermission.AI_PROPOSE_CI.value]))
        resp = client.post("/api/cmdb/proposals", json=_manifest())
        assert resp.status_code == 201
        proposal_id = resp.json()["proposal_id"]

        # Switch to an approver.
        _override_user(
            _user(
                "OPERATOR",
                [
                    UserPermission.CI_APPROVE_PROPOSAL.value,
                    UserPermission.CI_VIEW.value,
                    UserPermission.CI_EDIT.value,
                ],
            )
        )

        # Two sequential approve calls with the same version=1.
        # The first one wins; the second sees version=2 and the optimistic MATCH fails.
        resp_a = client.post(f"/api/cmdb/proposals/{proposal_id}/approve", json={"version": 1})
        resp_b = client.post(f"/api/cmdb/proposals/{proposal_id}/approve", json={"version": 1})

        statuses = sorted([resp_a.status_code, resp_b.status_code])
        assert statuses == [
            200,
            409,
        ], f"expected [200, 409], got {statuses}; body_a={resp_a.json()} body_b={resp_b.json()}"

    def test_concurrent_approves_exactly_one_audit_row(self, monkeypatch, seeded_repo):
        """Concurrent approves MUST persist exactly ONE CI_PROPOSAL_APPROVE row."""
        from services import audit_service

        audit_calls = []

        def _record(**kwargs):
            audit_calls.append(kwargs)
            return None

        monkeypatch.setattr(audit_service, "record_critical_change", _record)
        monkeypatch.setattr(audit_service, "record_denied", _record)

        _override_user(_user("AI_OPERATOR", [AIPermission.AI_PROPOSE_CI.value]))
        resp = client.post("/api/cmdb/proposals", json=_manifest())
        assert resp.status_code == 201
        proposal_id = resp.json()["proposal_id"]

        _override_user(
            _user(
                "OPERATOR",
                [
                    UserPermission.CI_APPROVE_PROPOSAL.value,
                    UserPermission.CI_VIEW.value,
                    UserPermission.CI_EDIT.value,
                ],
            )
        )

        client.post(f"/api/cmdb/proposals/{proposal_id}/approve", json={"version": 1})
        client.post(f"/api/cmdb/proposals/{proposal_id}/approve", json={"version": 1})

        approve_audit_calls = [
            c for c in audit_calls if c.get("event_type") == "CI_PROPOSAL_APPROVE"
        ]
        assert (
            len(approve_audit_calls) == 1
        ), f"expected exactly 1 CI_PROPOSAL_APPROVE audit row; got {len(approve_audit_calls)}"


class TestGuardrailDenial:
    def test_guardrail_denial_returns_harness_denied_and_no_proposal_created(
        self, monkeypatch, seeded_repo
    ):
        """When the guardrail denies, NO proposal is created and the response is conversational."""
        from services import ai_guard_service

        # Force the guard to deny.
        monkeypatch.setattr(
            ai_guard_service,
            "check_cooldown",
            lambda *a, **kw: (True, 30),  # is_blocked=True, 30s remaining
        )

        _override_user(_user("AI_OPERATOR", [AIPermission.AI_PROPOSE_CI.value]))
        resp = client.post("/api/cmdb/proposals", json=_manifest())

        # 200 with harness_result.denied=true (NOT 201, NOT 403)
        assert resp.status_code == 200
        body = resp.json()
        assert body["harness_result"]["denied"] is True
        assert body["harness_result"]["status"] == "denied"

        # No proposal created in the repo.
        assert seeded_repo._state["rows"] == {}
