"""End-to-end router test for /api/cmdb/proposals/* — fix #487.

This test guards against the regression fixed by PR (closes #487):

    PR #483 introduced ``feat-cmdb-ai-handoff`` and registered
    ``/api/cmdb/proposals/*`` handlers that passed ``db=None`` to
    ``services.cmdb_proposal_service.{create,approve,revoke}_proposal``.
    Those service functions forward ``db`` into
    ``audit_service.record_critical_change`` ->
    ``_persist_event``, which calls ``db.rollback()`` on its except path.
    With ``db=None`` every successful create/approve/revoke returned
    ``500 Internal Server Error`` (``AttributeError: 'NoneType' object
    has no attribute 'rollback'``).

The existing ``test_cmdb_proposal_router.py`` and
``test_cmdb_proposal_integration.py`` suites stubbed the audit service at
the module level (or stubbed the whole service from the router), so the
``db=None`` contract violation was never triggered in CI.

This test DOES NOT stub ``audit_service``. It provides a real (mocked)
SQLAlchemy ``Session`` via ``get_pg_db`` and asserts that the router
threads it through to the audit layer without crashing.

What it covers:
- POST /api/cmdb/proposals returns 201 (not 500) with a real session.
- ``audit_service.record_critical_change`` is called with the injected
  ``db`` (the spy captures the kwarg, ensuring the router no longer
  passes ``None``).
- POST /api/cmdb/proposals/{id}/approve returns 200 with the same
  guarantee on the approve path.

Out of scope (covered elsewhere):
- Permission denial paths (test_cmdb_proposal_router.py)
- Feature flag 404 (test_cmdb_proposal_router.py::test_feature_flag_off)
- Manifest schema validation (test_cmdb_proposal_router.py)
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from models.user import AIPermission, User, UserPermission
from services.auth_service import get_current_active_user
from sqlalchemy.orm import Session

# Enable the feature flag BEFORE importing main (router is gated on it).
os.environ.setdefault("FEATURE_CMDB_PROPOSALS_ENABLED", "true")

_mock_neo4j_driver = MagicMock()
with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
    from main import app


@pytest.fixture
def ai_user() -> User:
    return User(
        username="ai-e2e-bot",
        role="AI_DIAGNOSTIC",
        permissions=[AIPermission.AI_PROPOSE_CI.value],
        allowed_locations=[],
    )


@pytest.fixture
def operator_user() -> User:
    return User(
        username="ops-e2e",
        role="OPERATOR",
        permissions=[
            UserPermission.CI_VIEW.value,
            UserPermission.CI_APPROVE_PROPOSAL.value,
        ],
        allowed_locations=[],
    )


@pytest.fixture
def pg_session_spy():
    """Provide a SQLAlchemy-session-shaped MagicMock as the pg db.

    The mock exposes every attribute that ``audit_service._persist_event``
    and the cmdb_proposal service touch on the session, so the real
    audit code path runs against a real(-ish) session and the
    ``db.rollback()`` regression cannot resurface.
    """
    session = MagicMock(spec=Session)
    # Mirror the three methods the audit service actually calls.
    session.add = MagicMock()
    session.commit = MagicMock()
    session.refresh = MagicMock()
    session.rollback = MagicMock()
    return session


@pytest.fixture
def override_pg_db(pg_session_spy):
    """Override the FastAPI ``get_pg_db`` dependency with our spy."""
    from postgres_db import get_pg_db

    def _fake_pg_db() -> Session:
        return pg_session_spy

    app.dependency_overrides[get_pg_db] = _fake_pg_db
    yield
    app.dependency_overrides.pop(get_pg_db, None)


@pytest.fixture
def override_current_user():
    """Reset the auth dependency override between tests."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def stub_repo_and_guards(monkeypatch):
    """Stub the Neo4j-touching pieces (cmdb_proposal_repo, ai_guard, node_service).

    These never run on the real graph in unit tests. The audit service
    is intentionally NOT stubbed — that's the whole point of this test.
    """
    from repositories import cmdb_proposal_repo
    from services import ai_guard_service, cmdb_proposal_service, node_service

    # ai_guard_service.SessionLocal — guardrail DB access.
    bulk_session = MagicMock()
    bulk_scalar = MagicMock()
    bulk_scalar.scalar.return_value = 0
    bulk_session.execute.return_value = bulk_scalar
    monkeypatch.setattr(ai_guard_service, "SessionLocal", lambda: bulk_session)
    monkeypatch.setattr(ai_guard_service, "check_cooldown", lambda *a, **kw: (False, 0))

    # cmdb_proposal_repo — in-memory draft store keyed by proposal_id.
    repo = MagicMock()
    state: dict[str, dict] = {}

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
            "created_at": "2026-09-18T00:00:00Z",
            "updated_at": "2026-09-18T00:00:00Z",
            "resulted_ci_id": None,
            "revoke_reason": None,
            "proposed_category": kwargs.get("proposed_category"),
            "ci_id": kwargs.get("ci_id"),
        }
        state[row["id"]] = row
        return row

    def get(proposal_id):
        return state.get(proposal_id)

    def list_proposals(**kwargs):
        rows = list(state.values())
        if kwargs.get("status"):
            rows = [r for r in rows if r["status"] == kwargs["status"]]
        return {"rows": rows[: kwargs.get("page_size", 50)], "total": len(rows)}

    def approve(**kwargs):
        row = state.get(kwargs["proposal_id"])
        if not row or row["version"] != kwargs["expected_version"]:
            raise cmdb_proposal_repo.CmdbProposalVersionConflictError(
                f"version_conflict for {kwargs['proposal_id']}"
            )
        row["status"] = "APPROVED"
        row["version"] = kwargs["expected_version"] + 1
        row["reviewed_by"] = kwargs["reviewer_by"]
        row["applied_manifest_json"] = kwargs.get("applied_manifest_json")
        row["resulted_ci_id"] = kwargs.get("resulted_ci_id")
        return row

    def revoke(**kwargs):
        row = state.get(kwargs["proposal_id"])
        if not row or row["version"] != kwargs["expected_version"]:
            raise cmdb_proposal_repo.CmdbProposalVersionConflictError(
                f"version_conflict for {kwargs['proposal_id']}"
            )
        row["status"] = "REVOKED"
        row["version"] = kwargs["expected_version"] + 1
        row["revoke_reason"] = kwargs.get("reason")
        return row

    repo.create_draft = create_draft
    repo.get = get
    repo.list = list_proposals
    repo.approve = approve
    repo.revoke = revoke
    monkeypatch.setattr(cmdb_proposal_service, "_get_repo", lambda: repo)

    # Category resolve + ci_id collision check (happy path).
    monkeypatch.setattr(
        cmdb_proposal_service, "_resolve_category", lambda cat: ["Router", "Server"]
    )
    monkeypatch.setattr(cmdb_proposal_service, "_ci_id_exists", lambda ci_id: False)
    # node_service.create_update_node — approve writes a :CI in Neo4j.
    monkeypatch.setattr(
        node_service,
        "create_update_node",
        lambda *a, **kw: {"id": kwargs_default(kw, "id"), "label": kwargs_default(kw, "label")},
    )

    return {"state": state}


