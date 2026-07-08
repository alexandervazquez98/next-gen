"""Router tests for MQTT raw visibility and mapping APIs."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from models.user import User, UserPermission
from routers import mqtt
from services.mqtt_raw_reading_service import MqttRawReadingService


class _StatusService:
    def get_status(self):
        return {
            "service_name": "mqtt-subscriber",
            "configured": True,
            "running": True,
            "connected": True,
            "subscribed_patterns": ["rtu/+/telemetry"],
            "mapped_writes_total": 5,
            "unmapped_skips_total": 2,
            "failed_writes_total": 1,
            "last_error": None,
            "reason_code": None,
            "is_stale": False,
        }


class _RawService:
    def list_devices(self):
        return [
            {
                "device_id": "rtu-1",
                "name": "RTU 1",
                "classification": "RAW_MQTT_NON_KPI",
                "kpi_eligible": False,
                "mapped_metrics_count": 0,
                "unmapped_metrics_count": 1,
            }
        ]

    def list_device_metrics(self, device_id):
        return [
            {
                "device_id": device_id,
                "metric_id": f"{device_id}/temp",
                "name": "temp",
                "last_value": 42.0,
                "classification": "RAW_MQTT_NON_KPI",
                "kpi_eligible": False,
                "mapping_status": "UNMAPPED",
            }
        ]

    def list_latest_readings(self, limit=100):
        return [
            {
                "device_id": "rtu-1",
                "metric_id": "rtu-1/temp",
                "name": "temp",
                "last_value": 42.0,
                "classification": "RAW_MQTT_NON_KPI",
                "kpi_eligible": False,
                "mapping_status": "UNMAPPED",
            }
        ]


class _MappingService:
    def __init__(self):
        self.created = None
        self.thresholds = None

    def list_mappings(self, current_user, status_filter=None):
        return [
            {
                "id": "map-1",
                "source_device_id": "rtu-1",
                "source_metric_id": "rtu-1/temp",
                "source_metric_name": "temp",
                "target_ci_id": "ci-1",
                "target_metric_def_id": "temperature",
                "status": status_filter or "DRAFT",
            }
        ]

    def create_mapping(self, payload, current_user):
        self.created = payload
        return {
            "id": "map-1",
            "source_device_id": payload.source_device_id,
            "source_metric_id": payload.source_metric_id,
            "source_metric_name": payload.source_metric_name,
            "target_ci_id": payload.target_ci_id,
            "target_metric_def_id": payload.target_metric_def_id,
            "status": "DRAFT",
        }

    def update_mapping(self, mapping_id, payload, current_user):
        return {"id": mapping_id, "status": "DRAFT"}

    def approve_mapping(self, mapping_id, current_user):
        return {"id": mapping_id, "status": "APPROVED"}

    def revoke_mapping(self, mapping_id, current_user):
        return {"id": mapping_id, "status": "REVOKED"}

    def get_thresholds(self, mapping_id, current_user):
        return {"operator": ">=", "warning": 70, "critical": 90}

    def update_thresholds(self, mapping_id, thresholds, current_user):
        self.thresholds = thresholds
        return {
            "id": mapping_id,
            "status": "APPROVED",
            "operator": thresholds.operator,
            "warning": thresholds.warning,
            "critical": thresholds.critical,
        }


def _user(permissions=None):
    return User(username="operator", role="OPERATOR", permissions=permissions or [])


def _client(user=None, mapping_service=None, status_service=None):
    app = FastAPI()
    app.include_router(mqtt.router, prefix="/api")
    app.dependency_overrides[mqtt._current_user] = lambda: user or _user(
        [UserPermission.MQTT_READ.value, UserPermission.MQTT_MAPPING_MANAGE.value]
    )
    app.dependency_overrides[mqtt._raw_service] = lambda: _RawService()
    app.dependency_overrides[mqtt._mapping_service] = lambda: mapping_service or _MappingService()
    if status_service is not None:
        app.dependency_overrides[mqtt._runtime_status_service] = lambda: status_service
    return TestClient(app)


def test_raw_service_maps_repository_ids_to_api_fields():
    class Repo:
        def list_devices(self):
            return [{"id": "rtu-1", "name": "RTU 1"}]

        def list_metrics_with_mapping_status(self, device_id):
            return [
                {"id": f"{device_id}/temp", "device_id": device_id, "mapping_status": "UNMAPPED"}
            ]

        def list_latest_readings(self, limit=100):
            return [{"id": "rtu-1/temp", "device_id": "rtu-1", "mapping_status": "UNMAPPED"}]

    service = MqttRawReadingService(repo=Repo())

    assert service.list_devices()[0]["device_id"] == "rtu-1"
    assert service.list_device_metrics("rtu-1")[0]["metric_id"] == "rtu-1/temp"
    assert service.list_latest_readings()[0]["metric_id"] == "rtu-1/temp"


def test_raw_devices_are_labeled_non_kpi():
    response = _client().get("/api/mqtt/devices")

    assert response.status_code == 200
    assert response.json()[0]["classification"] == "RAW_MQTT_NON_KPI"
    assert response.json()[0]["kpi_eligible"] is False


def test_raw_metrics_include_unmapped_status():
    response = _client().get("/api/mqtt/devices/rtu-1/metrics")

    assert response.status_code == 200
    assert response.json()[0]["mapping_status"] == "UNMAPPED"
    assert response.json()[0]["kpi_eligible"] is False


def test_raw_readings_require_mqtt_read_permission():
    response = _client(user=_user([])).get("/api/mqtt/readings")

    assert response.status_code == 403


def test_create_mapping_uses_mapping_service():
    mapping_service = _MappingService()
    response = _client(mapping_service=mapping_service).post(
        "/api/mqtt/mappings",
        json={
            "source_device_id": "rtu-1",
            "source_metric_id": "rtu-1/temp",
            "source_metric_name": "temp",
            "target_ci_id": "ci-1",
            "target_metric_def_id": "temperature",
            "thresholds": {"operator": ">=", "warning": 70, "critical": 90},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "DRAFT"
    assert mapping_service.created.source_device_id == "rtu-1"


def test_invalid_threshold_operator_returns_422():
    response = _client().put(
        "/api/mqtt/mappings/map-1/thresholds",
        json={"operator": "between", "warning": 70, "critical": 90},
    )

    assert response.status_code == 422


def test_approve_and_revoke_mapping_endpoints():
    client = _client()

    approve = client.post("/api/mqtt/mappings/map-1/approve")
    revoke = client.post("/api/mqtt/mappings/map-1/revoke")

    assert approve.status_code == 200
    assert approve.json()["status"] == "APPROVED"
    assert revoke.status_code == 200
    assert revoke.json()["status"] == "REVOKED"


def test_threshold_read_and_update_endpoints():
    client = _client()

    get_response = client.get("/api/mqtt/mappings/map-1/thresholds")
    put_response = client.put(
        "/api/mqtt/mappings/map-1/thresholds",
        json={"operator": ">=", "warning": 75, "critical": 95},
    )

    assert get_response.status_code == 200
    assert get_response.json()["warning"] == 70
    assert put_response.status_code == 200
    assert put_response.json()["warning"] == 75


def test_status_endpoint_exposes_bridge_counters():
    response = _client(status_service=_StatusService()).get("/api/mqtt/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mapped_writes_total"] == 5
    assert payload["unmapped_skips_total"] == 2
    assert payload["failed_writes_total"] == 1
    assert payload["service_name"] == "mqtt-subscriber"
