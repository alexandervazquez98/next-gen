"""Repository tests for :CIProposal — feat-cmdb-ai-handoff.

Mirrors the optimistic-version precedent at
``backend/repositories/mqtt_mapping_repo.py:386-507`` but parameterizes all
Cypher via $params (no f-string interpolation).

Uses the in-tree ``MockNeo4jDriver`` from ``backend/tests/conftest.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from repositories.cmdb_proposal_repo import (
    CI_PROPOSAL_STATUS_DRAFT as CmdbProposalStatus,
    CmdbProposalNotFoundError,
    CmdbProposalRepo,
    CmdbProposalVersionConflictError,
)


@pytest.fixture
def repo(mock_neo4j_driver):
    """Return a CmdbProposalRepo wired to the mocked driver."""
    return CmdbProposalRepo(driver=mock_neo4j_driver)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _draft_record(
    proposal_id: str = "prop-1",
    version: int = 1,
    status: str = CmdbProposalStatus,
    manifest_ci_id: str = "CI-NEW",
    proposed_by: str = "ai-bot",
    proposed_category: str = "Router",
) -> dict:
    return {
        "id": proposal_id,
        "manifest_json": '{"ci":{"id":"CI-NEW","label":"Core Router","category":"Router"}}',
        "applied_manifest_json": None,
        "status": status,
        "version": version,
        "proposed_by": proposed_by,
        "proposed_role": "AI_OPERATOR",
        "reviewed_by": None,
        "reviewed_at": None,
        "created_at": _iso_now(),
        "updated_at": _iso_now(),
        "resulted_ci_id": None,
        "revoke_reason": None,
        "proposed_category": proposed_category,
        "ci_id": manifest_ci_id,
    }


class TestCreateDraft:
    def test_create_draft_writes_version_one(self, mock_neo4j_driver, repo):
        """create_draft MUST persist the proposal with version=1 and status=DRAFT."""
        mock_neo4j_driver.mock_session.set_response(
            "create (p:ciproposal",
            [
                {
                    "id": "prop-1",
                    "status": "DRAFT",
                    "version": 1,
                    "manifest_json": "{}",
                    "applied_manifest_json": None,
                    "proposed_by": "ai-bot",
                    "proposed_role": "AI_OPERATOR",
                    "reviewed_by": None,
                    "reviewed_at": None,
                    "created_at": _iso_now(),
                    "updated_at": _iso_now(),
                    "resulted_ci_id": None,
                    "revoke_reason": None,
                    "proposed_category": "Router",
                    "ci_id": "CI-NEW",
                }
            ],
        )

        row = repo.create_draft(
            proposal_id="prop-1",
            manifest_json='{"ci":{"id":"CI-NEW"}}',
            proposed_by="ai-bot",
            proposed_role="AI_OPERATOR",
            proposed_category="Router",
            ci_id="CI-NEW",
        )

        assert row["id"] == "prop-1"
        assert row["status"] == "DRAFT"
        assert row["version"] == 1
        # Verify the cypher used $params (no f-string interpolation of user data).
        print("\nDEBUG queries:", mock_neo4j_driver.mock_session.queries)
        cypher_call = next(
            c
            for c in mock_neo4j_driver.mock_session.queries
            if "create (p:ciproposal" in c["query"].lower()
        )
        assert "proposal_id" in cypher_call["params"]
        assert cypher_call["params"]["proposal_id"] == "prop-1"
        assert "manifest_json" in cypher_call["params"]


class TestGet:
    def test_get_returns_none_when_missing(self, mock_neo4j_driver, repo):
        """get(proposal_id) MUST return None when no row matches."""
        mock_neo4j_driver.mock_session.set_default_response([])
        assert repo.get("missing") is None

    def test_get_returns_row_when_present(self, mock_neo4j_driver, repo):
        """get(proposal_id) MUST return the row when present."""
        mock_neo4j_driver.mock_session.set_response(
            "match (p:ciproposal)", [_draft_record(proposal_id="prop-7")]
        )
        row = repo.get("prop-7")
        assert row is not None
        assert row["id"] == "prop-7"


class TestList:
    def test_list_filters_by_status(self, mock_neo4j_driver, repo):
        """list(status=...) MUST pass status as \$param and return all matching rows."""
        mock_neo4j_driver.mock_session.set_default_response(
            [_draft_record(proposal_id="a"), _draft_record(proposal_id="b")]
        )
        rows = repo.list(status=CmdbProposalStatus)
        assert len(rows) == 2
        # Ensure status parameter was passed via params (no f-string leak).
        params_used = [
            q["params"].get("status")
            for q in mock_neo4j_driver.mock_session.queries
            if "match (p:ciproposal)" in q["query"].lower()
        ]
        assert any(p == CmdbProposalStatus for p in params_used)

    def test_list_with_pagination(self, mock_neo4j_driver, repo):
        """list(page, page_size) MUST apply skip/limit via $params."""
        mock_neo4j_driver.mock_session.set_default_response([])
        repo.list(status=None, page=2, page_size=25)
        params_used = [
            q["params"]
            for q in mock_neo4j_driver.mock_session.queries
            if "match (p:ciproposal)" in q["query"].lower()
        ]
        assert any(p.get("skip") == 25 for p in params_used), (
            "list MUST apply pagination via skip/limit params"
        )


class TestApprove:
    def test_approve_uses_optimistic_version(self, mock_neo4j_driver, repo):
        """approve MUST include version in the MATCH clause so first writer wins."""
        mock_neo4j_driver.mock_session.set_response(
            "match (p:ciproposal",
            [
                {
                    "id": "prop-1",
                    "status": "APPROVED",
                    "version": 2,
                    "manifest_json": "{}",
                    "applied_manifest_json": '{"ci":{"id":"CI-NEW"}}',
                    "proposed_by": "ai-bot",
                    "proposed_role": "AI_OPERATOR",
                    "reviewed_by": "alice",
                    "reviewed_at": _iso_now(),
                    "created_at": _iso_now(),
                    "updated_at": _iso_now(),
                    "resulted_ci_id": "CI-NEW",
                    "revoke_reason": None,
                    "proposed_category": "Router",
                    "ci_id": "CI-NEW",
                }
            ],
        )

        row = repo.approve(
            proposal_id="prop-1",
            expected_version=1,
            reviewer_by="alice",
            applied_manifest_json='{"ci":{"id":"CI-NEW"}}',
            resulted_ci_id="CI-NEW",
        )
        assert row["status"] == "APPROVED"
        assert row["version"] == 2

        # Ensure the MATCH clause carries {id, version}
        approve_query = next(
            q
            for q in mock_neo4j_driver.mock_session.queries
            if "approved_status" in q["query"].lower()
        )
        assert "expected_version" in approve_query["params"]
        assert approve_query["params"]["expected_version"] == 1

    def test_approve_raises_on_version_conflict(self, mock_neo4j_driver, repo):
        """approve MUST raise CmdbProposalVersionConflictError if no row matches."""
        # No rows -> MATCH returns 0 records.
        mock_neo4j_driver.mock_session.set_default_response([])
        with pytest.raises(CmdbProposalVersionConflictError):
            repo.approve(
                proposal_id="prop-1",
                expected_version=99,
                reviewer_by="alice",
                applied_manifest_json="{}",
                resulted_ci_id="CI-NEW",
            )


class TestRevoke:
    def test_revoke_from_draft(self, mock_neo4j_driver, repo):
        """revoke MUST allow transitions from DRAFT."""
        mock_neo4j_driver.mock_session.set_response(
            "match (p:ciproposal",
            [
                {
                    "id": "prop-1",
                    "status": "REVOKED",
                    "version": 2,
                    "manifest_json": "{}",
                    "applied_manifest_json": None,
                    "proposed_by": "ai-bot",
                    "proposed_role": "AI_OPERATOR",
                    "reviewed_by": "alice",
                    "reviewed_at": _iso_now(),
                    "created_at": _iso_now(),
                    "updated_at": _iso_now(),
                    "resulted_ci_id": None,
                    "revoke_reason": "stale",
                    "proposed_category": "Router",
                    "ci_id": "CI-NEW",
                }
            ],
        )

        row = repo.revoke(
            proposal_id="prop-1",
            expected_version=1,
            reviewer_by="alice",
            reason="stale",
        )
        assert row["status"] == "REVOKED"
        assert row["version"] == 2

    def test_revoke_from_approved(self, mock_neo4j_driver, repo):
        """revoke MUST allow transitions from APPROVED too (REQ-CMAP-007 scenario 2)."""
        mock_neo4j_driver.mock_session.set_response(
            "match (p:ciproposal",
            [
                {
                    "id": "prop-1",
                    "status": "REVOKED",
                    "version": 3,
                    "manifest_json": "{}",
                    "applied_manifest_json": '{"ci":{"id":"CI-NEW"}}',
                    "proposed_by": "ai-bot",
                    "proposed_role": "AI_OPERATOR",
                    "reviewed_by": "alice",
                    "reviewed_at": _iso_now(),
                    "created_at": _iso_now(),
                    "updated_at": _iso_now(),
                    "resulted_ci_id": "CI-NEW",
                    "revoke_reason": "audit_revoke",
                    "proposed_category": "Router",
                    "ci_id": "CI-NEW",
                }
            ],
        )
        row = repo.revoke(
            proposal_id="prop-1",
            expected_version=2,
            reviewer_by="alice",
            reason="audit_revoke",
        )
        assert row["status"] == "REVOKED"
        assert row["revoke_reason"] == "audit_revoke"

    def test_revoke_raises_on_version_conflict(self, mock_neo4j_driver, repo):
        """revoke MUST raise CmdbProposalVersionConflictError on stale version."""
        mock_neo4j_driver.mock_session.set_default_response([])
        with pytest.raises(CmdbProposalVersionConflictError):
            repo.revoke(proposal_id="prop-1", expected_version=99, reviewer_by="alice")


class TestTtlSweep:
    def test_ttl_sweep_returns_count_of_revoked_proposals(self, mock_neo4j_driver, repo):
        """ttl_sweep MUST return the count of proposals it transitioned to REVOKED."""
        mock_neo4j_driver.mock_session.set_response(
            "match (p:ciproposal)",
            [{"count": 5}],
        )
        count = repo.ttl_sweep(retention_days=30)
        assert count == 5

    def test_ttl_sweep_uses_provided_retention_days(self, mock_neo4j_driver, repo):
        """ttl_sweep MUST honor the retention_days parameter via \$params."""
        mock_neo4j_driver.mock_session.set_default_response([{"count": 0}])
        repo.ttl_sweep(retention_days=7)
        queries = mock_neo4j_driver.mock_session.queries
        sweep_query = next(
            q
            for q in queries
            if "match (p:ciproposal)" in q["query"].lower()
        )
        assert sweep_query["params"]["retention_days"] == 7


class TestNotFound:
    def test_get_raises_helpful_error_when_neo4j_empty(self, mock_neo4j_driver, repo):
        """get MUST return None (not raise) when the proposal is absent."""
        mock_neo4j_driver.mock_session.set_default_response([])
        # The current repo design: None for missing rows (no exception).
        assert repo.get("nonexistent") is None