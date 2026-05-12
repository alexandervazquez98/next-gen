"""Router-level tests for event endpoints — AI agent guard integration.

Focus areas:
- POST /api/events/{event_id}/ack — AI agent guard, record_operation
- POST /api/events/{event_id}/close — AI agent guard, CRITICAL escalation
- POST /api/events/{event_id}/diagnose — AI agent guard, record_operation

Strategy:
- Use FastAPI TestClient with the global app import
- Patch Neo4j driver at module import time
- Override get_current_active_user to inject AI agent or regular user
- Mock ai_guard_service functions and event_service functions
"""

import pytest
import types
import sys
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Patch Neo4j driver BEFORE importing main
# ---------------------------------------------------------------------------
_mock_neo4j_driver = MagicMock()

# Stub out snmp_service before it gets imported
_snmp_service_stub = types.ModuleType("services.snmp_service")
setattr(_snmp_service_stub, "snmp_collector_loop", lambda: None)
setattr(
    _snmp_service_stub,
    "get_collector_status",
    lambda: {"last_run": None, "status": "STOPPED", "stats": {}},
)
setattr(_snmp_service_stub, "validate_snmp_oid", lambda *args, **kwargs: {"success": False})
setattr(_snmp_service_stub, "run_diagnostic", lambda *args, **kwargs: "diagnostic-ok")
sys.modules["services.snmp_service"] = _snmp_service_stub

with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
    from main import app
    from database import get_db

from models.user import User, UserPermission
from services.auth_service import get_current_active_user

# ---------------------------------------------------------------------------
# TestClient
# ---------------------------------------------------------------------------
client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ai_user(username: str = "ai-agent-1", role: str = "AI_DIAGNOSTIC") -> User:
    """Create a fake AI agent user."""
    return User(
        username=username,
        role=role,
        permissions=[],
        allowed_locations=[],
    )


def _operator_user(
    username: str = "operator",
    permissions: list[UserPermission] | None = None,
) -> User:
    """Create a regular operator user."""
    return User(
        username=username,
        role="OPERATOR",
        permissions=permissions or [UserPermission.EVENT_ACK, UserPermission.EVENT_CLOSE, UserPermission.RUN_DIAGNOSTICS],
        allowed_locations=[],
    )


# ---------------------------------------------------------------------------
# Tests: POST /api/events/{event_id}/ack
# ---------------------------------------------------------------------------


class TestAckEvent:
    """Tests for POST /api/events/{event_id}/ack endpoint with AI agent guards."""

    def test_ack_unauthenticated(self):
        """No auth token should return 401."""
        response = client.post("/api/events/evt-001/ack")
        assert response.status_code == 401

    def test_ack_no_permission(self):
        """User without EVENT_ACK should get 403."""
        async def override():
            return User(
                username="viewer",
                role="VIEWER",
                permissions=[],
                allowed_locations=[],
            )

        app.dependency_overrides[get_current_active_user] = override

        response = client.post("/api/events/evt-001/ack", json={})

        assert response.status_code == 403

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_ack_passes_guard_check(self):
        """AI agent can acknowledge when check_all_guards returns allowed=True."""
        async def override():
            return _ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.check_all_guards") as mock_guards, \
             patch("routers.events.record_operation") as mock_record, \
             patch("routers.events.event_service") as mock_service:
            mock_guards.return_value = MagicMock(allowed=True)
            mock_service.ack_event.return_value = {"message": "Event acknowledged"}

            response = client.post("/api/events/evt-001/ack", json={})

            assert response.status_code == 200
            mock_guards.assert_called_once_with("ai-agent-1", "ack", ["evt-001"])
            mock_record.assert_called_once()

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_ack_blocked_by_guard(self):
        """AI agent gets 403 when check_all_guards returns allowed=False (cooldown active)."""
        async def override():
            return _ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.check_all_guards") as mock_guards:
            mock_guards.return_value = MagicMock(
                allowed=False,
                reason="Cooldown active",
                cooldown_remaining_seconds=300,
            )

            response = client.post("/api/events/evt-001/ack", json={})

            assert response.status_code == 403
            assert "Cooldown active" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_ack_records_operation_on_success(self):
        """When ack succeeds, record_operation is called with result='success'."""
        async def override():
            return _ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.check_all_guards") as mock_guards, \
             patch("routers.events.record_operation") as mock_record, \
             patch("routers.events.event_service") as mock_service:
            mock_guards.return_value = MagicMock(allowed=True)
            mock_service.ack_event.return_value = {"message": "Event acknowledged"}

            response = client.post("/api/events/evt-001/ack", json={"comment_message": "Test ack"})

            assert response.status_code == 200
            # record_operation should have been called with result='success'
            call_kwargs = mock_record.call_args
            assert call_kwargs[1]["result"] == "success"
            assert call_kwargs[1]["operation"] == "ack"

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: POST /api/events/{event_id}/close
# ---------------------------------------------------------------------------


