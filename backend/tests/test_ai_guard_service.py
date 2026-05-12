"""Unit tests for ai_guard_service — cooldown tracking, behavioral guards, bulk detection.

Tests use mocked DB (SessionLocal) and in-memory cooldown cache.
Behavioral guard queries are intercepted at the sqlalchemy text() level.
"""

import pytest
import time
from unittest.mock import patch, MagicMock
from models.ai_guard_models import GuardResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_session():
    """Create a mock DB session that intercepts ai_operation_log queries."""
    session = MagicMock()
    return session


def _mock_execute_result(rows):
    """Build a mock execute() that returns a scalar or result set.

    Args:
        rows: If int, scalar() returns that int directly.
              If list, scalar() returns None (for multi-row) and scalar_one_or_none returns rows[0] or None.
    """
    mock_result = MagicMock()
    if isinstance(rows, int):
        mock_result.scalar.return_value = rows
        mock_result.scalar_one_or_none.return_value = rows
    else:
        mock_result.scalar.return_value = None
        mock_result.scalar_one_or_none.return_value = rows[0] if rows else None
    return mock_result


# ---------------------------------------------------------------------------
# Cooldown cache — isolated tests (no DB)
# ---------------------------------------------------------------------------

class TestCooldownCache:
    """Tests for cooldown cache set/get/TTL behavior."""

    def test_set_and_get_remaining_active(self):
        """After set_cooldown, get_remaining returns remaining > 0."""
        from services.ai_guard_service import _cooldown_cache

        # Use a unique key to avoid collision
        agent = f"test-agent-{time.time_ns()}"
        op = "diagnose"
        target = f"target-{time.time_ns()}"

        _cooldown_cache.set(agent, op, target, ttl_seconds=300)

        remaining = _cooldown_cache.get_remaining(agent, op, target)
        assert remaining > 0
        assert remaining <= 300

    def test_get_remaining_no_entry_returns_zero(self):
        """get_remaining returns 0 when no cooldown entry exists."""
        from services.ai_guard_service import _cooldown_cache

        remaining = _cooldown_cache.get_remaining(
            "nonexistent-agent", "ack", "nonexistent-target"
        )
        assert remaining == 0

    def test_check_cooldown_no_cooldown(self):
        """check_cooldown returns (False, 0) when no cooldown is active."""
        from services.ai_guard_service import check_cooldown

        # Use a unique agent/target to avoid collisions
        agent = f"agent-nocd-{time.time_ns()}"
        target = f"target-nocd-{time.time_ns()}"

        is_blocked, remaining = check_cooldown(agent, "diagnose", target)
        assert is_blocked is False
        assert remaining == 0

    def test_check_cooldown_active(self):
        """check_cooldown returns (True, cooldown_remaining) when cooldown is active."""
        from services.ai_guard_service import check_cooldown, _cooldown_cache

        agent = f"agent-cd-{time.time_ns()}"
        target = f"target-cd-{time.time_ns()}"
        _cooldown_cache.set(agent, "ack", target, ttl_seconds=600)

        is_blocked, remaining = check_cooldown(agent, "ack", target)
        assert is_blocked is True
        assert remaining > 0
        assert remaining <= 600

    def test_check_cooldown_ttl_expiration(self):
        """Cooldown entries expire after their TTL using mocked time."""
        from services.ai_guard_service import _CooldownCache

        cache = _CooldownCache()
        agent = f"agent-exp-{time.time_ns()}"
        target = f"target-exp-{time.time_ns()}"

        # Patch time.monotonic to control the clock
        original_monotonic = time.monotonic
        try:
            # Set entry at t=100
            time.monotonic = lambda: 100.0
            cache.set(agent, "diagnose", target, ttl_seconds=10)

            # At t=100, remaining should be ~10
            time.monotonic = lambda: 100.0
            remaining = cache.get_remaining(agent, "diagnose", target)
            assert remaining >= 9  # ~10 seconds remaining (within rounding)

            # Advance to t=111 (past TTL of 10 seconds)
            time.monotonic = lambda: 111.0
            remaining = cache.get_remaining(agent, "diagnose", target)
            assert remaining == 0  # TTL expired
        finally:
            time.monotonic = original_monotonic

    def test_check_cooldown_unknown_operation_uses_default_60s(self):
        """check_cooldown uses 60s default for unknown operations."""
        from services.ai_guard_service import check_cooldown, _cooldown_cache

        agent = f"agent-def-{time.time_ns()}"
        target = f"target-def-{time.time_ns()}"

        # Unknown operation has no entry — should return False/0
        is_blocked, remaining = check_cooldown(agent, "unknown_op", target)
        assert is_blocked is False
        assert remaining == 0

        # Now set cooldown for a known operation
        _cooldown_cache.set(agent, "diagnose", target, ttl_seconds=300)
        is_blocked, remaining = check_cooldown(agent, "diagnose", target)
        assert is_blocked is True

    def test_check_cooldown_empty_target_ids_handled(self):
        """check_all_guards handles empty target_ids list gracefully."""
        from services.ai_guard_service import check_all_guards

        mock_db = MagicMock()
        mock_db.execute.return_value = _mock_execute_result(0)
        mock_db.close = MagicMock()

        with patch("services.ai_guard_service.SessionLocal", return_value=mock_db):
            result = check_all_guards("some-agent", "diagnose", [])
        # Should not raise — empty list is handled with target_id=""
        assert isinstance(result, GuardResult)

    def test_different_target_ids_have_independent_cooldowns(self):
        """Cooldowns are per (agent, operation, target_id) — not global."""
        from services.ai_guard_service import check_cooldown, _cooldown_cache

        agent = f"agent-multi-{time.time_ns()}"
        target1 = f"target1-{time.time_ns()}"
        target2 = f"target2-{time.time_ns()}"

        _cooldown_cache.set(agent, "ack", target1, ttl_seconds=600)

        # target1 should be blocked
        is_blocked1, _ = check_cooldown(agent, "ack", target1)
        assert is_blocked1 is True

        # target2 should NOT be blocked
        is_blocked2, _ = check_cooldown(agent, "ack", target2)
        assert is_blocked2 is False


