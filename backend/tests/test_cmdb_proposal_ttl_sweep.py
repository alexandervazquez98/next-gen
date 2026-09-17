"""Unit tests for the TTL sweep script — feat-cmdb-ai-handoff (T-1.6).

REQ-CMAP-016 / REQ-AUDIT-001 scenario 3:
- ttl_sweep invoked once with the resolved retention_days
- one CI_PROPOSAL_REVOKE audit row emitted per swept proposal with
  actor_role=SYSTEM and revoke_reason=ttl_expired
- idempotent: zero audit rows when ttl_sweep returns 0
- CLI flag overrides default; env var honored when flag absent

Stub-based (no live DB).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


def _swept_row(proposal_id: str = "prop-1", proposed_by: str = "ai-bot") -> dict:
    return {
        "id": proposal_id,
        "status": "REVOKED",
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
                "rationale": "Spoke router",
            }
        ),
        "applied_manifest_json": None,
        "proposed_by": proposed_by,
        "proposed_role": "AI_OPERATOR",
        "reviewed_by": "SYSTEM",
        "reviewed_at": "2026-09-13T00:00:00Z",
        "created_at": "2026-09-12T00:00:00Z",
        "updated_at": "2026-09-13T00:00:00Z",
        "resulted_ci_id": None,
        "revoke_reason": "ttl_expired",
        "proposed_category": "Router",
        "ci_id": "CI-NEW",
    }


@pytest.fixture
def audit_calls(monkeypatch):
    """Capture record_critical_change calls into a list."""
    from services import audit_service

    calls: list[dict] = []

    def _record(**kwargs):
        calls.append(kwargs)
        return None

    def _denied(**kwargs):
        raise AssertionError("record_denied hardcodes ACCESS_DENIED; use record_critical_change")

    monkeypatch.setattr(audit_service, "record_critical_change", _record)
    monkeypatch.setattr(audit_service, "record_denied", _denied)
    return calls


@pytest.fixture
def repo_stub():
    stub = MagicMock()
    stub.ttl_sweep = MagicMock(return_value=0)
    stub.list = MagicMock(return_value=[])
    return stub


@pytest.fixture
def fake_session():
    return MagicMock()


class TestTtlSweepScript:
    def test_sweep_revokes_31_day_old_drafts_and_emits_audit(
        self, monkeypatch, audit_calls, repo_stub, fake_session
    ):
        """Sweep MUST call ttl_sweep(30) and emit one audit row per swept node."""
        repo_stub.ttl_sweep.return_value = 2
        repo_stub.list.return_value = [_swept_row("prop-1"), _swept_row("prop-2")]

        from scripts import cmdb_proposal_ttl_sweep as script

        monkeypatch.setattr(script, "_get_repo", lambda: repo_stub)
        monkeypatch.setattr(script, "SessionLocal", lambda: fake_session)

        exit_code = script.main(argv=[])

        repo_stub.ttl_sweep.assert_called_once_with(30)
        assert exit_code == 0
        assert len(audit_calls) == 2
        for call in audit_calls:
            assert call["event_type"] == "CI_PROPOSAL_REVOKE"
            assert call["outcome"] == "SUCCESS"
            assert call["target_type"] == "ci_proposal"
            assert call["source"] == "cmdb_proposals"
            assert call["context"]["actor_role"] == "SYSTEM"
            assert call["context"]["revoke_reason"] == "ttl_expired"
            assert call["context"]["next_state"] == "REVOKED"
            assert call["context"]["previous_state"] == "DRAFT"

    def test_sweep_is_idempotent_when_zero_nodes_revoked(
        self, monkeypatch, audit_calls, repo_stub, fake_session
    ):
        """When ttl_sweep returns 0, NO audit rows MUST be emitted."""
        repo_stub.ttl_sweep.return_value = 0

        from scripts import cmdb_proposal_ttl_sweep as script

        monkeypatch.setattr(script, "_get_repo", lambda: repo_stub)
        monkeypatch.setattr(script, "SessionLocal", lambda: fake_session)

        script.main(argv=[])

        repo_stub.ttl_sweep.assert_called_once_with(30)
        assert audit_calls == []

    def test_sweep_accepts_retention_days_cli_arg(
        self, monkeypatch, audit_calls, repo_stub, fake_session
    ):
        """--retention-days CLI flag MUST override the default."""
        repo_stub.ttl_sweep.return_value = 0

        from scripts import cmdb_proposal_ttl_sweep as script

        monkeypatch.setattr(script, "_get_repo", lambda: repo_stub)
        monkeypatch.setattr(script, "SessionLocal", lambda: fake_session)

        script.main(argv=["--retention-days", "7"])

        repo_stub.ttl_sweep.assert_called_once_with(7)

    def test_sweep_honors_environment_variable(
        self, monkeypatch, audit_calls, repo_stub, fake_session
    ):
        """CMDB_PROPOSAL_RETENTION_DAYS env var MUST be honored when CLI flag is absent."""
        repo_stub.ttl_sweep.return_value = 0

        from scripts import cmdb_proposal_ttl_sweep as script

        monkeypatch.setattr(script, "_get_repo", lambda: repo_stub)
        monkeypatch.setattr(script, "SessionLocal", lambda: fake_session)
        monkeypatch.setenv("CMDB_PROPOSAL_RETENTION_DAYS", "14")

        script.main(argv=[])

        repo_stub.ttl_sweep.assert_called_once_with(14)

    def test_sweep_redacts_secrets_in_audit_context(
        self, monkeypatch, audit_calls, repo_stub, fake_session
    ):
        """Audit context's applied_manifest_summary MUST redact secret-shaped values."""
        repo_stub.ttl_sweep.return_value = 1
        row = _swept_row("prop-1")
        row["manifest_json"] = json.dumps(
            {
                "schema_version": 1,
                "ci": {
                    "id": "CI-NEW",
                    "label": "Core Router",
                    "category": "Router",
                    "type": "Router",
                    "snmp": {"version": "v2c", "community": "public-ro-xyz"},
                },
                "rationale": "Spoke router",
            }
        )
        repo_stub.list.return_value = [row]

        from scripts import cmdb_proposal_ttl_sweep as script

        monkeypatch.setattr(script, "_get_repo", lambda: repo_stub)
        monkeypatch.setattr(script, "SessionLocal", lambda: fake_session)

        script.main(argv=[])

        assert len(audit_calls) == 1
        summary = audit_calls[0]["context"]["applied_manifest_summary"]
        assert summary["ci"]["snmp"]["community"] == "<REDACTED>"