class TestCloseEvent:
    """Tests for POST /api/events/{event_id}/close endpoint with AI agent guards."""

    def test_close_unauthenticated(self):
        """No auth token should return 401."""
        response = client.post("/api/events/evt-001/close", json={})
        assert response.status_code == 401

    def test_close_no_permission(self):
        """User without EVENT_CLOSE should get 403."""
        async def override():
            return User(
                username="viewer",
                role="VIEWER",
                permissions=[],
                allowed_locations=[],
            )

        app.dependency_overrides[get_current_active_user] = override

        response = client.post("/api/events/evt-001/close", json={})

        assert response.status_code == 403

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_cannot_force_close(self):
        """AI agent with forced=True should get 403 — AI cannot force-close."""
        async def override():
            return _ai_user()

        app.dependency_overrides[get_current_active_user] = override

        response = client.post(
            "/api/events/evt-001/close",
            json={"forced": True, "comment_message": "closing"},
        )

        assert response.status_code == 403
        assert "AI agents cannot force-close" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_close_passes_guard_check(self):
        """AI agent can close when check_all_guards returns allowed=True (non-CRITICAL event)."""
        async def override():
            return _ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.check_all_guards") as mock_guards, \
             patch("routers.events.record_operation") as mock_record, \
             patch("routers.events.event_service") as mock_service, \
             patch("routers.events.set_cooldown") as mock_set_cooldown:
            mock_guards.return_value = MagicMock(allowed=True)
            mock_service.get_event_detail.return_value = {
                "event": {"severity": "WARNING", "message": "Test", "ci": {"id": "ci-001", "label": "Router-01"}},
            }
            mock_service.close_event.return_value = {"message": "Event closed"}

            response = client.post("/api/events/evt-001/close", json={})

            assert response.status_code == 200
            mock_guards.assert_called_once_with("ai-agent-1", "close", ["evt-001"])

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_close_blocked_by_guard(self):
        """AI agent gets 403 when check_all_guards returns allowed=False."""
        async def override():
            return _ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.check_all_guards") as mock_guards:
            mock_guards.return_value = MagicMock(
                allowed=False,
                reason="Close without diagnostic: >3 closes/hour without any diagnostic",
            )

            response = client.post("/api/events/evt-001/close", json={})

            assert response.status_code == 403
            assert "Close without diagnostic" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_critical_event_close_triggers_escalation(self):
        """Closing a CRITICAL event must trigger escalation notification for all users."""
        async def override():
            return _operator_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.notify_critical_event_escalation") as mock_notify, \
             patch("routers.events.record_operation") as mock_record, \
             patch("routers.events.event_service") as mock_service, \
             patch("routers.events.set_cooldown") as mock_set_cooldown:
            mock_service.get_event_detail.return_value = {
                "event": {
                    "severity": "CRITICAL",
                    "message": "CPU overload",
                    "ci": {"id": "ci-001", "label": "Router-01"},
                },
            }
            mock_service.close_event.return_value = {"message": "Event closed"}

            response = client.post("/api/events/evt-001/close", json={})

            assert response.status_code == 200
            # notify_critical_event_escalation must have been called
            mock_notify.assert_called_once()
            call_kwargs = mock_notify.call_args[1]
            assert call_kwargs["severity"] == "CRITICAL" or "event_message" in call_kwargs

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_close_critical_event_records_escalated(self):
        """AI agent closing CRITICAL event should record result='escalated'."""
        async def override():
            return _ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.check_all_guards") as mock_guards, \
             patch("routers.events.notify_critical_event_escalation") as mock_notify, \
             patch("routers.events.record_operation") as mock_record, \
             patch("routers.events.event_service") as mock_service, \
             patch("routers.events.set_cooldown") as mock_set_cooldown:
            mock_guards.return_value = MagicMock(allowed=True)
            mock_service.get_event_detail.return_value = {
                "event": {
                    "severity": "CRITICAL",
                    "message": "CPU overload",
                    "ci": {"id": "ci-001", "label": "Router-01"},
                },
            }
            mock_service.close_event.return_value = {"message": "Event closed"}

            response = client.post("/api/events/evt-001/close", json={})

            assert response.status_code == 200
            # record_operation should be called twice: once for escalation, once for success
            # Find the escalated call
            escalated_calls = [
                c for c in mock_record.call_args_list
                if c[1].get("result") == "escalated"
            ]
            assert len(escalated_calls) >= 1

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: POST /api/events/{event_id}/diagnose
# ---------------------------------------------------------------------------


