"""Router-level tests for metrics and events endpoints with mocked dependencies.

Focus areas:
- Metrics: list/usage/history remain public, while create/delete/promote require
  authentication plus CI_EDIT. Tests cover CRUD, usage, promotion, validation,
  and history with mocked Neo4j/Postgres.
- Events: list/related are public; comment/ack/close/prune/diagnose require
  authentication. Tests enforce this boundary.

Strategy:
- Use FastAPI TestClient with the global app import
- Patch Neo4j driver (database.driver) at module import time
- Override get_pg_db for PostgreSQL-dependent endpoints (metric history)
- Override get_current_active_user for auth-protected event endpoints
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Patch Neo4j driver BEFORE importing anything that touches database.py
# The driver is created at module import time and tries to connect immediately
# ---------------------------------------------------------------------------
_mock_neo4j_driver = MagicMock()
with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
    from main import app
    from database import get_db

from models.user import User, UserPermission
from postgres_db import get_pg_db
from services.auth_service import get_current_active_user

# ---------------------------------------------------------------------------
# TestClient
# ---------------------------------------------------------------------------
client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pydantic_user(
    username: str = "testuser",
    role: str = "OPERATOR",
    permissions: list[UserPermission] | None = None,
    disabled: bool = False,
) -> User:
    """Create a Pydantic User for injection via dependency override."""
    return User(
        username=username,
        role=role,
        permissions=permissions or [],
        allowed_locations=[],
        disabled=disabled,
    )


class _FakeNeo4jNode:
    """Mimics a Neo4j node so that dict(node) and node.get() work correctly."""

    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()

    def __iter__(self):
        return iter(self._data)

    def items(self):
        return self._data.items()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """Provide a mock SQLAlchemy session for PostgreSQL endpoints."""
    db = MagicMock(spec=Session)
    return db


@pytest.fixture
def mock_neo4j_driver():
    """Provide a mock Neo4j driver."""
    driver = MagicMock()
    driver.execute_query.return_value = ([], None, None)
    driver.session.return_value.__enter__ = MagicMock(return_value=MagicMock())
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    """Ensure dependency overrides never leak between tests."""
    original_overrides = app.dependency_overrides.copy()
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


# ===========================================================================
# METRICS ROUTER TESTS
# ===========================================================================
# NOTE: The metrics router mixes public read endpoints with protected write
# endpoints. These tests document the current behavior.
# ===========================================================================


class TestMetricsList:
    """Tests for GET /api/metrics — list all metric definitions."""

    def test_list_metrics_returns_empty(self, mock_neo4j_driver):
        """Should return empty list when no metrics exist."""
        mock_session = MagicMock()
        mock_session.run.return_value = []
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with patch("database.driver", mock_neo4j_driver):
            response = client.get("/api/metrics")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_metrics_returns_data(self, mock_neo4j_driver):
        """Should return metric definitions when they exist."""

        class FakeRecord:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

            def get(self, key, default=None):
                return self._data.get(key, default)

        class FakeResult:
            def __iter__(self):
                return iter(
                    [
                        FakeRecord(
                            {
                                "m": {
                                    "id": "cpu-load",
                                    "protocol": "SNMP",
                                    "warning": 80.0,
                                    "critical": 95.0,
                                    "oid": "1.3.6.1.2.1.25.3.3.1.2",
                                    "dataType": "INTEGER",
                                    "unit": "%",
                                    "description": "CPU Load",
                                    "criticality": 2,
                                    "applicable_to": '{"brands": ["cisco"]}',
                                }
                            }
                        )
                    ]
                )

        mock_session = MagicMock()
        mock_session.run.return_value = FakeResult()
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with patch("database.driver", mock_neo4j_driver):
            response = client.get("/api/metrics")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "cpu-load"
        assert data[0]["protocol"] == "SNMP"

    def test_list_metrics_no_auth_required(self):
        """Metrics list should NOT require authentication (documented gap)."""
        # No auth headers, no overrides — should still succeed (200, not 401)
        # Since Neo4j isn't mocked here, it will fail with 500, but NOT 401
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            with patch("database.driver", MagicMock()):
                response = client.get("/api/metrics")
        # 200 or 500 are acceptable — the key is it's NOT 401/403
        assert response.status_code != 401
        assert response.status_code != 403


class TestMetricsCreate:
    """Tests for POST /api/metrics — create/update metric definition."""

    def test_create_metric_success(self, mock_neo4j_driver):
        """Should create a metric definition."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.CI_EDIT],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        mock_session = MagicMock()
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with (
            patch("database.driver", mock_neo4j_driver),
            patch("routers.metrics.check_permission", return_value=True),
        ):
            response = client.post(
                "/api/metrics",
                json={
                    "id": "test-cpu",
                    "protocol": "SNMP",
                    "oid": "1.3.6.1.2.1.25.3.3.1.2",
                    "warning": 80.0,
                    "critical": 95.0,
                    "dataType": "INTEGER",
                    "unit": "%",
                    "description": "Test CPU metric",
                    "criticality": 2,
                    "applicable_to": {
                        "brands": ["cisco"],
                        "models": [],
                        "layers": [],
                        "names": [],
                        "excluded_names": [],
                    },
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "Metric defined" in data["message"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_create_metric_unauthenticated(self):
        """Create metric requires authentication."""
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            with patch("database.driver", MagicMock()):
                response = client.post(
                    "/api/metrics",
                    json={
                        "id": "no-auth-metric",
                        "protocol": "SNMP",
                    },
                )
        assert response.status_code == 401

    def test_create_metric_forbidden_without_permission(self):
        """Authenticated user without CI_EDIT should get 403."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_VIEW],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.post(
            "/api/metrics",
            json={
                "id": "forbidden-metric",
                "protocol": "SNMP",
            },
        )

        assert response.status_code == 403


class TestMetricsDelete:
    """Tests for DELETE /api/metrics/{metric_id} — delete metric definition."""

    def test_delete_metric_success(self, mock_neo4j_driver):
        """Should delete a metric definition."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.CI_EDIT],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        mock_session = MagicMock()
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with (
            patch("database.driver", mock_neo4j_driver),
            patch("routers.metrics.check_permission", return_value=True),
        ):
            response = client.delete("/api/metrics/test-cpu")

        assert response.status_code == 200
        data = response.json()
        assert "Metric deleted" in data["message"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_delete_metric_unauthenticated(self):
        """Delete metric requires authentication."""
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            with patch("database.driver", MagicMock()):
                response = client.delete("/api/metrics/any-metric")
        assert response.status_code == 401

    def test_delete_metric_forbidden_without_permission(self):
        """Authenticated user without CI_EDIT should get 403."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_VIEW],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.delete("/api/metrics/forbidden-metric")

        assert response.status_code == 403


class TestMetricsUsage:
    """Tests for GET /api/metrics/{metric_id}/usage — analyze CI matching."""

    def test_metric_usage_returns_data(self, mock_neo4j_driver):
        """Should return usage info with matching CIs."""

        # The service code does dict(record) on each result row.
        # We need objects that dict() can convert — a dict subclass works.
        class DictRecord(dict):
            """A dict that also supports record['key'] and record.get('key')."""

            def __getitem__(self, key):
                return super().__getitem__(key)

        call_count = [0]

        def mock_run(query, **params):
            call_count[0] += 1
            if call_count[0] == 1:
                # First query: fetch applicable_to
                return MagicMock(
                    single=MagicMock(
                        return_value=DictRecord(
                            {"apt": '{"brands": ["cisco"], "excluded_names": []}'}
                        )
                    )
                )
            # Second query: UNION results — must support dict(record)
            return [
                DictRecord(
                    {
                        "id": "ci-001",
                        "name": "Router-01",
                        "ip": "192.168.1.1",
                        "model": "ASR-1000",
                        "brand": "Cisco",
                    }
                )
            ]

        mock_session = MagicMock()
        mock_session.run.side_effect = mock_run
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with patch("database.driver", mock_neo4j_driver):
            response = client.get("/api/metrics/cpu-load/usage")

        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "criteria" in data


class TestMetricsPromote:
    """Tests for POST /api/metrics/promote — promote metric to graph node."""

    def test_promote_metric_success(self, mock_neo4j_driver):
        """Should promote a metric to a first-class graph node."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.CI_EDIT],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        mock_session = MagicMock()
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with (
            patch("database.driver", mock_neo4j_driver),
            patch("routers.metrics.check_permission", return_value=True),
        ):
            response = client.post(
                "/api/metrics/promote",
                json={
                    "ci_id": "ci-001",
                    "metric_name": "cpu-load",
                    "display_name": "CPU Load on Router-01",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "Metric promoted" in data["message"]
        assert "id" in data

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_promote_metric_forbidden_without_permission(self):
        """Authenticated user without CI_EDIT should get 403."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_VIEW],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.post(
            "/api/metrics/promote",
            json={
                "ci_id": "ci-001",
                "metric_name": "cpu-load",
                "display_name": "CPU Load on Router-01",
            },
        )

        assert response.status_code == 403


class TestMetricsValidate:
    """Tests for POST /api/metrics/validate — OID validation endpoint."""

    def test_validate_oid_snmp_not_available(self):
        """Should handle SNMP library not being available."""
        fake_user = _make_pydantic_user(username="operator", role="OPERATOR")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        with patch("routers.metrics.validate_snmp_oid") as mock_validate:
            mock_validate.return_value = {
                "success": False,
                "error": "SNMP not available",
            }

            response = client.post(
                "/api/metrics/validate",
                json={
                    "ip": "192.168.1.1",
                    "community": "public",
                    "oid": "1.3.6.1.2.1.1.1.0",
                },
            )

            assert response.status_code == 400
            data = response.json()
            assert data["success"] is False

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_validate_oid_success(self):
        """Should return success when OID is reachable."""
        fake_user = _make_pydantic_user(username="operator", role="OPERATOR")

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        # Patch at the router module level where the function is imported
        with patch("routers.metrics.validate_snmp_oid") as mock_validate:
            mock_validate.return_value = {
                "success": True,
                "value": "Cisco IOS Software",
                "response_time_ms": 12.5,
            }

            response = client.post(
                "/api/metrics/validate",
                json={
                    "ip": "192.168.1.1",
                    "community": "public",
                    "oid": "1.3.6.1.2.1.1.1.0",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

        app.dependency_overrides.pop(get_current_active_user, None)


class TestMetricsHistory:
    """Tests for GET /api/metrics/{node_id}/{metric_id}/history — PostgreSQL."""

    def test_history_requires_pg_db(self, mock_db):
        """History endpoint depends on PostgreSQL via get_pg_db."""

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        mock_db.execute.return_value.fetchall.return_value = []

        response = client.get("/api/metrics/ci-001/cpu-load/history")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        app.dependency_overrides.pop(get_pg_db, None)

    def test_history_with_hours_param(self, mock_db):
        """Should pass hours parameter to the repository."""

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        mock_db.execute.return_value.fetchall.return_value = []

        response = client.get("/api/metrics/ci-001/cpu-load/history?hours=48&limit=500")

        assert response.status_code == 200

        app.dependency_overrides.pop(get_pg_db, None)


# ===========================================================================
# EVENTS ROUTER TESTS
# ===========================================================================


class TestEventsList:
    """Tests for GET /api/events — list events (public endpoint)."""

    def test_list_events_no_filter(self, mock_neo4j_driver):
        """Should return events without any status filter."""

        class FakeEventNode:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

            def get(self, key, default=None):
                return self._data.get(key, default)

            def keys(self):
                return self._data.keys()

            def __iter__(self):
                return iter(self._data)

            def items(self):
                return self._data.items()

        class FakeRecord:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

            def get(self, key, default=None):
                return self._data.get(key, default)

        from datetime import datetime

        mock_session = MagicMock()
        mock_session.run.return_value = MagicMock(
            __iter__=MagicMock(
                return_value=iter(
                    [
                        FakeRecord(
                            {
                                "e": FakeEventNode(
                                    {
                                        "id": "evt-001",
                                        "status": "OPEN",
                                        "severity": "CRITICAL",
                                        "ci_id": "ci-001",
                                        "value": 97.5,
                                        "message": "CPU exceeded threshold",
                                        "created_at": datetime.utcnow(),
                                    }
                                ),
                                "ci_name": "Router-01",
                                "metric_name": "cpu-load",
                                "metric_protocol": "SNMP",
                            }
                        )
                    ]
                )
            )
        )
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with patch("database.driver", mock_neo4j_driver):
            response = client.get("/api/events")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["ci_name"] == "Router-01"

    def test_list_events_with_status_filter(self, mock_neo4j_driver):
        """Should pass status filter to the query."""
        mock_session = MagicMock()
        mock_session.run.return_value = MagicMock(
            __iter__=MagicMock(return_value=iter([]))
        )
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with patch("database.driver", mock_neo4j_driver):
            response = client.get("/api/events?status=OPEN")

        assert response.status_code == 200
        # Verify the status param was passed to the query
        call_args = mock_session.run.call_args
        assert call_args is not None
        assert call_args[1]["status"] == "OPEN"

    def test_list_events_active_filter(self, mock_neo4j_driver):
        """ACTIVE status should include OPEN, ACK, RECOVERED."""
        mock_session = MagicMock()
        mock_session.run.return_value = MagicMock(
            __iter__=MagicMock(return_value=iter([]))
        )
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with patch("database.driver", mock_neo4j_driver):
            response = client.get("/api/events?status=ACTIVE")

        assert response.status_code == 200
        call_args = mock_session.run.call_args
        assert call_args[1]["status"] == "ACTIVE"

    def test_list_events_no_auth_required(self):
        """Events list should NOT require authentication (by design)."""
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            with patch("database.driver", MagicMock()):
                response = client.get("/api/events")
        assert response.status_code != 401
        assert response.status_code != 403


class TestEventsRelated:
    """Tests for GET /api/events/related/{ci_id} — events for a CI."""

    def test_related_events_returns_data(self, mock_neo4j_driver):
        """Should return active events for a specific CI."""

        class FakeEventNode:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

            def get(self, key, default=None):
                return self._data.get(key, default)

            def keys(self):
                return self._data.keys()

            def __iter__(self):
                return iter(self._data)

        class FakeRecord:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

            def get(self, key, default=None):
                return self._data.get(key, default)

        mock_session = MagicMock()
        mock_session.run.return_value = MagicMock(
            __iter__=MagicMock(
                return_value=iter(
                    [
                        FakeRecord(
                            {
                                "e": FakeEventNode(
                                    {
                                        "id": "evt-001",
                                        "status": "OPEN",
                                        "severity": "CRITICAL",
                                        "ci_id": "ci-001",
                                    }
                                ),
                                "metric_name": "cpu-load",
                            }
                        )
                    ]
                )
            )
        )
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with patch("database.driver", mock_neo4j_driver):
            response = client.get("/api/events/related/ci-001")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["metric_name"] == "cpu-load"

    def test_related_events_no_auth_required(self):
        """Related events should NOT require auth (by design)."""
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            with patch("database.driver", MagicMock()):
                response = client.get("/api/events/related/ci-001")
        assert response.status_code != 401
        assert response.status_code != 403


class TestEventsAck:
    """Tests for POST /api/events/{event_id}/ack — acknowledge event (auth required)."""

    def test_ack_event_success(self, mock_neo4j_driver):
        """Authenticated user should be able to ack an event."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_ACK],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        mock_session = MagicMock()
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with patch("database.driver", mock_neo4j_driver):
            response = client.post("/api/events/evt-001/ack")

        assert response.status_code == 200
        data = response.json()
        assert "Acknowledged" in data["message"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ack_event_unauthenticated(self):
        """Unauthenticated user should get 401."""
        response = client.post("/api/events/evt-001/ack")
        assert response.status_code == 401

    def test_ack_event_forbidden_without_permission(self):
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_VIEW],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.post("/api/events/evt-001/ack")

        assert response.status_code == 403


class TestEventsClose:
    """Tests for POST /api/events/{event_id}/close — close event (auth required)."""

    def test_close_event_success(self, mock_neo4j_driver):
        """Authenticated user should be able to close an event."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_CLOSE],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        mock_session = MagicMock()
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with patch("database.driver", mock_neo4j_driver):
            response = client.post("/api/events/evt-001/close")

        assert response.status_code == 200
        data = response.json()
        assert "Closed" in data["message"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_close_event_unauthenticated(self):
        """Unauthenticated user should get 401."""
        response = client.post("/api/events/evt-001/close")
        assert response.status_code == 401

    def test_close_event_forbidden_without_permission(self):
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_VIEW],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.post("/api/events/evt-001/close")

        assert response.status_code == 403


class TestEventsComment:
    """Tests for POST /api/events/{event_id}/comment — add comment (auth required)."""

    def test_add_comment_unauthenticated(self):
        response = client.post(
            "/api/events/evt-001/comment",
            json={"message": "test"},
        )

        assert response.status_code == 401

    def test_add_comment_with_message_only(self):
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_VIEW],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        with patch(
            "routers.events.event_service.add_event_comment"
        ) as mock_add_comment:
            mock_add_comment.return_value = {"message": "Comment added"}

            response = client.post(
                "/api/events/evt-001/comment",
                json={"message": "Investigating the issue"},
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Comment added"
        mock_add_comment.assert_called_once_with(
            "evt-001", "operator", "Investigating the issue"
        )


class TestEventsPrune:
    """Tests for POST /api/events/prune — bulk close recovered events (auth required)."""

    def test_prune_recovered_success(self, mock_neo4j_driver):
        """Authenticated user should prune recovered events."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_CLOSE],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        class FakeRecord:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

            def get(self, key, default=None):
                return self._data.get(key, default)

        mock_session = MagicMock()
        mock_session.run.return_value = MagicMock(
            single=MagicMock(return_value=FakeRecord({"closed_count": 5}))
        )
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with patch("database.driver", mock_neo4j_driver):
            response = client.post("/api/events/prune")

        assert response.status_code == 200
        data = response.json()
        assert "Cleaned up" in data["message"]
        assert data["count"] == 5

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_prune_recovered_unauthenticated(self):
        """Unauthenticated user should get 401."""
        response = client.post("/api/events/prune")
        assert response.status_code == 401

    def test_prune_recovered_forbidden_without_permission(self):
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_VIEW],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.post("/api/events/prune")

        assert response.status_code == 403


class TestEventsDiagnose:
    """Tests for POST /api/events/{event_id}/diagnose — run diagnostic (auth required)."""

    def test_diagnose_event_not_found(self, mock_neo4j_driver):
        """Should return 404 when event doesn't exist."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.RUN_DIAGNOSTICS],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        mock_session = MagicMock()
        mock_session.run.return_value = MagicMock(single=MagicMock(return_value=None))
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with patch("database.driver", mock_neo4j_driver):
            response = client.post("/api/events/nonexistent/diagnose")

        assert response.status_code == 404

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_diagnose_event_unauthenticated(self):
        """Unauthenticated user should get 401."""
        response = client.post("/api/events/evt-001/diagnose")
        assert response.status_code == 401

    def test_diagnose_event_forbidden_without_permission(self):
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_VIEW],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        response = client.post("/api/events/evt-001/diagnose")

        assert response.status_code == 403

    def test_diagnose_event_success(self, mock_neo4j_driver):
        """Should run diagnostic when event and CI exist."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.RUN_DIAGNOSTICS],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        class FakeNode:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

            def get(self, key, default=None):
                return self._data.get(key, default)

            def keys(self):
                return self._data.keys()

            def __iter__(self):
                return iter(self._data)

        class FakeRecord:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

            def get(self, key, default=None):
                return self._data.get(key, default)

        mock_session = MagicMock()
        mock_session.run.return_value = MagicMock(
            single=MagicMock(
                return_value=FakeRecord(
                    {
                        "ci": FakeNode(
                            {
                                "id": "ci-001",
                                "label": "Router-01",
                                "ip": "192.168.1.1",
                                "type": "router",
                            }
                        ),
                        "m": FakeNode(
                            {
                                "id": "cpu-load",
                                "protocol": "SNMP",
                                "oid": "1.3.6.1.2.1.25.3.3.1.2",
                            }
                        ),
                    }
                )
            )
        )
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with (
            patch("database.driver", mock_neo4j_driver),
            patch(
                "services.event_service.run_diagnostic",
                return_value="Ping OK, SNMP reachable",
            ),
        ):
            response = client.post("/api/events/evt-001/diagnose")

        assert response.status_code == 200
        data = response.json()
        assert "Diagnostic run" in data["message"]

        app.dependency_overrides.pop(get_current_active_user, None)


class TestEventsForcedCloseAuthorization:
    """Tests for forced close authorization on POST /api/events/{event_id}/close.

    Scenarios:
    - F4-T1: EVENT_CLOSE only + forced=False → 200 (normal close still works)
    - F4-T2: EVENT_CLOSE only + forced=True  → 403 (no EVENT_FORCED_CLOSE)
    - F4-T3: EVENT_CLOSE + EVENT_FORCED_CLOSE + forced=True → 200
    """

    def test_normal_close_without_forced_close_perm_succeeds(self, mock_neo4j_driver):
        """User with EVENT_CLOSE but no EVENT_FORCED_CLOSE can do a normal close (forced=False)."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_CLOSE],
        )

        async def override():
            return fake_user

        app.dependency_overrides[get_current_active_user] = override

        mock_session = MagicMock()
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with patch("database.driver", mock_neo4j_driver):
            response = client.post(
                "/api/events/evt-001/close",
                json={"forced": False},
            )

        assert response.status_code == 200
        data = response.json()
        assert "Closed" in data["message"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_forced_close_without_forced_close_perm_is_403(self):
        """User with EVENT_CLOSE but no EVENT_FORCED_CLOSE is denied forced close."""
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_CLOSE],
        )

        async def override():
            return fake_user

        app.dependency_overrides[get_current_active_user] = override

        response = client.post(
            "/api/events/evt-001/close",
            json={"forced": True},
        )

        assert response.status_code == 403
        assert "EVENT_FORCED_CLOSE" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_forced_close_with_forced_close_perm_succeeds(self, mock_neo4j_driver):
        """User with both EVENT_CLOSE and EVENT_FORCED_CLOSE can force-close an event."""
        fake_user = _make_pydantic_user(
            username="t2operator",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_CLOSE, UserPermission.EVENT_FORCED_CLOSE],
        )

        async def override():
            return fake_user

        app.dependency_overrides[get_current_active_user] = override

        mock_session = MagicMock()
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with patch("database.driver", mock_neo4j_driver):
            response = client.post(
                "/api/events/evt-001/close",
                json={"forced": True},
            )

        assert response.status_code == 200
        data = response.json()
        assert "Closed" in data["message"]

        app.dependency_overrides.pop(get_current_active_user, None)
