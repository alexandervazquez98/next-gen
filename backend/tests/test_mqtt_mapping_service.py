"""Service tests for MQTT mapping lifecycle authorization, validation and audit."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from models.mqtt import MqttMappingCreateRequest, MqttMappingThresholds, MqttMappingUpdateRequest
from models.user import User, UserPermission
from repositories.mqtt_mapping_repo import MappingConflictError, MappingNotFoundError
from services import audit_service
from services.mqtt_mapping_service import MqttMappingService


class _RepoStub:
    def __init__(self):
        self.created = None
        self.updated = None
        self.thresholds = None
        self.raise_on_create = None
        self.raise_on_update = None
        self.raise_on_approve = None
        self.raise_on_revoke = None
        self.get_mapping_calls = []
        self.mappings = [
            {
                "id": "map-1",
                "source_device_id": "rtu-1",
                "source_metric_id": "rtu-1/temp",
                "source_metric_name": "temp",
                "target_ci_id": "ci-1",
                "target_metric_def_id": "temperature",
                "status": "DRAFT",
                "version": 1,
                "operator": ">=",
                "warning": 70.0,
                "critical": 90.0,
            }
        ]

    def get_mapping(self, mapping_id):
        self.get_mapping_calls.append(mapping_id)
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
        return {"id": kwargs["mapping_id"], "status": "DRAFT", "version": 1, **kwargs}

    def update_draft(self, **kwargs):
        if self.raise_on_update:
            raise self.raise_on_update
        self.updated = kwargs
        return {"id": kwargs["mapping_id"], "status": "DRAFT", "version": 1, **kwargs}

    def approve(self, mapping_id, approved_by):
        if self.raise_on_approve:
            raise self.raise_on_approve
        return {
            "id": mapping_id,
            "status": "APPROVED",
            "version": 2,
            "approved_by": approved_by,
        }

    def revoke(self, mapping_id, revoked_by):
        if self.raise_on_revoke:
            raise self.raise_on_revoke
        return {"id": mapping_id, "status": "REVOKED", "version": 3, "revoked_by": revoked_by}

    def update_thresholds(self, **kwargs):
        self.thresholds = kwargs
        return {"id": kwargs["mapping_id"], "status": "APPROVED", "version": 4, **kwargs}


def _user(permissions=None):
    return User(username="operator", role="OPERATOR", permissions=permissions or [])


# ── Issue #386 — audit emission harness ─────────────────────────────────────

_DB = object()  # opaque session sentinel; the service must never introspect it

MANAGE = UserPermission.MQTT_MAPPING_MANAGE.value
READ_ONLY = UserPermission.MQTT_READ.value


@pytest.fixture()
def audit_calls(monkeypatch):
    """Capture `record_critical_change` kwargs and fail if `record_denied` is used."""
    calls: list[dict] = []

    def _record(**kwargs):
        calls.append(kwargs)
        return None

    def _denied(**kwargs):
        raise AssertionError(
            "record_denied hardcodes ACCESS_DENIED and must not be used for MQTT lifecycle events"
        )

    monkeypatch.setattr(audit_service, "record_critical_change", _record)
    monkeypatch.setattr(audit_service, "record_denied", _denied)
    return calls


def _create_payload(**overrides):
    base = {
        "source_device_id": "rtu-1",
        "source_metric_id": "rtu-1/temp",
        "source_metric_name": "temp",
        "target_ci_id": "ci-1",
        "target_metric_def_id": "temperature",
    }
    base.update(overrides)
    return MqttMappingCreateRequest(**base)


def _invoke_create(service, user, **kwargs):
    return service.create_mapping(_create_payload(), user, db=_DB, **kwargs)


def _invoke_update(service, user, **kwargs):
    return service.update_mapping(
        "map-1",
        MqttMappingUpdateRequest(source_metric_name="temperature"),
        user,
        db=_DB,
        **kwargs,
    )


def _invoke_approve(service, user, **kwargs):
    return service.approve_mapping("map-1", user, db=_DB, **kwargs)


def _invoke_revoke(service, user, **kwargs):
    return service.revoke_mapping("map-1", user, db=_DB, **kwargs)


def _invoke_thresholds(service, user, **kwargs):
    return service.update_thresholds(
        "map-1",
        MqttMappingThresholds(operator=">=", warning=75, critical=95),
        user,
        db=_DB,
        **kwargs,
    )


LIFECYCLE_ACTIONS = [
    ("MQTT_MAPPING_CREATE", _invoke_create),
    ("MQTT_MAPPING_UPDATE", _invoke_update),
    ("MQTT_MAPPING_APPROVE", _invoke_approve),
    ("MQTT_MAPPING_REVOKE", _invoke_revoke),
    ("MQTT_MAPPING_THRESHOLD_UPDATE", _invoke_thresholds),
]


@pytest.mark.parametrize(("event_type", "invoke"), LIFECYCLE_ACTIONS)
def test_denied_lifecycle_action_emits_lifecycle_event_type(event_type, invoke, audit_calls):
    """Spec: denied attempts are audited with the lifecycle event type, not ACCESS_DENIED."""
    repo = _RepoStub()
    repo.mappings[0]["status"] = "APPROVED"
    service = MqttMappingService(repo=repo)

    with pytest.raises(HTTPException) as exc:
        invoke(service, _user([READ_ONLY]))

    assert exc.value.status_code == 403
    assert len(audit_calls) == 1
    call = audit_calls[0]
    assert call["event_type"] == event_type
    assert call["outcome"] == "DENIED"
    assert call["target_type"] == "mqtt_mapping"
    assert call["target_id"]
    assert call["context"]["required_permission"] == "MQTT_MAPPING_MANAGE"


def test_denied_action_does_not_touch_the_repository(audit_calls):
    """A denial must be audited before any lifecycle mutation is attempted."""
    repo = _RepoStub()
    service = MqttMappingService(repo=repo)

    with pytest.raises(HTTPException):
        _invoke_approve(service, _user([READ_ONLY]))

    assert repo.created is None
    assert repo.updated is None
    assert repo.thresholds is None
    assert audit_calls[0]["outcome"] == "DENIED"


def test_denied_action_without_db_still_raises_and_emits_nothing(audit_calls):
    """Callers that pass no session (existing unit callers) keep the 403 contract."""
    service = MqttMappingService(repo=_RepoStub())

    with pytest.raises(HTTPException) as exc:
        service.approve_mapping("map-1", _user([READ_ONLY]))

    assert exc.value.status_code == 403
    assert audit_calls == []


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
