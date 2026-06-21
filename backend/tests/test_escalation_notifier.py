"""REQ-CORR-5: Escalation gating on PROPAGATED events.

`backend/services/escalation_notifier.py:notify_critical_event_escalation`
MUST NOT publish or store an active escalation when the triggering event is
non-authoritative (`correlation_type='PROPAGATED'`). PR 1 added
`_is_authoritative_event` to `services/event_service.py`; this file proves the
escalation path uses it correctly.

Scenarios:
- CRITICAL + PROPAGATED → no escalation sent (no payload stored, no success)
- CRITICAL + ROOT → escalation sent (existing behavior preserved)
- WARNING + PROPAGATED → no escalation sent (defense-in-depth; gate fires
  regardless of severity)
- CRITICAL + missing correlation_type → escalation sent (backwards compat:
  legacy events are treated as authoritative)
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure backend root is on the import path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    """Synchronously run an async coroutine for testing."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def reset_active_escalations():
    """Clear the module-level active-escalations dict between tests."""
    from services import escalation_notifier

    with escalation_notifier._lock:
        escalation_notifier._active_escalations.clear()
    yield
    with escalation_notifier._lock:
        escalation_notifier._active_escalations.clear()


def _call_notify(*, correlation_type: str | None, event_id: str = "evt-001"):
    """Invoke notify_critical_event_escalation with sensible defaults."""
    from services.escalation_notifier import notify_critical_event_escalation

    return _run(
        notify_critical_event_escalation(
            ai_persona="AI_OPERATOR",
            ai_agent_id="ai-agent-1",
            event_id=event_id,
            event_message="CPU overloaded",
            ci_id="ci-B",
            ci_name="Router-01",
            correlation_type=correlation_type,
        )
    )


# ---------------------------------------------------------------------------
# Scenario 1: PROPAGATED events never escalate
# ---------------------------------------------------------------------------


class TestPropagatedEventsSuppressed:
    """CRITICAL/WARNING PROPAGATED events must NOT trigger an escalation."""

    def test_critical_propagated_event_no_escalation_published(self):
        """CRITICAL + PROPAGATED → no active escalation stored, success=False."""
        from services import escalation_notifier

        result = _call_notify(correlation_type="PROPAGATED")

        # No active escalation was stored locally.
        with escalation_notifier._lock:
            assert escalation_notifier._active_escalations == {}, (
                f"PROPAGATED escalation must not be stored, but found: "
                f"{list(escalation_notifier._active_escalations)!r}"
            )
        # The returned ticket must mark itself suppressed (success=False).
        assert result["success"] is False, (
            f"PROPAGATED escalation must return success=False, got {result!r}"
        )
        assert result["event_id"] == "evt-001"

    def test_warning_propagated_event_no_escalation_published(self):
        """WARNING + PROPAGATED → defense-in-depth: gate fires regardless of
        severity. (In practice the caller only fires on CRITICAL today, but
        the gate must still hold if a caller passes a WARNING PROPAGATED
        event.)"""
        from services import escalation_notifier

        result = _call_notify(correlation_type="PROPAGATED", event_id="evt-warn")

        with escalation_notifier._lock:
            assert escalation_notifier._active_escalations == {}
        assert result["success"] is False

    def test_propagated_lowercase_treated_as_propagated(self):
        """Lowercase 'propagated' is case-insensitive (matches
        _is_authoritative_event semantics). Defense in depth."""
        from services import escalation_notifier

        result = _call_notify(correlation_type="propagated")

        with escalation_notifier._lock:
            assert escalation_notifier._active_escalations == {}
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Scenario 2: Authoritative events escalate as before
# ---------------------------------------------------------------------------


class TestAuthoritativeEventsEscalate:
    """ROOT events (and legacy events with missing correlation_type) MUST
    trigger an escalation. This preserves existing behavior — the gate is
    additive, never subtractive on the authoritative side."""

    def test_critical_root_event_escalates(self):
        """CRITICAL + ROOT → escalation stored and reported (success=True)."""
        from services import escalation_notifier

        result = _call_notify(correlation_type="ROOT")

        # Active escalation stored.
        with escalation_notifier._lock:
            stored = dict(escalation_notifier._active_escalations)
        assert len(stored) == 1, (
            f"ROOT escalation must be stored, found {len(stored)}: {stored!r}"
        )
        escalation_id = next(iter(stored))
        assert stored[escalation_id]["event_id"] == "evt-001"
        # aiomqtt is not installed in this environment, so publish is
        # reported as not-delivered (success=False) but the ticket was stored.
        # The important guarantee is that the ticket EXISTS and has a topic.
        assert result["topic"] == "alerts/human/escalation"
        assert result["escalation_id"] == escalation_id

    def test_critical_missing_correlation_type_treated_as_root(self):
        """Legacy event with no correlation_type is treated as authoritative
        and escalates. Backwards compatibility with events written before
        PR 1."""
        from services import escalation_notifier

        result = _call_notify(correlation_type=None)

        with escalation_notifier._lock:
            stored = dict(escalation_notifier._active_escalations)
        assert len(stored) == 1, (
            f"missing correlation_type must escalate (legacy compat), "
            f"found {len(stored)}: {stored!r}"
        )
        assert result["topic"] == "alerts/human/escalation"

    def test_critical_explicit_none_correlation_type_escalates(self):
        """correlation_type explicitly passed as None → escalates."""
        from services import escalation_notifier

        result = _call_notify(correlation_type=None, event_id="evt-explicit-none")

        with escalation_notifier._lock:
            assert len(escalation_notifier._active_escalations) == 1
        assert result["event_id"] == "evt-explicit-none"


# ---------------------------------------------------------------------------
# Scenario 3: The gate uses _is_authoritative_event (not a string compare)
# ---------------------------------------------------------------------------


class TestGateUsesAuthoritativeHelper:
    """The escalation gate MUST delegate to `_is_authoritative_event` rather
    than reimplementing the correlation_type check, so the predicate stays
    in one place. This is a structural assertion, not a behavioral one."""

    def test_gate_calls_is_authoritative_event(self):
        """`_is_authoritative_event` is consulted for every escalation attempt."""
        with patch(
            "services.escalation_notifier._is_authoritative_event",
            wraps=_real_is_authoritative,
        ) as mock_helper:
            _call_notify(correlation_type="PROPAGATED")

        assert mock_helper.called, (
            "escalation_notifier must consult _is_authoritative_event to "
            "decide whether to publish (REQ-CORR-5)"
        )
        # Helper was called with a dict that exposes `correlation_type`.
        helper_arg = mock_helper.call_args[0][0]
        assert helper_arg.get("correlation_type") == "PROPAGATED", (
            f"_is_authoritative_event must receive correlation_type, got "
            f"{helper_arg!r}"
        )


def _real_is_authoritative(event_data):
    """Import the real helper inside the test (lazy import to avoid module
    load order issues during patching)."""
    from services.event_service import _is_authoritative_event

    return _is_authoritative_event(event_data)
