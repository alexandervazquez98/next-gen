"""Router-level tests for RTU and Sensor endpoints — mocked dependencies.

Focus areas:
- GET /api/v1/rtus — list all RTUs (auth required)
- GET /api/v1/rtus/{rtu_id} — get RTU by ID
- POST /api/v1/rtus — create RTU
- PUT /api/v1/rtus/{rtu_id} — update RTU
- DELETE /api/v1/rtus/{rtu_id} — delete RTU
- GET /api/v1/rtus/{rtu_id}/sensors — list sensors
- POST /api/v1/rtus/{rtu_id}/sensors — create sensor
- PUT /api/v1/rtus/{rtu_id}/sensors/{sensor_id} — update sensor
- DELETE /api/v1/rtus/{rtu_id}/sensors/{sensor_id} — delete sensor

Strategy:
- Patch Neo4j driver BEFORE importing anything that touches database.py
- Use the real app from main.py for TestClient
- Override get_current_active_user for protected endpoints
- Mock RTUService for service-layer isolation
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Patch Neo4j driver BEFORE importing anything that touches database.py
# ---------------------------------------------------------------------------
_mock_neo4j_driver = MagicMock()
with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
    from main import app

from models.user import User, UserPermission  # noqa: E402
from services.auth_service import get_current_active_user  # noqa: E402

# ---------------------------------------------------------------------------
# TestClient (real app)
# ---------------------------------------------------------------------------
client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pydantic_user(
    username: str = "testuser",
    role: str = "OPERATOR",
    permissions: list = None,
    disabled: bool = False,
    allowed_locations: list = None,
) -> User:
    """Create a Pydantic User for injection via dependency override."""
    return User(
        username=username,
        role=role,
        permissions=permissions or [],
        allowed_locations=allowed_locations or [],
        disabled=disabled,
    )


def _override_auth_and_service(user: User, mock_rtu_service):
    from routers import rtus as rtus_module

    async def override_get_current_active_user():
        return user

    app.dependency_overrides[get_current_active_user] = override_get_current_active_user
    app.dependency_overrides[rtus_module.get_rtu_service] = lambda: mock_rtu_service
    return rtus_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_rtu_service():
    """Provides a mock RTUService for router tests."""
    return MagicMock()


@pytest.fixture
def fake_user():
    """Provides a fake authenticated user."""
    return _make_pydantic_user(
        username="testuser",
        role="ADMIN",
        permissions=[
            UserPermission.CI_VIEW,
            UserPermission.CI_EDIT,
            UserPermission.CI_DELETE,
        ],
    )


@pytest.fixture
def auth_override(fake_user, mock_rtu_service):
    """Override auth and RTUService dependencies."""

    async def override_get_current_active_user():
        return fake_user

    from routers import rtus as rtus_module

    app.dependency_overrides[get_current_active_user] = override_get_current_active_user
    app.dependency_overrides[rtus_module.get_rtu_service] = lambda: mock_rtu_service

    yield mock_rtu_service

    # Cleanup
    app.dependency_overrides.pop(get_current_active_user, None)
    app.dependency_overrides.pop(rtus_module.get_rtu_service, None)


# ---------------------------------------------------------------------------
# RTU Endpoint Tests
# ---------------------------------------------------------------------------


class TestRTUsRouter:
    """Tests for RTU CRUD endpoints."""

    def test_get_rtus_returns_list(self, auth_override, mock_rtu_service):
        """GET /api/v1/rtus returns list of RTUs."""
        mock_rtu_service.list_rtus.return_value = [
            {
                "id": str(uuid4()),
                "name": "RTU-01",
                "ip": "192.168.1.100",
                "status": "online",
                "location_id": str(uuid4()),
                "mqtt_topic": "rtu/loc/rtu/telemetry",
                "mqtt_config": None,
                "layer": "RTU",
                "created_at": "2026-05-04T12:00:00Z",
                "updated_at": "2026-05-04T12:00:00Z",
            }
        ]

        response = client.get("/api/v1/rtus")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert data[0]["name"] == "RTU-01"

    def test_get_rtus_with_location_filter(self, auth_override, mock_rtu_service):
        """GET /api/v1/rtus?location_id= filters by location."""
        location_id = str(uuid4())
        mock_rtu_service.list_rtus.return_value = []

        response = client.get(f"/api/v1/rtus?location_id={location_id}")

        assert response.status_code == 200
        mock_rtu_service.list_rtus.assert_called_once()

    def test_get_rtu_by_id_returns_rtu(self, auth_override, mock_rtu_service):
        """GET /api/v1/rtus/{rtu_id} returns the RTU."""
        rtu_id = str(uuid4())
        mock_rtu_service.get_rtu.return_value = {
            "id": rtu_id,
            "name": "RTU-01",
            "ip": "192.168.1.100",
            "status": "online",
            "location_id": str(uuid4()),
            "mqtt_topic": f"rtu/{uuid4()}/{rtu_id}/telemetry",
            "mqtt_config": None,
            "layer": "RTU",
            "created_at": "2026-05-04T12:00:00Z",
            "updated_at": "2026-05-04T12:00:00Z",
        }

        response = client.get(f"/api/v1/rtus/{rtu_id}")

        assert response.status_code == 200
        assert response.json()["id"] == rtu_id

    def test_get_rtu_by_id_returns_404_when_not_found(self, auth_override, mock_rtu_service):
        """GET /api/v1/rtus/{rtu_id} returns 404 when RTU not found."""
        mock_rtu_service.get_rtu.return_value = None

        response = client.get(f"/api/v1/rtus/{uuid4()}")

        assert response.status_code == 404

    def test_read_rtu_routes_reject_low_privilege_user(self, mock_rtu_service):
        """RTU read endpoints require CI_VIEW permission."""
        rtus_module = _override_auth_and_service(
            _make_pydantic_user(role="VIEWER", permissions=[]),
            mock_rtu_service,
        )

        try:
            rtu_id = str(uuid4())

            list_response = client.get("/api/v1/rtus")
            get_response = client.get(f"/api/v1/rtus/{rtu_id}")

            assert list_response.status_code == 403
            assert get_response.status_code == 403
            mock_rtu_service.list_rtus.assert_not_called()
            mock_rtu_service.get_rtu.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(rtus_module.get_rtu_service, None)

    def test_post_rtu_creates_rtu(self, auth_override, mock_rtu_service):
        """POST /api/v1/rtus creates a new RTU."""
        location_id = uuid4()
        mock_rtu_service.create_rtu.return_value = {
            "id": str(uuid4()),
            "name": "RTU-New",
            "location_id": str(location_id),
            "status": "unknown",
            "ip": "192.168.1.50",
            "mqtt_topic": f"rtu/{location_id}/{uuid4()}/telemetry",
            "mqtt_config": None,
            "layer": "RTU",
            "created_at": "2026-05-04T12:00:00Z",
            "updated_at": "2026-05-04T12:00:00Z",
        }

        response = client.post(
            "/api/v1/rtus",
            json={
                "name": "RTU-New",
                "location_id": str(location_id),
                "ip": "192.168.1.50",
            },
        )

        assert response.status_code == 201
        mock_rtu_service.create_rtu.assert_called_once()

    def test_post_rtu_returns_422_on_invalid_payload(self, auth_override):
        """POST /api/v1/rtus returns 422 when required fields missing."""
        response = client.post(
            "/api/v1/rtus",
            json={"name": "RTU-New"},  # missing location_id
        )

        assert response.status_code == 422

    def test_put_rtu_updates_rtu(self, auth_override, mock_rtu_service):
        """PUT /api/v1/rtus/{rtu_id} updates RTU properties."""
        rtu_id = str(uuid4())
        mock_rtu_service.update_rtu.return_value = {
            "id": rtu_id,
            "name": "RTU-Updated",
            "status": "offline",
            "location_id": str(uuid4()),
            "mqtt_topic": f"rtu/{uuid4()}/{rtu_id}/telemetry",
            "mqtt_config": None,
            "layer": "RTU",
            "created_at": "2026-05-04T12:00:00Z",
            "updated_at": "2026-05-04T12:00:00Z",
        }

        response = client.put(
            f"/api/v1/rtus/{rtu_id}",
            json={"name": "RTU-Updated", "status": "offline"},
        )

        assert response.status_code == 200
        mock_rtu_service.update_rtu.assert_called_once()

    def test_put_rtu_returns_404_when_not_found(self, auth_override, mock_rtu_service):
        """PUT /api/v1/rtus/{rtu_id} returns 404 when RTU not found."""
        mock_rtu_service.update_rtu.return_value = None

        response = client.put(
            f"/api/v1/rtus/{uuid4()}",
            json={"name": "RTU-Updated"},
        )

        assert response.status_code == 404

    def test_delete_rtu_deletes_rtu(self, auth_override, mock_rtu_service):
        """DELETE /api/v1/rtus/{rtu_id} deletes RTU."""
        rtu_id = str(uuid4())
        mock_rtu_service.delete_rtu.return_value = True

        response = client.delete(f"/api/v1/rtus/{rtu_id}")

        assert response.status_code == 204
        mock_rtu_service.delete_rtu.assert_called_once_with(rtu_id)

    def test_delete_rtu_returns_404_when_not_found(self, auth_override, mock_rtu_service):
        """DELETE /api/v1/rtus/{rtu_id} returns 404 when RTU not found."""
        mock_rtu_service.delete_rtu.return_value = False

        response = client.delete(f"/api/v1/rtus/{uuid4()}")

        assert response.status_code == 404

    def test_mutating_rtu_routes_reject_low_privilege_user(self, mock_rtu_service):
        """RTU create/update/delete require CI edit/delete permissions."""
        rtus_module = _override_auth_and_service(
            _make_pydantic_user(role="VIEWER", permissions=[UserPermission.CI_VIEW]),
            mock_rtu_service,
        )

        try:
            rtu_id = str(uuid4())
            location_id = str(uuid4())

            create_response = client.post(
                "/api/v1/rtus",
                json={"name": "RTU-New", "location_id": location_id},
            )
            update_response = client.put(
                f"/api/v1/rtus/{rtu_id}",
                json={"name": "RTU-Updated"},
            )
            delete_response = client.delete(f"/api/v1/rtus/{rtu_id}")

            assert create_response.status_code == 403
            assert update_response.status_code == 403
            assert delete_response.status_code == 403
            mock_rtu_service.create_rtu.assert_not_called()
            mock_rtu_service.update_rtu.assert_not_called()
            mock_rtu_service.delete_rtu.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(rtus_module.get_rtu_service, None)


# ---------------------------------------------------------------------------
# Sensor Endpoint Tests
# ---------------------------------------------------------------------------


class TestSensorsRouter:
    """Tests for Sensor CRUD endpoints."""

    def test_get_sensors_for_rtu(self, auth_override, mock_rtu_service):
        """GET /api/v1/rtus/{rtu_id}/sensors returns sensor list."""
        rtu_id = str(uuid4())
        mock_rtu_service.list_sensors.return_value = [
            {
                "id": str(uuid4()),
                "name": "Temp Sensor 1",
                "register_addr": 0,
                "register_count": 2,
                "unit": "0.01°C",
                "sensor_type": "temperature",
                "rtu_id": rtu_id,
                "created_at": "2026-05-04T12:00:00Z",
                "updated_at": "2026-05-04T12:00:00Z",
            }
        ]

        response = client.get(f"/api/v1/rtus/{rtu_id}/sensors")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Temp Sensor 1"

    def test_post_sensor_creates_sensor(self, auth_override, mock_rtu_service):
        """POST /api/v1/rtus/{rtu_id}/sensors creates a new sensor."""
        rtu_id = str(uuid4())
        mock_rtu_service.create_sensor.return_value = {
            "id": str(uuid4()),
            "name": "Humidity Sensor",
            "register_addr": 2,
            "register_count": 2,
            "unit": "0.01%RH",
            "sensor_type": "humidity",
            "rtu_id": rtu_id,
            "created_at": "2026-05-04T12:00:00Z",
            "updated_at": "2026-05-04T12:00:00Z",
        }

        response = client.post(
            f"/api/v1/rtus/{rtu_id}/sensors",
            json={
                "name": "Humidity Sensor",
                "register_addr": 2,
                "register_count": 2,
                "unit": "0.01%RH",
                "sensor_type": "humidity",
            },
        )

        assert response.status_code == 201
        mock_rtu_service.create_sensor.assert_called_once()

    def test_read_sensor_routes_reject_low_privilege_user(self, mock_rtu_service):
        """Sensor read endpoints require CI_VIEW permission."""
        rtus_module = _override_auth_and_service(
            _make_pydantic_user(role="VIEWER", permissions=[]),
            mock_rtu_service,
        )

        try:
            rtu_id = str(uuid4())

            response = client.get(f"/api/v1/rtus/{rtu_id}/sensors")

            assert response.status_code == 403
            mock_rtu_service.list_sensors.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(rtus_module.get_rtu_service, None)

    def test_post_sensor_returns_422_on_invalid_register_bounds(self, auth_override):
        """POST with register_addr > 319 returns 422."""
        rtu_id = str(uuid4())

        response = client.post(
            f"/api/v1/rtus/{rtu_id}/sensors",
            json={
                "name": "Bad Sensor",
                "register_addr": 400,
                "sensor_type": "temperature",
            },
        )

        assert response.status_code == 422

    def test_put_sensor_updates_sensor(self, auth_override, mock_rtu_service):
        """PUT /api/v1/rtus/{rtu_id}/sensors/{sensor_id} updates sensor."""
        sensor_id = str(uuid4())
        mock_rtu_service.update_sensor.return_value = {
            "id": sensor_id,
            "name": "Sensor Updated",
            "register_addr": 0,
            "register_count": 1,
            "unit": "0.01°C",
            "sensor_type": "temperature",
            "rtu_id": str(uuid4()),
            "created_at": "2026-05-04T12:00:00Z",
            "updated_at": "2026-05-04T12:00:00Z",
        }

        response = client.put(
            f"/api/v1/rtus/{uuid4()}/sensors/{sensor_id}",
            json={"name": "Sensor Updated"},
        )

        assert response.status_code == 200

    def test_delete_sensor_deletes_sensor(self, auth_override, mock_rtu_service):
        """DELETE /api/v1/rtus/{rtu_id}/sensors/{sensor_id} deletes sensor."""
        sensor_id = str(uuid4())
        mock_rtu_service.delete_sensor.return_value = True

        response = client.delete(f"/api/v1/rtus/{uuid4()}/sensors/{sensor_id}")

        assert response.status_code == 204

    def test_mutating_sensor_routes_reject_low_privilege_user(self, mock_rtu_service):
        """Sensor create/update/delete require CI edit/delete permissions."""
        rtus_module = _override_auth_and_service(
            _make_pydantic_user(role="VIEWER", permissions=[UserPermission.CI_VIEW]),
            mock_rtu_service,
        )

        try:
            rtu_id = str(uuid4())
            sensor_id = str(uuid4())

            create_response = client.post(
                f"/api/v1/rtus/{rtu_id}/sensors",
                json={"name": "Sensor", "register_addr": 1, "sensor_type": "temperature"},
            )
            update_response = client.put(
                f"/api/v1/rtus/{rtu_id}/sensors/{sensor_id}",
                json={"name": "Sensor Updated"},
            )
            delete_response = client.delete(f"/api/v1/rtus/{rtu_id}/sensors/{sensor_id}")

            assert create_response.status_code == 403
            assert update_response.status_code == 403
            assert delete_response.status_code == 403
            mock_rtu_service.create_sensor.assert_not_called()
            mock_rtu_service.update_sensor.assert_not_called()
            mock_rtu_service.delete_sensor.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(rtus_module.get_rtu_service, None)


# Mark entire module as api tests
pytestmark = [pytest.mark.api]
