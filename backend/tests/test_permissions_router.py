"""Router-level tests for the /api/permissions/ endpoint.

Tests verify:
- Authenticated users get a 200 response with human/ai keys
- Returned values match UserPermission and AIPermission enum values
- Unauthenticated requests get a 401
"""

import sys
import types
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub heavy infrastructure BEFORE importing main (conftest already stubs
# neo4j/psycopg2, but we need the snmp_service stub to avoid import errors)
# ---------------------------------------------------------------------------
_SNMP_SERVICE_SENTINEL = object()
_previous_snmp_service = sys.modules.get("services.snmp_service", _SNMP_SERVICE_SENTINEL)

if "services.snmp_service" not in sys.modules:
    _snmp_stub = types.ModuleType("services.snmp_service")
    setattr(_snmp_stub, "snmp_collector_loop", lambda: None)
    setattr(
        _snmp_stub,
        "get_collector_status",
        lambda: {"last_run": None, "status": "STOPPED", "stats": {}},
    )
    setattr(_snmp_stub, "validate_snmp_oid", lambda *args, **kwargs: {"success": False})
    setattr(_snmp_stub, "run_diagnostic", lambda *args, **kwargs: "diagnostic-ok")
    sys.modules["services.snmp_service"] = _snmp_stub

_mock_neo4j_driver = MagicMock()

with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
    from main import app

if _previous_snmp_service is _SNMP_SERVICE_SENTINEL:
    sys.modules.pop("services.snmp_service", None)
else:
    sys.modules["services.snmp_service"] = _previous_snmp_service

from fastapi.testclient import TestClient
from models.user import User, UserPermission, AIPermission
from services.auth_service import get_current_active_user

client = TestClient(app)


def _mock_user():
    return User(
        username="testuser",
        role="ADMIN",
        permissions=[],
        allowed_locations=[],
    )


def test_get_permissions_authenticated():
    app.dependency_overrides[get_current_active_user] = _mock_user
    resp = client.get("/api/permissions/")
    assert resp.status_code == 200
    body = resp.json()
    assert "human" in body
    assert "ai" in body
    app.dependency_overrides.pop(get_current_active_user, None)


def test_human_permissions_match_enum():
    app.dependency_overrides[get_current_active_user] = _mock_user
    resp = client.get("/api/permissions/")
    assert set(resp.json()["human"]) == {p.value for p in UserPermission}
    app.dependency_overrides.pop(get_current_active_user, None)


def test_ai_permissions_match_enum():
    app.dependency_overrides[get_current_active_user] = _mock_user
    resp = client.get("/api/permissions/")
    assert set(resp.json()["ai"]) == {p.value for p in AIPermission}
    app.dependency_overrides.pop(get_current_active_user, None)


def test_get_permissions_unauthenticated():
    app.dependency_overrides.clear()  # ensure no override leaks from prior tests
    resp = client.get("/api/permissions/")
    assert resp.status_code == 401
