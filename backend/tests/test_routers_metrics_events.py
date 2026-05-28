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

import asyncio
from datetime import datetime, timezone
import pytest
import sys
import threading
import types
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Patch Neo4j driver BEFORE importing anything that touches database.py
# The driver is created at module import time and tries to connect immediately
# ---------------------------------------------------------------------------
_mock_neo4j_driver = MagicMock()
_snmp_service_stub = types.ModuleType("services.snmp_service")
setattr(_snmp_service_stub, "snmp_collector_loop", lambda: None)
setattr(
    _snmp_service_stub,
    "get_collector_status",
    lambda: {
        "last_run": None,
        "status": "STOPPED",
        "stats": {},
    },
)
setattr(
    _snmp_service_stub, "validate_snmp_oid", lambda *args, **kwargs: {"success": False}
)
setattr(_snmp_service_stub, "run_diagnostic", lambda *args, **kwargs: "diagnostic-ok")
sys.modules["services.snmp_service"] = _snmp_service_stub
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
        permissions=[permission.value for permission in (permissions or [])],
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

    def test_get_single_metric_returns_full_payload(self, mock_neo4j_driver):
        class DictRecord(dict):
            def __getitem__(self, key):
                return super().__getitem__(key)

        class FakeNode(dict):
            def get(self, key, default=None):
                return super().get(key, default)

        class SingleResult:
            def single(self):
                return DictRecord(
                    {
                        "m": FakeNode(
                            {
                                "id": "cpu-load",
                                "protocol": "SNMP",
                                "warning": 80.0,
                                "critical": 95.0,
                                "oid": "1.3.6.1.2.1.25.3.3.1.2",
                                "dataType": "INTEGER",
                                "unit": "%",
                                "description": "CPU Load",
                                "operator": ">=",
                                "criticality": 2,
                                "polling_interval": 120,
                                "applicable_to": '{"brands": ["cisco"], "models": ["asr1000"]}',
                            }
                        )
                    }
                )

        mock_session = MagicMock()
        mock_session.run.return_value = SingleResult()
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)

        with patch("database.driver", mock_neo4j_driver):
            response = client.get("/api/metrics/cpu-load")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "cpu-load"
        assert data["warning"] == 80.0
        assert data["critical"] == 95.0
        assert data["operator"] == ">="
        assert data["polling_interval"] == 120
        assert data["applicable_to"]["models"] == ["asr1000"]

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

    @pytest.mark.asyncio
    async def test_create_metric_offloads_sync_service_work(self):
        """The async route should not block unrelated coroutine startup."""
        from routers import metrics as metrics_router
        from models.core import MetricDef

        fake_user = _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        started = threading.Event()
        release = threading.Event()

        def blocking_create(metric):
            started.set()
            release.wait(timeout=2)
            return {"message": "Metric defined"}

        async def unrelated(marker: asyncio.Event):
            marker.set()

        with (
            patch("routers.metrics.check_permission", return_value=True),
            patch.object(metrics_router.metric_service, "create_metric", side_effect=blocking_create),
        ):
            metric = MetricDef(id="slow-metric", protocol="SNMP")
            marker_task = None
            route_task = asyncio.create_task(metrics_router.create_metric(metric, fake_user))
            timer = threading.Timer(1.0, release.set)
            timer.start()
            try:
                await asyncio.sleep(0)
                assert not route_task.done()
                assert await asyncio.to_thread(started.wait, 1)

                marker = asyncio.Event()
                marker_task = asyncio.create_task(unrelated(marker))
                await asyncio.wait_for(marker.wait(), timeout=0.1)

                release.set()
                result = await route_task
            finally:
                release.set()
                timer.cancel()
                await asyncio.gather(route_task, return_exceptions=True)
                if marker_task is not None:
                    await marker_task

        assert result == {"message": "Metric defined"}

    @pytest.mark.asyncio
    async def test_create_metric_duplicate_operation_maps_to_409(self):
        from routers import metrics as metrics_router
        from models.core import MetricDef
        from services.metric_operation_guard import MetricOperationInProgress

        fake_user = _make_pydantic_user(permissions=[UserPermission.CI_EDIT])

        with (
            patch("routers.metrics.check_permission", return_value=True),
            patch.object(
                metrics_router.metric_service,
                "create_metric",
                side_effect=MetricOperationInProgress("slow-metric"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await metrics_router.create_metric(MetricDef(id="slow-metric", protocol="SNMP"), fake_user)

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == {
            "message": "Metric operation already in progress",
            "metric_id": "slow-metric",
        }

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

    @pytest.mark.asyncio
    async def test_delete_metric_offloads_sync_service_work(self):
        """The async route should not block unrelated coroutine startup."""
        from routers import metrics as metrics_router

        fake_user = _make_pydantic_user(permissions=[UserPermission.CI_EDIT])
        started = threading.Event()
        release = threading.Event()

        def blocking_delete(metric_id):
            started.set()
            release.wait(timeout=2)
            return {"message": "Metric deleted"}

        async def unrelated(marker: asyncio.Event):
            marker.set()

        with (
            patch("routers.metrics.check_permission", return_value=True),
            patch.object(metrics_router.metric_service, "delete_metric", side_effect=blocking_delete),
        ):
            marker_task = None
            route_task = asyncio.create_task(metrics_router.delete_metric("slow-metric", fake_user))
            timer = threading.Timer(1.0, release.set)
            timer.start()
            try:
                await asyncio.sleep(0)
                assert not route_task.done()
                assert await asyncio.to_thread(started.wait, 1)

                marker = asyncio.Event()
                marker_task = asyncio.create_task(unrelated(marker))
                await asyncio.wait_for(marker.wait(), timeout=0.1)

                release.set()
                result = await route_task
            finally:
                release.set()
                timer.cancel()
                await asyncio.gather(route_task, return_exceptions=True)
                if marker_task is not None:
                    await marker_task

        assert result == {"message": "Metric deleted"}

    @pytest.mark.asyncio
    async def test_delete_metric_duplicate_operation_maps_to_409(self):
        from routers import metrics as metrics_router
        from services.metric_operation_guard import MetricOperationInProgress

        fake_user = _make_pydantic_user(permissions=[UserPermission.CI_EDIT])

        with (
            patch("routers.metrics.check_permission", return_value=True),
            patch.object(
                metrics_router.metric_service,
                "delete_metric",
                side_effect=MetricOperationInProgress("slow-metric"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await metrics_router.delete_metric("slow-metric", fake_user)

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == {
            "message": "Metric operation already in progress",
            "metric_id": "slow-metric",
        }

    def test_delete_metric_success(self):
        """Should delete a metric definition."""
        from routers import metrics as metrics_router

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

        with (
            patch("routers.metrics.check_permission", return_value=True),
            patch.object(
                metrics_router.metric_service,
                "delete_metric",
                return_value={
                    "message": "Metric deleted",
                    "metric_id": "test-cpu",
                    "deleted": True,
                    "events_recovered": 0,
                    "relationships_deleted": 0,
                    "relationship_batches": [],
                    "history_retained": True,
                },
            ),
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

    def test_metric_usage_filters_union_candidates_with_and_logic(self, mock_neo4j_driver):
        """Usage should not count brand-only matches when model filter is also required."""

        class DictRecord(dict):
            def __getitem__(self, key):
                return super().__getitem__(key)

        call_count = [0]

        def mock_run(query, **params):
            call_count[0] += 1
            if call_count[0] == 1:
                return MagicMock(
                    single=MagicMock(
                        return_value=DictRecord(
                            {
                                "apt": '{"brands": ["Cambium Networks"], "models": ["450i"], "excluded_names": []}'
                            }
                        )
                    )
                )

            return [
                DictRecord(
                    {
                        "id": "ci-450i",
                        "name": "Cambium-450i",
                        "ip": "10.0.0.1",
                        "model": "450i",
                        "brand": "Cambium Networks",
                        "layer": "wireless",
                    }
                ),
                DictRecord(
                    {
                        "id": "ci-45700",
                        "name": "Cambium-45700",
                        "ip": "10.0.0.2",
                        "model": "45700",
                        "brand": "Cambium Networks",
                        "layer": "wireless",
                    }
                ),
            ]

        mock_session = MagicMock()
        mock_session.run.side_effect = mock_run
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)

        with patch("database.driver", mock_neo4j_driver):
            response = client.get("/api/metrics/cmb450i-cpu-util/usage")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["cis"][0]["id"] == "ci-450i"


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


class TestMultiMetricsHistory:
    """Tests for GET /api/metrics/{metric_id}/history?node_ids=... — multi-CI batch endpoint."""

    def test_multi_history_returns_nodes_array(self, mock_db):
        """Multi-CI history with valid node_ids returns nodes array."""

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        # Mock the query chain for TimescaleDB
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        response = client.get("/api/metrics/cpu-load/history?node_ids=ci-001,ci-002&hours=24")

        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert isinstance(data["nodes"], list)
        assert len(data["nodes"]) == 2
        assert data["nodes"][0]["node_id"] == "ci-001"
        assert data["nodes"][1]["node_id"] == "ci-002"

        app.dependency_overrides.pop(get_pg_db, None)

    def test_multi_history_max_10_cis_enforced(self, mock_db):
        """Request with more than 10 node_ids returns HTTP 400."""

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        too_many_ids = ",".join([f"ci-{i}" for i in range(15)])
        response = client.get(f"/api/metrics/cpu-load/history?node_ids={too_many_ids}&hours=24")

        assert response.status_code == 400
        assert "Max 10 CIs allowed" in response.json()["detail"]

        app.dependency_overrides.pop(get_pg_db, None)

    def test_multi_history_empty_node_ids_returns_400(self, mock_db):
        """Request with empty node_ids returns HTTP 400."""

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        response = client.get("/api/metrics/cpu-load/history?node_ids=&hours=24")

        assert response.status_code == 400

        app.dependency_overrides.pop(get_pg_db, None)

    def test_multi_history_single_ci_still_returns_nodes_array(self, mock_db):
        """Single CI in node_ids still returns nodes array (not flat array)."""

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        response = client.get("/api/metrics/cpu-load/history?node_ids=ci-001&hours=24")

        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert len(data["nodes"]) == 1

        app.dependency_overrides.pop(get_pg_db, None)

    def test_multi_history_no_node_ids_returns_400(self, mock_db):
        """Request without node_ids on multi-CI endpoint returns HTTP 400."""

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        response = client.get("/api/metrics/cpu-load/history?hours=24")

        assert response.status_code == 400

        app.dependency_overrides.pop(get_pg_db, None)

    def test_multi_history_node_with_no_data_returns_empty_data_array(self, mock_db):
        """CI with no metric data returns node entry with empty data array."""

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_pg_db] = override_get_db

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []  # No data for this CI
        mock_db.query.return_value = mock_query

        response = client.get("/api/metrics/cpu-load/history?node_ids=ci-empty&hours=24")

        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        ci_node = next((n for n in data["nodes"] if n["node_id"] == "ci-empty"), None)
        assert ci_node is not None
        assert ci_node["data"] == []

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
                                        "metric_id": "cpu-load",
                                        "value": 97.5,
                                        "message": "CPU exceeded threshold",
                                        "created_at": datetime.utcnow(),
                                        "last_seen": datetime.utcnow(),
                                        "ack": False,
                                    }
                                ),
                                "ci": _FakeNeo4jNode(
                                    {
                                        "id": "ci-001",
                                        "name": "Router-01",
                                        "ip": "10.0.0.1",
                                        "location_name": "Madrid HQ",
                                    }
                                ),
                                "m": _FakeNeo4jNode(
                                    {
                                        "id": "cpu-load",
                                        "name": "cpu-load",
                                        "protocol": "SNMP",
                                    }
                                ),
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
        """ACTIVE status should request unresolved OPEN/ACK events from the service."""
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

    def test_list_events_remains_summary_only(self):
        """Summary polling must not expose modal-only business context payloads."""
        payload = [
            {
                "id": "evt-lean",
                "ci_id": "ci-001",
                "ci_name": "Router-01",
                "ci_node_id": "ci-001",
                "metric_id": "cpu-load",
                "metric_name": "cpu-load",
                "metric_protocol": "SNMP",
                "status": "OPEN",
                "severity": "CRITICAL",
                "message": "CPU exceeded threshold",
                "created_at": "2026-04-05T11:00:00+00:00",
                "last_seen": "2026-04-05T11:00:00+00:00",
                "ack": False,
                "ack_by": "operator-1",
                "closed_by": "operator-2",
                "comments": [
                    "[AUDIT][CLOSE] Evento cerrado por operator-2\nNota: detalle interno"
                ],
            }
        ]

        with patch("routers.events.event_service.get_events", return_value=payload):
            response = client.get("/api/events")

        assert response.status_code == 200
        data = response.json()
        assert "business_context" not in data[0]
        assert "itsm_context" not in data[0]
        assert "comments" not in data[0]
        assert "ack_by" not in data[0]
        assert "closed_by" not in data[0]

    def test_list_events_allows_sparse_legacy_events_and_exposes_discriminators(self):
        """Response model should not drop event discriminators or reject missing metric_id."""
        payload = [
            {
                "id": "evt-sparse-icmp",
                "ci_id": "ci-001",
                "ci_name": "Router-01",
                "ci_node_id": "ci-001",
                "status": "OPEN",
                "severity": "CRITICAL",
                "message": "Service/Host Down: ICMP",
                "ack": False,
                "event_type": "AVAILABILITY",
                "source_protocol": "ICMP",
            }
        ]

        with patch("routers.events.event_service.get_events", return_value=payload):
            response = client.get("/api/events?status=ACTIVE")

        assert response.status_code == 200
        event = response.json()[0]
        assert event["metric_id"] is None
        assert event["metric_name"] is None
        assert event["metric_protocol"] is None
        assert event["created_at"] is None
        assert event["event_type"] == "AVAILABILITY"
        assert event["source_protocol"] == "ICMP"

    def test_availability_report_endpoint_is_additive_and_accepts_custom_window(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 31, tzinfo=timezone.utc)
        payload = {
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "generated_at": end.isoformat(),
            "window_days": 30,
            "total_groups": 1,
            "rows": [
                {
                    "ci_id": "ci-001",
                    "ci_name": "Router-01",
                    "event_type": "AVAILABILITY",
                    "recovered_incidents": 2,
                    "mttr_seconds": 900,
                    "mtbf_seconds": 7200,
                    "downtime_seconds": 1800,
                    "active_events": 0,
                    "active_downtime_seconds": 0,
                    "availability_percentage": 99.9306,
                    "first_failure_at": start.isoformat(),
                    "last_failure_at": end.isoformat(),
                    "ci": {
                        "id": "ci-001",
                        "label": "Router-01",
                        "category": "Routers",
                        "type": "Routers",
                        "ip": "10.0.0.1",
                        "owner": "NOC",
                        "metadata": {"rack": "R1"},
                    },
                }
            ],
        }

        with patch(
            "routers.events.event_service.get_availability_report", return_value=payload
        ) as get_report:
            response = client.get(
                "/api/events/availability-report",
                params={"start": start.isoformat(), "end": end.isoformat()},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["window_start"] == payload["window_start"]
        assert body["window_end"] == payload["window_end"]
        assert body["generated_at"] == payload["generated_at"]
        assert body["window_days"] == 30.0
        assert body["total_groups"] == 1
        row = body["rows"][0]
        assert row["ci_id"] == "ci-001"
        assert row["ci_name"] == "Router-01"
        assert row["mttr_seconds"] == 900
        assert row["mtbf_seconds"] == 7200
        assert row["ci"]["id"] == "ci-001"
        assert row["ci"]["label"] == "Router-01"
        assert row["ci"]["category"] == "Routers"
        assert row["ci"]["type"] == "Routers"
        assert row["ci"]["ip"] == "10.0.0.1"
        assert row["ci"]["owner"] == "NOC"
        assert row["ci"]["metadata"] == {"rack": "R1"}
        get_report.assert_called_once()
        assert get_report.call_args.kwargs["start"] == start
        assert get_report.call_args.kwargs["end"] == end

    def test_availability_report_endpoint_keeps_old_rows_valid(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        payload = {
            "window_start": start.isoformat(),
            "window_end": start.isoformat(),
            "generated_at": start.isoformat(),
            "window_days": 0,
            "total_groups": 1,
            "rows": [
                {
                    "ci_id": "ci-001",
                    "ci_name": "Router-01",
                    "event_type": "AVAILABILITY",
                    "recovered_incidents": 0,
                    "mttr_seconds": None,
                    "mtbf_seconds": None,
                    "downtime_seconds": 0,
                    "active_events": 0,
                    "active_downtime_seconds": 0,
                    "availability_percentage": None,
                    "first_failure_at": None,
                    "last_failure_at": None,
                }
            ],
        }

        with patch(
            "routers.events.event_service.get_availability_report", return_value=payload
        ):
            response = client.get("/api/events/availability-report")

        assert response.status_code == 200
        body = response.json()
        assert body["rows"][0]["ci_id"] == "ci-001"
        assert body["rows"][0].get("ci") in (None, {})


class TestEventsDetail:
    """Tests for GET /api/events/{event_id} — modal detail payload."""

    def test_get_event_detail_success(self):
        fake_user = _make_pydantic_user(
            username="viewer",
            role="VIEWER",
            permissions=[UserPermission.EVENT_VIEW],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        payload = {
            "event": {
                "id": "evt-001",
                "ci_id": "ci-001",
                "ci_name": "Router-01",
                "metric_id": "cpu-load",
                "metric_name": "cpu-load",
                "metric_protocol": "SNMP",
                "status": "OPEN",
                "severity": "CRITICAL",
                "message": "CPU exceeded threshold",
                "created_at": "2026-04-05T11:25:00+00:00",
                "last_seen": "2026-04-05T11:25:00+00:00",
                "ack": False,
                "ci_ref": {
                    "id": "ci-001",
                    "label": "Router-01",
                    "hostname": "10.0.0.1",
                    "location_name": "Madrid HQ",
                },
            },
            "business_context": {
                "source": "snapshot",
                "business_service": {
                    "id": "svc-001",
                    "name": "Corp-WAN",
                    "owner_t1": "Mesa N1",
                    "owner_t2": "NetOps",
                    "owner_t3": "Arquitectura",
                },
                "service_catalog": {
                    "id": "sla-001",
                    "category": "NETWORK",
                    "service_tier": "Gold",
                    "sla_minutes": 60,
                },
                "impacted_users": 350,
                "sla_remaining_minutes": 25,
                "site": "Madrid HQ",
            },
            "itsm_context": {
                "assignment_state": "unassigned",
                "assigned_to": None,
                "opened_by": "system",
                "escalation_tier": "T2",
                "external_ticket": None,
            },
        }

        with patch(
            "routers.events.event_service.get_event_detail", return_value=payload
        ):
            response = client.get("/api/events/evt-001")

        assert response.status_code == 200
        data = response.json()
        assert data["event"]["ci_ref"]["id"] == "ci-001"
        assert data["business_context"]["source"] == "snapshot"
        assert data["business_context"]["sla_remaining_minutes"] == 25
        assert data["itsm_context"]["opened_by"] == "system"

    def test_get_event_detail_requires_authentication(self):
        response = client.get("/api/events/evt-001")

        assert response.status_code == 401

    def test_get_event_detail_forbidden_without_event_view_permission(self):
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

        response = client.get("/api/events/evt-001")

        assert response.status_code == 403
        assert response.json()["detail"] == "Not authorized to view events"

    def test_get_event_detail_real_contract_handles_partial_snapshot(
        self, mock_neo4j_driver
    ):
        fake_user = _make_pydantic_user(
            username="viewer",
            role="VIEWER",
            permissions=[UserPermission.EVENT_VIEW],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        class FakeRecord(dict):
            def __getitem__(self, key):
                return super().__getitem__(key)

            def get(self, key, default=None):
                return super().get(key, default)

        mock_session = MagicMock()
        mock_session.run.return_value.single.return_value = FakeRecord(
            {
                "e": _FakeNeo4jNode(
                    {
                        "id": "evt-legacy",
                        "ci_id": "ci-legacy",
                        "metric_id": "ping",
                        "status": "OPEN",
                        "severity": "WARNING",
                        "message": "Legacy event without full snapshot",
                        "created_at": "not-a-datetime",
                        "last_seen": "not-a-datetime",
                        "ack": False,
                        "business_service_name": "Legacy Payments",
                    }
                ),
                "ci": _FakeNeo4jNode(
                    {
                        "id": "ci-legacy",
                        "label": "Router-99",
                        "ip": "10.0.0.99",
                        "locationName": None,
                    }
                ),
                "m": _FakeNeo4jNode({"id": "ping", "protocol": "ICMP"}),
                "bs": None,
                "sc": _FakeNeo4jNode({"id": "sla-legacy", "category": "NETWORK"}),
            }
        )
        mock_neo4j_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )

        with patch("database.driver", mock_neo4j_driver):
            response = client.get("/api/events/evt-legacy")

        assert response.status_code == 200
        data = response.json()
        assert data["business_context"]["source"] == "mixed"
        assert data["business_context"]["business_service"] is None
        assert data["business_context"]["service_catalog"]["id"] == "sla-legacy"
        assert data["business_context"]["service_catalog"].get("service_tier") is None
        assert data["business_context"]["sla_remaining_minutes"] is None

    def test_get_event_detail_404(self):
        fake_user = _make_pydantic_user(
            username="viewer",
            role="VIEWER",
            permissions=[UserPermission.EVENT_VIEW],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        with patch(
            "routers.events.event_service.get_event_detail",
            side_effect=HTTPException(status_code=404, detail="Event not found"),
        ):
            response = client.get("/api/events/missing")

        assert response.status_code == 404
        assert response.json()["detail"] == "Event not found"


class TestEventsRelated:
    """Tests for GET /api/events/related/{ci_id} — events for a CI."""

    def test_related_events_returns_data(self, mock_neo4j_driver):
        """Should return active events for a specific CI."""
        fake_user = _make_pydantic_user(
            username="viewer",
            role="VIEWER",
            permissions=[UserPermission.EVENT_VIEW],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

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
        app.dependency_overrides.pop(get_current_active_user, None)

    def test_related_events_requires_authentication(self):
        response = client.get("/api/events/related/ci-001")

        assert response.status_code == 401

    def test_related_events_forbidden_without_event_view_permission(self):
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

        response = client.get("/api/events/related/ci-001")

        assert response.status_code == 403
        assert response.json()["detail"] == "Not authorized to view events"
        app.dependency_overrides.pop(get_current_active_user, None)


class TestEventsAck:
    """Tests for POST /api/events/{event_id}/ack — acknowledge event (auth required)."""

    def test_ack_event_success(self):
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

        with patch("routers.events.event_service.ack_event") as mock_ack_event:
            mock_ack_event.return_value = {"message": "Event Acknowledged"}
            response = client.post("/api/events/evt-001/ack")

        assert response.status_code == 200
        data = response.json()
        assert "Acknowledged" in data["message"]
        mock_ack_event.assert_called_once_with(
            "evt-001", "operator", comment_message=None
        )

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_ack_event_accepts_atomic_ownership_comment(self):
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

        with patch("routers.events.event_service.ack_event") as mock_ack_event:
            mock_ack_event.return_value = {"message": "Event Acknowledged"}
            response = client.post(
                "/api/events/evt-001/ack",
                json={
                    "comment_message": "[OWNERSHIP] Caso tomado por operator - Tier T2"
                },
            )

        assert response.status_code == 200
        mock_ack_event.assert_called_once_with(
            "evt-001",
            "operator",
            comment_message="[OWNERSHIP] Caso tomado por operator - Tier T2",
        )

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

    def test_close_event_success(self):
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

        with patch("routers.events.event_service.close_event") as mock_close_event:
            mock_close_event.return_value = {"message": "Event Closed"}
            response = client.post("/api/events/evt-001/close")

        assert response.status_code == 200
        data = response.json()
        assert "Closed" in data["message"]
        mock_close_event.assert_called_once_with(
            "evt-001", "operator", forced=False, comment_message=None
        )

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_close_event_accepts_atomic_closure_comment(self):
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

        with patch("routers.events.event_service.close_event") as mock_close_event:
            mock_close_event.return_value = {"message": "Event Closed"}
            response = client.post(
                "/api/events/evt-001/close",
                json={
                    "forced": False,
                    "comment_message": "[CIERRE] Causa raíz: Error de configuración\nNota: Se corrigió la configuración BGP",
                },
            )

        assert response.status_code == 200
        mock_close_event.assert_called_once_with(
            "evt-001",
            "operator",
            forced=False,
            comment_message="[CIERRE] Causa raíz: Error de configuración\nNota: Se corrigió la configuración BGP",
        )

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

    def test_close_event_requires_structured_root_cause_and_note(
        self, mock_neo4j_driver
    ):
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

        with patch("database.driver", mock_neo4j_driver):
            response = client.post(
                "/api/events/evt-001/close",
                json={"forced": False, "comment_message": "Nota: corto"},
            )

        assert response.status_code == 400
        assert "Causa raíz" in response.json()["detail"]
        app.dependency_overrides.pop(get_current_active_user, None)

    def test_forced_close_requires_reason(self, mock_neo4j_driver):
        fake_user = _make_pydantic_user(
            username="operator",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_CLOSE, UserPermission.EVENT_FORCED_CLOSE],
        )

        async def override_get_current_active_user():
            return fake_user

        app.dependency_overrides[get_current_active_user] = (
            override_get_current_active_user
        )

        with patch("database.driver", mock_neo4j_driver):
            response = client.post(
                "/api/events/evt-001/close",
                json={"forced": True, "comment_message": "   "},
            )

        assert response.status_code == 400
        assert "Forced close requires a reason" in response.json()["detail"]
        app.dependency_overrides.pop(get_current_active_user, None)


class TestEventsComment:
    """Tests for POST /api/events/{event_id}/comment — add comment (auth + permission)."""

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
            permissions=[UserPermission.EVENT_ACK],
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

    def test_add_comment_forbidden_without_event_permission(self):
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
            "/api/events/evt-001/comment",
            json={"message": "Investigating the issue"},
        )

        assert response.status_code == 403

        app.dependency_overrides.pop(get_current_active_user, None)


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
                json={
                    "forced": False,
                    "comment_message": "Causa raíz: Falla de hardware\nNota: Se reemplazó el módulo principal averiado",
                },
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
                json={
                    "forced": True,
                    "comment_message": "Motivo: Ventana de mantenimiento aprobada",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "Closed" in data["message"]

        app.dependency_overrides.pop(get_current_active_user, None)