def kwargs_default(kwargs: dict, key: str) -> str | None:
    return kwargs.get(key)


def _manifest() -> dict:
    return {
        "schema_version": 1,
        "ci": {
            "id": "CI-E2E-001",
            "label": "E2E Test Router",
            "category": "Router",
            "type": "Router",
            "ip": "10.10.10.1",
        },
        "rationale": "fix #487 e2e regression",
        "source_refs": ["chat:e2e"],
    }


client = TestClient(app)


def test_create_proposal_injects_pg_db(
    ai_user, override_pg_db, override_current_user, pg_session_spy, stub_repo_and_guards
):
    """POST /api/cmdb/proposals must inject a real pg session, not None.

    Regression guard for #487: with the old code the handler passed
    ``db=None`` and the audit layer crashed with AttributeError on
    ``db.rollback()``. With the fix, ``get_pg_db`` is wired and the
    handler receives the spy session. We assert the call returned 201
    AND that ``audit_service.record_critical_change`` was invoked with
    the same session (proving it is not None and was threaded through).
    """
    app.dependency_overrides[get_current_active_user] = lambda: ai_user

    with patch(
        "services.audit_service.record_critical_change",
        wraps=lambda **kw: None,
    ) as audit_spy:
        response = client.post("/api/cmdb/proposals", json=_manifest())

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "DRAFT"
    assert body["version"] == 1
    assert "proposal_id" in body

    # The audit row must have been written, and ``db`` passed to it MUST
    # be the session the router injected (i.e., not None and equal to the spy).
    assert audit_spy.call_count == 1, audit_spy.call_args_list
    forwarded_db = audit_spy.call_args.kwargs["db"]
    assert forwarded_db is pg_session_spy, (
        f"audit_service.record_critical_change received db={forwarded_db!r}, "
        "expected the injected pg session. This is the #487 regression."
    )


def test_approve_proposal_injects_pg_db(
    ai_user,
    operator_user,
    override_pg_db,
    override_current_user,
    pg_session_spy,
    stub_repo_and_guards,
):
    """POST /api/cmdb/proposals/{id}/approve must inject a real pg session too.

    Same regression as #487, exercised on the approve path so a future
    refactor that re-introduces ``db=None`` on any of the three write
    handlers is caught.
    """
    # First create a draft as the AI agent.
    app.dependency_overrides[get_current_active_user] = lambda: ai_user
    create_resp = client.post("/api/cmdb/proposals", json=_manifest())
    assert create_resp.status_code == 201, create_resp.text
    proposal_id = create_resp.json()["proposal_id"]

    # Then approve as the operator. Audit must be called with the spy session.
    app.dependency_overrides[get_current_active_user] = lambda: operator_user
    with patch(
        "services.audit_service.record_critical_change",
        wraps=lambda **kw: None,
    ) as audit_spy:
        response = client.post(
            f"/api/cmdb/proposals/{proposal_id}/approve",
            json={"version": 1},
        )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "APPROVED"
    assert response.json()["version"] == 2

    forwarded_db = audit_spy.call_args.kwargs["db"]
    assert forwarded_db is pg_session_spy, (
        f"approve path: audit_service.record_critical_change received "
        f"db={forwarded_db!r}, expected the injected pg session."
    )