# ---------------------------------------------------------------------------
# Behavioral guards — mocked DB
# ---------------------------------------------------------------------------

class TestBehavioralGuards:
    """Tests for behavioral guard rules with mocked DB queries."""

    def _mock_db_with_result(self, scalar_result):
        """Create a mock DB session that returns a fixed scalar for execute()."""
        mock_db = MagicMock()
        mock_db.execute.return_value = _mock_execute_result(scalar_result)
        mock_db.close = MagicMock()
        return mock_db

    def test_close_without_diagnostic_guard_blocks_at_4_closes(self):
        """>3 closes without diagnostic in the same hour must be blocked."""
        from services.ai_guard_service import check_behavioral_guards

        # 4 closes (closes_count > 3) and no diagnostic → BLOCK
        mock_db = self._mock_db_with_result(4)  # closes_count
        # Second execute call is for the diagnostic check — returns None (no diagnostic)
        mock_db.execute.side_effect = [
            _mock_execute_result(4),   # closes_count
            _mock_execute_result(None),  # has_diagnostic
        ]

        with patch("services.ai_guard_service.SessionLocal", return_value=mock_db):
            result = check_behavioral_guards("agent-1", "close", "evt-001")

        assert result.allowed is False
        assert "Close without diagnostic" in result.reason

    def test_close_guard_allows_with_diagnostic_present(self):
        """Close is allowed if there is at least one diagnostic in the same period."""
        from services.ai_guard_service import check_behavioral_guards

        mock_db = self._mock_db_with_result(4)
        # has_diagnostic returns a row
        mock_db.execute.side_effect = [
            _mock_execute_result(4),    # closes_count
            _mock_execute_result([1]),  # has_diagnostic (row found)
        ]

        with patch("services.ai_guard_service.SessionLocal", return_value=mock_db):
            result = check_behavioral_guards("agent-1", "close", "evt-001")

        assert result.allowed is True

    def test_close_guard_allows_at_3_closes_or_less(self):
        """<=3 closes (exactly 3) must be allowed — only >3 is blocked."""
        from services.ai_guard_service import check_behavioral_guards

        mock_db = self._mock_db_with_result(3)
        mock_db.execute.side_effect = [
            _mock_execute_result(3),   # closes_count
            _mock_execute_result([1]),  # has_diagnostic
        ]

        with patch("services.ai_guard_service.SessionLocal", return_value=mock_db):
            result = check_behavioral_guards("agent-1", "close", "evt-001")

        assert result.allowed is True

    def test_ack_flood_guard_blocks_at_21_acks(self):
        """>20 acks/10min without diagnostic must be blocked."""
        from services.ai_guard_service import check_behavioral_guards

        mock_db = self._mock_db_with_result(21)
        mock_db.execute.side_effect = [
            _mock_execute_result(21),   # ack_count
            _mock_execute_result(None),  # has_diagnostic
        ]

        with patch("services.ai_guard_service.SessionLocal", return_value=mock_db):
            result = check_behavioral_guards("agent-1", "ack", "evt-001")

        assert result.allowed is False
        assert "Ack flood" in result.reason

    def test_ack_flood_guard_allows_with_diagnostic(self):
        """Ack is allowed if there is at least one diagnostic in the window."""
        from services.ai_guard_service import check_behavioral_guards

        mock_db = self._mock_db_with_result(21)
        mock_db.execute.side_effect = [
            _mock_execute_result(21),   # ack_count
            _mock_execute_result([1]),  # has_diagnostic
        ]

        with patch("services.ai_guard_service.SessionLocal", return_value=mock_db):
            result = check_behavioral_guards("agent-1", "ack", "evt-001")

        assert result.allowed is True

    def test_ack_flood_guard_allows_at_20_acks_or_less(self):
        """<=20 acks must be allowed — only >20 is blocked."""
        from services.ai_guard_service import check_behavioral_guards

        mock_db = self._mock_db_with_result(20)
        mock_db.execute.side_effect = [
            _mock_execute_result(20),   # ack_count
            _mock_execute_result([1]),  # has_diagnostic
        ]

        with patch("services.ai_guard_service.SessionLocal", return_value=mock_db):
            result = check_behavioral_guards("agent-1", "ack", "evt-001")

        assert result.allowed is True

    def test_metadata_stampede_guard_blocks_at_6_updates(self):
        """>5 CI metadata updates/5min must be blocked."""
        from services.ai_guard_service import check_behavioral_guards

        mock_db = self._mock_db_with_result(6)
        mock_db.execute.side_effect = [
            _mock_execute_result(6),   # update_count
        ]

        with patch("services.ai_guard_service.SessionLocal", return_value=mock_db):
            result = check_behavioral_guards("agent-1", "ci_metadata_update", "ci-001")

        assert result.allowed is False
        assert "Metadata stampede" in result.reason

    def test_metadata_stampede_guard_allows_at_5_or_fewer(self):
        """<=5 metadata updates in 5min must be allowed."""
        from services.ai_guard_service import check_behavioral_guards

        mock_db = self._mock_db_with_result(5)
        mock_db.execute.side_effect = [
            _mock_execute_result(5),
        ]

        with patch("services.ai_guard_service.SessionLocal", return_value=mock_db):
            result = check_behavioral_guards("agent-1", "ci_metadata_update", "ci-001")

        assert result.allowed is True

    # ── Critical escalation via check_bulk_detection ─────────────────────────

    def test_critical_escalation_triggered_at_50_same_ops(self):
        """same_op_count >= 50 flags CRITICAL escalation: allowed=True, escalation_required=True."""
        from services.ai_guard_service import check_bulk_detection

        mock_db = MagicMock()
        mock_db.execute.return_value = _mock_execute_result(50)
        mock_db.close = MagicMock()

        with patch("services.ai_guard_service.SessionLocal", return_value=mock_db):
            result = check_bulk_detection("agent-1", "diagnose", ["ci-001"])

        assert result.allowed is True
        assert result.escalation_required is True
        assert "High volume" in result.reason

    def test_critical_escalation_not_triggered_at_49_same_ops(self):
        """same_op_count = 49 does NOT trigger escalation: allowed=True, escalation_required=False."""
        from services.ai_guard_service import check_bulk_detection

        mock_db = MagicMock()
        # same_op_count=49 → below 50 threshold, no escalation
        # diff_ci_count also below 30
        mock_db.execute.side_effect = [
            _mock_execute_result(49),   # same_op_count
            _mock_execute_result(0),    # diff_ci_count
        ]
        mock_db.close = MagicMock()

        with patch("services.ai_guard_service.SessionLocal", return_value=mock_db):
            result = check_bulk_detection("agent-1", "diagnose", ["ci-001"])

        assert result.allowed is True
        assert result.escalation_required is False


