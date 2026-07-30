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

import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Patch Neo4j driver BEFORE importing main
# ---------------------------------------------------------------------------
_mock_neo4j_driver = MagicMock()

# Stub out snmp_service before it gets imported
_SNMP_SERVICE_SENTINEL = object()
_previous_snmp_service = sys.modules.get("services.snmp_service", _SNMP_SERVICE_SENTINEL)
_snmp_service_stub = types.ModuleType("services.snmp_service")
_snmp_service_stub.snmp_collector_loop = lambda: None
_snmp_service_stub.get_collector_status = lambda: {
    "last_run": None,
    "status": "STOPPED",
    "stats": {},
}
_snmp_service_stub.validate_snmp_oid = lambda *args, **kwargs: {"success": False}
_snmp_service_stub.run_diagnostic = lambda *args, **kwargs: "diagnostic-ok"
sys.modules["services.snmp_service"] = _snmp_service_stub

with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
    from main import app

if _previous_snmp_service is _SNMP_SERVICE_SENTINEL:
    sys.modules.pop("services.snmp_service", None)
else:
    sys.modules["services.snmp_service"] = _previous_snmp_service

from models.user import AIPermission, User, UserPermission  # noqa: E402
from services.auth_service import get_current_active_user  # noqa: E402

# ---------------------------------------------------------------------------
# TestClient
# ---------------------------------------------------------------------------
client = TestClient(app)


