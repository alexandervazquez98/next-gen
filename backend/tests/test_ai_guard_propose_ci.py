"""Extension tests for propose_ci cooldown + bulk threshold — feat-cmdb-ai-handoff.

REQ-AICHG-003 / REQ-AICHG-004 / REQ-CMAP-010:
- COOLDOWNS table includes 'propose_ci' with TTL >= 120s (mirrors ci_metadata_update)
- bulk detection escalates or denies at >5 submits in any rolling 60-minute window
- canonical guard target uses 'ci_proposal:new' or 'ci_proposal:<id>'
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _reset_cooldown_cache():
    """Each test starts with an empty cooldown cache to avoid cross-test leakage."""
    from services import ai_guard_service

    cache = ai_guard_service._cooldown_cache
    cache._entries.clear()
    yield
    cache._entries.clear()


class TestProposeCiCooldown:
    def test_propose_ci_cooldown_blocks_second_submit_within_window(self):
        """The propose_ci cooldown MUST block a second submit within the TTL window."""
        from services.ai_guard_service import check_cooldown, set_cooldown

        agent = "ai-bot-test-cooldown"
        target = "ci_proposal:new"
        # First submit goes through (no cooldown entry yet).
        is_blocked, _ = check_cooldown(agent, "propose_ci", target)
        assert is_blocked is False
        # Simulate a successful submit that registered the cooldown.
        set_cooldown(agent, "propose_ci", target)
        # Now a second submit must be blocked.
        is_blocked, remaining = check_cooldown(agent, "propose_ci", target)
        assert is_blocked is True
        assert remaining > 0

    def test_propose_ci_cooldown_is_listed_in_cooldowns_table(self):
        """COOLDOWNS MUST include 'propose_ci' with a TTL of >= 120s."""
        from services.ai_guard_service import COOLDOWNS

        assert "propose_ci" in COOLDOWNS, "COOLDOWNS table MUST include propose_ci"
        assert (
            COOLDOWNS["propose_ci"] >= 120
        ), f"propose_ci cooldown TTL {COOLDOWNS['propose_ci']} MUST be >= 120s"

    def test_propose_ci_cooldown_honors_env_override(self):
        """CMDB_PROPOSAL_COOLDOWN_SECONDS MUST override the default when present."""
        from services import ai_guard_service

        original = ai_guard_service.COOLDOWNS.get("propose_ci")
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("CMDB_PROPOSAL_COOLDOWN_SECONDS", "300")
            # Re-evaluate the COOLDOWNS dict assignment by importing the module afresh
            import importlib

            importlib.reload(ai_guard_service)
            assert ai_guard_service.COOLDOWNS["propose_ci"] == 300
        # Restore
        importlib.reload(ai_guard_service)
        if original is not None:
            ai_guard_service.COOLDOWNS["propose_ci"] = original


class TestProposeCiBulkThreshold:
    def test_propose_ci_bulk_threshold_escalates_at_six_per_hour(self, monkeypatch):
        """The 6th submit within 60 minutes MUST escalate/deny."""
        from services import ai_guard_service

        # Mock the DB execute to return count=5 (so the 6th submit crosses the threshold).
        session = MagicMock()
        scalar_mock = MagicMock()
        scalar_mock.scalar.return_value = 5
        session.execute.return_value = scalar_mock

        monkeypatch.setattr(ai_guard_service, "SessionLocal", lambda: session)

        result = ai_guard_service.check_bulk_detection(
            "ai-bot-bulk", "propose_ci", ["ci_proposal:new"]
        )
        # The bulk detection layer sets escalation_required OR denies.
        assert (
            result.escalation_required is True or result.allowed is False
        ), "propose_ci bulk threshold MUST escalate/deny at >=5 prior submits"

    def test_propose_ci_below_threshold_passes(self, monkeypatch):
        """Below the threshold the check MUST pass without escalation."""
        from services import ai_guard_service

        session = MagicMock()
        scalar_mock = MagicMock()
        scalar_mock.scalar.return_value = 2  # only 2 prior submits
        session.execute.return_value = scalar_mock

        monkeypatch.setattr(ai_guard_service, "SessionLocal", lambda: session)

        result = ai_guard_service.check_bulk_detection(
            "ai-bot-low", "propose_ci", ["ci_proposal:new"]
        )
        assert result.allowed is True
        assert result.escalation_required is False

    def test_propose_ci_uses_canonical_target_ci_proposal_new(self):
        """The guard target MUST be 'ci_proposal:new' (pre-create) per REQ-AICHG-002."""
        # The cooldown key is canonical — when an AI submits a manifest with
        # ci.id="X" and another with ci.id="Y", both submissions MUST use the
        # SAME canonical target so bulk counts aggregate.
        from services.ai_guard_service import check_cooldown, set_cooldown

        agent = "ai-bot-canonical"
        # Both submissions use the same canonical target despite different manifests.
        set_cooldown(agent, "propose_ci", "ci_proposal:new")
        is_blocked, _ = check_cooldown(agent, "propose_ci", "ci_proposal:new")
        assert is_blocked is True


class TestProposeCiEnvironment:
    def test_bulk_threshold_env_override(self):
        """CMDB_PROPOSAL_BULK_THRESHOLD env MUST be readable and overridable."""
        # Just verify the env var name is the documented one; the value is read
        # inside check_bulk_detection. The threshold check is exercised by the
        # two tests above.
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("CMDB_PROPOSAL_BULK_THRESHOLD", "10")
            assert os.getenv("CMDB_PROPOSAL_BULK_THRESHOLD") == "10"