class TestDiagnoseEvent:
    """Tests for POST /api/events/{event_id}/diagnose endpoint with AI agent guards."""

    def test_diagnose_unauthenticated(self):
        """No auth token should return 401."""
        response = client.post("/api/events/evt-001/diagnose")
        assert response.status_code == 401

    def test_diagnose_no_permission(self):
        """User without RUN_DIAGNOSTICS should get 403."""
        async def override():
            return User(
                username="viewer",
                role="VIEWER",
                permissions=[],
                allowed_locations=[],
            )

        app.dependency_overrides[get_current_active_user] = override

        response = client.post("/api/events/evt-001/diagnose")

        assert response.status_code == 403

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_diagnose_passes_guard_check(self):
        """AI agent can run diagnostic when check_all_guards returns allowed=True."""
        async def override():
            return _ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.check_all_guards") as mock_guards, \
             patch("routers.events.record_operation") as mock_record, \
             patch("routers.events.event_service") as mock_service:
            mock_guards.return_value = MagicMock(allowed=True)
            mock_service.get_event_detail.return_value = {
                "event": {"severity": "WARNING", "message": "Test", "ci": {"id": "ci-001", "label": "Router-01"}},
            }
            mock_service.run_event_diagnostic.return_value = {"message": "Diagnostic complete"}

            response = client.post("/api/events/evt-001/diagnose")

            assert response.status_code == 200
            mock_guards.assert_called_once_with("ai-agent-1", "diagnose", ["evt-001"])
            mock_record.assert_called_once()

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_diagnose_blocked_by_guard(self):
        """AI agent gets 403 when check_all_guards returns allowed=False."""
        async def override():
            return _ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.check_all_guards") as mock_guards:
            mock_guards.return_value = MagicMock(
                allowed=False,
                reason="Cooldown active",
                cooldown_remaining_seconds=180,
            )

            response = client.post("/api/events/evt-001/diagnose")

            assert response.status_code == 403
            assert "Cooldown active" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_diagnose_records_operation_on_success(self):
        """When diagnose succeeds, record_operation is called with operation='diagnose'."""
        async def override():
            return _ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.check_all_guards") as mock_guards, \
             patch("routers.events.record_operation") as mock_record, \
             patch("routers.events.event_service") as mock_service:
            mock_guards.return_value = MagicMock(allowed=True)
            mock_service.get_event_detail.return_value = {
                "event": {"severity": "WARNING", "ci": {"label": "Router-01"}},
            }
            mock_service.run_event_diagnostic.return_value = {"message": "Diagnostic complete"}

            response = client.post("/api/events/evt-001/diagnose")

            assert response.status_code == 200
            # record_operation should have been called with operation='diagnose'
            call_kwargs = mock_record.call_args
            assert call_kwargs[1]["operation"] == "diagnose"
            assert call_kwargs[1]["result"] == "success"

        app.dependency_overrides.pop(get_current_active_user, None)
