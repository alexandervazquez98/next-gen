"""Service tests for MQTT mapping lifecycle authorization and validation."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from models.mqtt import MqttMappingCreateRequest, MqttMappingThresholds, MqttMappingUpdateRequest
from models.user import User, UserPermission
from repositories.mqtt_mapping_repo import MappingConflictError, MappingNotFoundError
from services.mqtt_mapping_service import MqttMappingService


class _RepoStub:
    def __init__(self):
        self.created = None
        self.updated = None
        self.thresholds = None
        self.raise_on_create = None
        self.mappings = [
            {
                "id": "map-1",
                "status": "DRAFT",
                "operator": ">=",
                "warning": 70.0,
                "critical": 90.0,
            }
        ]

    def get_mapping(self, mapping_id):
        for mapping in self.mappings:
            if mapping["id"] == mapping_id:
                return mapping
        return None

    def list_mappings(self, status=None):
        if status is None:
            return self.mappings
        return [mapping for mapping in self.mappings if mapping["status"] == status]

    def create_draft(self, **kwargs):
        if self.raise_on_create:
            raise self.raise_on_create
        self.created = kwargs
        return {"id": kwargs["mapping_id"], "status": "DRAFT", **kwargs}

    def update_draft(self, **kwargs):
        self.updated = kwargs
        return {"id": kwargs["mapping_id"], "status": "DRAFT", **kwargs}

    def approve(self, mapping_id, approved_by):
        return {"id": mapping_id, "status": "APPROVED", "approved_by": approved_by}

    def revoke(self, mapping_id, revoked_by):
        return {"id": mapping_id, "status": "REVOKED", "revoked_by": revoked_by}

    def update_thresholds(self, **kwargs):
        self.thresholds = kwargs
        return {"id": kwargs["mapping_id"], "status": "APPROVED", **kwargs}


def _user(permissions=None):
    return User(username="operator", role="OPERATOR", permissions=permissions or [])


def test_create_mapping_requires_mapping_permission():
    service = MqttMappingService(repo=_RepoStub())
    payload = MqttMappingCreateRequest(
        source_device_id="rtu-1",
        source_metric_id="rtu-1/temp",
        source_metric_name="temp",
        target_ci_id="ci-1",
        target_metric_def_id="temperature",
    )

    with pytest.raises(HTTPException) as exc:
        service.create_mapping(payload, _user([UserPermission.MQTT_READ.value]))

    assert exc.value.status_code == 403


def test_create_mapping_persists_thresholds_and_actor():
    repo = _RepoStub()
    service = MqttMappingService(repo=repo)
    payload = MqttMappingCreateRequest(
        source_device_id="rtu-1",
        source_metric_id="rtu-1/temp",
        source_metric_name="temp",
        target_ci_id="ci-1",
        target_metric_def_id="temperature",
        thresholds=MqttMappingThresholds(operator=">=", warning=70, critical=90),
    )

    result = service.create_mapping(payload, _user([UserPermission.MQTT_MAPPING_MANAGE.value]))

    assert result["status"] == "DRAFT"
    assert repo.created["created_by"] == "operator"
    assert repo.created["warning"] == 70
    assert repo.created["critical"] == 90
    assert repo.created["operator"] == ">="


def test_create_mapping_translates_missing_source_to_404():
    repo = _RepoStub()
    repo.raise_on_create = MappingNotFoundError("Source device not found")
    service = MqttMappingService(repo=repo)
    payload = MqttMappingCreateRequest(
        source_device_id="missing",
        source_metric_id="missing/temp",
        source_metric_name="temp",
        target_ci_id="ci-1",
        target_metric_def_id="temperature",
    )

    with pytest.raises(HTTPException) as exc:
        service.create_mapping(payload, _user([UserPermission.MQTT_MAPPING_MANAGE.value]))

    assert exc.value.status_code == 404


def test_create_mapping_translates_conflict_to_409():
    repo = _RepoStub()
    repo.raise_on_create = MappingConflictError("duplicate")
    service = MqttMappingService(repo=repo)
    payload = MqttMappingCreateRequest(
        source_device_id="rtu-1",
        source_metric_id="rtu-1/temp",
        source_metric_name="temp",
        target_ci_id="ci-1",
        target_metric_def_id="temperature",
    )

    with pytest.raises(HTTPException) as exc:
        service.create_mapping(payload, _user([UserPermission.MQTT_MAPPING_MANAGE.value]))

    assert exc.value.status_code == 409


def test_update_thresholds_requires_mapping_permission():
    service = MqttMappingService(repo=_RepoStub())

    with pytest.raises(HTTPException) as exc:
        service.update_thresholds(
            "map-1",
            MqttMappingThresholds(operator=">=", warning=70, critical=90),
            _user([UserPermission.MQTT_READ.value]),
        )

    assert exc.value.status_code == 403


def test_get_thresholds_requires_read_permission():
    service = MqttMappingService(repo=_RepoStub())

    thresholds = service.get_thresholds("map-1", _user([UserPermission.MQTT_READ.value]))

    assert thresholds == {"operator": ">=", "warning": 70.0, "critical": 90.0}


def test_update_thresholds_requires_approved_mapping():
    repo = _RepoStub()
    service = MqttMappingService(repo=repo)

    with pytest.raises(HTTPException) as exc:
        service.update_thresholds(
            "map-1",
            MqttMappingThresholds(operator=">=", warning=75, critical=95),
            _user([UserPermission.MQTT_MAPPING_MANAGE.value]),
        )

    assert exc.value.status_code == 409
    assert repo.thresholds is None


def test_update_thresholds_updates_approved_mapping():
    repo = _RepoStub()
    repo.mappings[0]["status"] = "APPROVED"
    service = MqttMappingService(repo=repo)

    service.update_thresholds(
        "map-1",
        MqttMappingThresholds(operator=">=", warning=75, critical=95),
        _user([UserPermission.MQTT_MAPPING_MANAGE.value]),
    )

    assert repo.thresholds["warning"] == 75
    assert repo.thresholds["critical"] == 95


def test_update_mapping_passes_partial_fields_to_repo():
    repo = _RepoStub()
    service = MqttMappingService(repo=repo)

    service.update_mapping(
        "map-1",
        MqttMappingUpdateRequest(
            source_metric_name="temperature",
            thresholds=MqttMappingThresholds(operator=">=", warning=60, critical=85),
        ),
        _user([UserPermission.MQTT_MAPPING_MANAGE.value]),
    )

    assert repo.updated["source_metric_name"] == "temperature"
    assert repo.updated["warning"] == 60
    assert repo.updated["critical"] == 85
    assert repo.updated["operator"] == ">="


def test_update_mapping_without_thresholds_preserves_existing_thresholds():
    repo = _RepoStub()
    service = MqttMappingService(repo=repo)

    service.update_mapping(
        "map-1",
        MqttMappingUpdateRequest(source_metric_name="temperature"),
        _user([UserPermission.MQTT_MAPPING_MANAGE.value]),
    )

    assert repo.updated["warning"] == 70.0
    assert repo.updated["critical"] == 90.0
    assert repo.updated["operator"] == ">="