@pytest.fixture(autouse=True)
def restore_dependency_overrides_and_snmp_stub():
    yield
    app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ai_user(
    username: str = "ai-agent-1",
    role: str = "AI_DIAGNOSTIC",
    permissions: list[AIPermission | str] | None = None,
) -> User:
    """Create a fake AI agent user."""
    return User(
        username=username,
        role=role,
        permissions=(
            [
                AIPermission.AI_EVENT_ACK,
                AIPermission.AI_EVENT_CLOSE,
                AIPermission.AI_EVENT_COMMENT,
                AIPermission.AI_RUN_DIAGNOSTIC,
            ]
            if permissions is None
            else permissions
        ),
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
        permissions=permissions
        or [UserPermission.EVENT_ACK, UserPermission.EVENT_CLOSE, UserPermission.RUN_DIAGNOSTICS],
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

        with (
            patch("routers.events.check_all_guards") as mock_guards,
            patch("routers.events.record_operation") as mock_record,
            patch("routers.events.event_service") as mock_service,
        ):
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

    def test_ai_agent_ack_without_ai_event_ack_denied_before_guard(self):
        """AI agent without AI_EVENT_ACK must not reach ack guard logic."""

        async def override():
            return _ai_user(permissions=[AIPermission.AI_RUN_DIAGNOSTIC])

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.check_all_guards") as mock_guards:
            response = client.post("/api/events/evt-001/ack", json={})

            assert response.status_code == 403
            mock_guards.assert_not_called()

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_ack_records_operation_on_success(self):
        """When ack succeeds, record_operation is called with result='success'."""

        async def override():
            return _ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with (
            patch("routers.events.check_all_guards") as mock_guards,
            patch("routers.events.record_operation") as mock_record,
            patch("routers.events.event_service") as mock_service,
        ):
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
# Tests: POST /api/events/{event_id}/comment
# ---------------------------------------------------------------------------


class TestCommentEvent:
    """Tests for POST /api/events/{event_id}/comment endpoint permissions."""

    def test_human_event_ack_can_comment(self):
        async def override():
            return _operator_user(permissions=[UserPermission.EVENT_ACK])

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.event_service") as mock_service:
            mock_service.add_event_comment.return_value = {"message": "Comment added"}

            response = client.post(
                "/api/events/evt-001/comment",
                json={"message": "Checking this event"},
            )

            assert response.status_code == 200
            mock_service.add_event_comment.assert_called_once_with(
                "evt-001", "operator", "Checking this event"
            )

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_without_ai_event_comment_denied(self):
        async def override():
            return _ai_user(permissions=[AIPermission.AI_EVENT_ACK])

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.event_service") as mock_service:
            response = client.post(
                "/api/events/evt-001/comment",
                json={"message": "Checking this event"},
            )

            assert response.status_code == 403
            mock_service.add_event_comment.assert_not_called()

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_with_ai_event_comment_can_comment(self):
        async def override():
            return _ai_user(permissions=[AIPermission.AI_EVENT_COMMENT])

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.event_service") as mock_service:
            mock_service.add_event_comment.return_value = {"message": "Comment added"}

            response = client.post(
                "/api/events/evt-001/comment",
                json={"message": "AI note"},
            )

            assert response.status_code == 200
            mock_service.add_event_comment.assert_called_once_with(
                "evt-001", "ai-agent-1", "AI note"
            )

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

        with (
            patch("routers.events.check_all_guards") as mock_guards,
            patch("routers.events.record_operation"),
            patch("routers.events.event_service") as mock_service,
            patch("routers.events.set_cooldown"),
        ):
            mock_guards.return_value = MagicMock(allowed=True)
            mock_service.get_event_detail.return_value = {
                "event": {
                    "severity": "WARNING",
                    "message": "Test",
                    "ci": {"id": "ci-001", "label": "Router-01"},
                },
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

    def test_ai_agent_close_without_ai_event_close_denied_before_guard(self):
        """AI_DIAGNOSTIC with only AI_RUN_DIAGNOSTIC must not close events."""

        async def override():
            return _ai_user(permissions=[AIPermission.AI_RUN_DIAGNOSTIC])

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.check_all_guards") as mock_guards:
            response = client.post("/api/events/evt-001/close", json={})

            assert response.status_code == 403
            mock_guards.assert_not_called()

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_critical_event_close_triggers_escalation(self):
        """Closing a CRITICAL event must trigger escalation notification for all users."""

        async def override():
            return _operator_user()

        app.dependency_overrides[get_current_active_user] = override

        with (
            patch("routers.events.notify_critical_event_escalation") as mock_notify,
            patch("routers.events.record_operation"),
            patch("routers.events.event_service") as mock_service,
            patch("routers.events.set_cooldown"),
        ):
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
            assert "event_message" in call_kwargs

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_close_critical_event_records_escalated(self):
        """AI agent closing CRITICAL event should record result='escalated'."""

        async def override():
            return _ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with (
            patch("routers.events.check_all_guards") as mock_guards,
            patch("routers.events.notify_critical_event_escalation"),
            patch("routers.events.record_operation") as mock_record,
            patch("routers.events.event_service") as mock_service,
            patch("routers.events.set_cooldown"),
        ):
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
                c for c in mock_record.call_args_list if c[1].get("result") == "escalated"
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

        with (
            patch("routers.events.check_all_guards") as mock_guards,
            patch("routers.events.record_operation") as mock_record,
            patch("routers.events.event_service") as mock_service,
        ):
            mock_guards.return_value = MagicMock(allowed=True)
            mock_service.get_event_detail.return_value = {
                "event": {
                    "severity": "WARNING",
                    "message": "Test",
                    "ci": {"id": "ci-001", "label": "Router-01"},
                },
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

    def test_ai_agent_diagnose_without_ai_run_diagnostic_denied_before_guard(self):
        """AI agent without AI_RUN_DIAGNOSTIC must not reach diagnostic guards."""

        async def override():
            return _ai_user(permissions=[AIPermission.AI_EVENT_ACK])

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.check_all_guards") as mock_guards:
            response = client.post("/api/events/evt-001/diagnose")

            assert response.status_code == 403
            mock_guards.assert_not_called()

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ai_agent_diagnose_records_operation_on_success(self):
        """When diagnose succeeds, record_operation is called with operation='diagnose'."""

        async def override():
            return _ai_user()

        app.dependency_overrides[get_current_active_user] = override

        with (
            patch("routers.events.check_all_guards") as mock_guards,
            patch("routers.events.record_operation") as mock_record,
            patch("routers.events.event_service") as mock_service,
        ):
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


# ---------------------------------------------------------------------------
# Tests: GET /api/events?include_children
# ---------------------------------------------------------------------------


class TestGetEventsIncludeChildren:
    """REQ-003 / SCN-001..003: GET /api/events forwards the include_children
    boolean to event_service and threads the default."""

    def test_default_call_uses_root_only(self):
        """SCN-001: default GET forwards include_children=False."""
        with patch("routers.events.event_service") as mock_service:
            mock_service.get_events.return_value = []

            response = client.get("/api/events?status=CONSOLE")

            assert response.status_code == 200
            mock_service.get_events.assert_called_once_with(
                "CONSOLE", include_children=False
            )

    def test_explicit_true_forwards_include_children_true(self):
        """SCN-002: include_children=true flag is forwarded."""
        with patch("routers.events.event_service") as mock_service:
            mock_service.get_events.return_value = []

            response = client.get(
                "/api/events?status=CONSOLE&include_children=true"
            )

            assert response.status_code == 200
            mock_service.get_events.assert_called_once_with(
                "CONSOLE", include_children=True
            )

    def test_explicit_false_matches_default(self):
        """SCN-003: include_children=false is identical to default."""
        with patch("routers.events.event_service") as mock_service:
            mock_service.get_events.return_value = []

            response = client.get(
                "/api/events?status=CONSOLE&include_children=false"
            )

            assert response.status_code == 200
            mock_service.get_events.assert_called_once_with(
                "CONSOLE", include_children=False
            )


# ---------------------------------------------------------------------------
# Tests: GET /api/events/{event_id}/affected
# ---------------------------------------------------------------------------


class TestGetEventAffected:
    """REQ-004 / SCN-004 / SCN-005: drill-down endpoint."""

    def test_affected_returns_200_with_ordered_rows(self):
        async def override():
            return _operator_user(permissions=[UserPermission.EVENT_VIEW])

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.event_service") as mock_service:
            mock_service.get_affected_siblings.return_value = [
                {"ci_id": "ci-A", "ci_name": "Router-A", "status": "OK"},
                {"ci_id": "ci-B", "ci_name": "Router-B", "status": "OK"},
            ]

            response = client.get("/api/events/evt-1/affected")

            assert response.status_code == 200
            body = response.json()
            assert len(body) == 2
            assert body[0]["ci_id"] == "ci-A"
            mock_service.get_affected_siblings.assert_called_once_with("evt-1")

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_affected_unknown_event_returns_404(self):
        async def override():
            return _operator_user(permissions=[UserPermission.EVENT_VIEW])

        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.events.event_service") as mock_service:
            mock_service.get_affected_siblings.side_effect = HTTPException(
                status_code=404, detail="Event not found: missing-id"
            )

            response = client.get("/api/events/missing-id/affected")

            assert response.status_code == 404
            assert response.json()["detail"] == "Event not found: missing-id"

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_affected_missing_event_view_returns_403(self):
        async def override():
            return User(
                username="viewer",
                role="VIEWER",
                permissions=[],
                allowed_locations=[],
            )

        app.dependency_overrides[get_current_active_user] = override

        response = client.get("/api/events/evt-1/affected")

        assert response.status_code == 403
        assert response.json()["detail"] == "Not authorized to view events"

        app.dependency_overrides.pop(get_current_active_user, None)