# ---------------------------------------------------------------------------
# Bulk detection guards
# ---------------------------------------------------------------------------

class TestBulkDetection:
    """Tests for bulk operation detection."""

    def test_bulk_too_large_blocks_at_11_entities(self):
        """check_bulk_detection must block when >10 entities are requested."""
        from services.ai_guard_service import check_bulk_detection

        result = check_bulk_detection("agent-1", "ack", [f"entity-{i}" for i in range(11)])

        assert result.allowed is False
        assert "Bulk operation too large" in result.reason
        assert "11" in result.reason

    def test_bulk_allows_10_or_fewer_entities(self):
        """check_bulk_detection allows when <=10 entities."""
        from services.ai_guard_service import check_bulk_detection

        mock_db = MagicMock()
        mock_db.execute.return_value = _mock_execute_result(0)
        mock_db.close = MagicMock()

        with patch("services.ai_guard_service.SessionLocal", return_value=mock_db):
            result = check_bulk_detection("agent-1", "ack", [f"entity-{i}" for i in range(10)])
        assert result.allowed is True

    def test_bulk_flags_high_volume_same_op(self):
        """>=50 same operations/hour must set escalation_required=True."""
        from services.ai_guard_service import check_bulk_detection

        mock_db = MagicMock()
        # First call: same_op_count >= 50 → escalation
        mock_db.execute.return_value = _mock_execute_result(50)
        mock_db.close = MagicMock()

        with patch("services.ai_guard_service.SessionLocal", return_value=mock_db):
            result = check_bulk_detection("agent-1", "ack", ["entity-1"])

        assert result.allowed is True
        assert result.escalation_required is True
        assert "High volume" in result.reason

    def test_bulk_flags_high_ci_diversity(self):
        """>=30 different CIs/hour must set escalation_required=True."""
        from services.ai_guard_service import check_bulk_detection

        mock_db = MagicMock()
        # First call: same_op_count < 50, second: diff_ci_count >= 30
        mock_db.execute.side_effect = [
            _mock_execute_result(10),   # same_op_count below threshold
            _mock_execute_result(30),   # diff_ci_count at threshold
        ]
        mock_db.close = MagicMock()

        with patch("services.ai_guard_service.SessionLocal", return_value=mock_db):
            result = check_bulk_detection("agent-1", "ack", ["ci-001"])

        assert result.allowed is True
        assert result.escalation_required is True
        assert "High CI diversity" in result.reason


# ---------------------------------------------------------------------------
# check_all_guards integration
# ---------------------------------------------------------------------------

class TestCheckAllGuards:
    """Tests for the unified check_all_guards entry point."""

    def test_all_guards_pass(self):
        """When cooldown, behavioral, and bulk all pass, result is allowed."""
        from services.ai_guard_service import check_all_guards

        mock_db = MagicMock()
        mock_db.execute.return_value = _mock_execute_result(0)
        mock_db.close = MagicMock()

        with patch("services.ai_guard_service.SessionLocal", return_value=mock_db):
            result = check_all_guards("agent-1", "diagnose", ["evt-001"])

        assert result.allowed is True

    def test_empty_target_ids_uses_empty_string(self):
        """Empty target_ids list must not raise — handled with target_id=''."""
        from services.ai_guard_service import check_all_guards

        mock_db = MagicMock()
        mock_db.execute.return_value = _mock_execute_result(0)
        mock_db.close = MagicMock()

        with patch("services.ai_guard_service.SessionLocal", return_value=mock_db):
            # Must not raise KeyError or IndexError
            result = check_all_guards("agent-1", "diagnose", [])
            assert isinstance(result, GuardResult)
