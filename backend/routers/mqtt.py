"""MQTT raw telemetry and mapping API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from models.mqtt import (
    MqttMappingCreateRequest,
    MqttMappingResponse,
    MqttMappingThresholds,
    MqttMappingUpdateRequest,
    MqttRawDeviceResponse,
    MqttRawMetricResponse,
)
from models.user import User
from services.auth_service import get_current_active_user
from services.mqtt_mapping_service import (
    MQTT_READ_PERMISSION_KIND,
    MqttMappingService,
    get_mqtt_mapping_service,
    require_mqtt_permission,
)
from services.mqtt_raw_reading_service import MqttRawReadingService, get_mqtt_raw_reading_service
from services.mqtt_runtime_status import get_mqtt_runtime_status_service

router = APIRouter(
    prefix="/mqtt",
    tags=["MQTT"],
    responses={404: {"description": "Not found"}},
)


def _current_user(user: User = Depends(get_current_active_user)) -> User:  # noqa: B008
    return user


def _raw_service() -> MqttRawReadingService:
    return get_mqtt_raw_reading_service()


def _mapping_service() -> MqttMappingService:
    return get_mqtt_mapping_service()


def _runtime_status_service():
    return get_mqtt_runtime_status_service()


CurrentUserDep = Depends(_current_user)
RawServiceDep = Depends(_raw_service)
MappingServiceDep = Depends(_mapping_service)
RuntimeStatusServiceDep = Depends(_runtime_status_service)


@router.get("/devices", response_model=list[MqttRawDeviceResponse])
def list_mqtt_devices(
    current_user: User = CurrentUserDep,
    service: MqttRawReadingService = RawServiceDep,
):
    require_mqtt_permission(MQTT_READ_PERMISSION_KIND, current_user)
    return service.list_devices()


@router.get("/devices/{device_id}/metrics", response_model=list[MqttRawMetricResponse])
def list_mqtt_device_metrics(
    device_id: str,
    current_user: User = CurrentUserDep,
    service: MqttRawReadingService = RawServiceDep,
):
    require_mqtt_permission(MQTT_READ_PERMISSION_KIND, current_user)
    return service.list_device_metrics(device_id)


@router.get("/readings", response_model=list[MqttRawMetricResponse])
def list_mqtt_latest_readings(
    limit: int = Query(100, ge=1, le=500),
    current_user: User = CurrentUserDep,
    service: MqttRawReadingService = RawServiceDep,
):
    require_mqtt_permission(MQTT_READ_PERMISSION_KIND, current_user)
    return service.list_latest_readings(limit=limit)


@router.get("/status")
def get_mqtt_status(
    current_user: User = CurrentUserDep,
    status_service=RuntimeStatusServiceDep,
):
    require_mqtt_permission(MQTT_READ_PERMISSION_KIND, current_user)
    return status_service.get_status()


@router.get("/mappings", response_model=list[MqttMappingResponse])
def list_mqtt_mappings(
    status: str | None = None,
    current_user: User = CurrentUserDep,
    service: MqttMappingService = MappingServiceDep,
):
    return service.list_mappings(current_user=current_user, status_filter=status)


@router.post("/mappings", response_model=MqttMappingResponse)
def create_mqtt_mapping(
    payload: MqttMappingCreateRequest,
    current_user: User = CurrentUserDep,
    service: MqttMappingService = MappingServiceDep,
):
    return service.create_mapping(payload, current_user=current_user)


@router.put("/mappings/{mapping_id}", response_model=MqttMappingResponse)
def update_mqtt_mapping(
    mapping_id: str,
    payload: MqttMappingUpdateRequest,
    current_user: User = CurrentUserDep,
    service: MqttMappingService = MappingServiceDep,
):
    return service.update_mapping(mapping_id, payload, current_user=current_user)


@router.post("/mappings/{mapping_id}/approve", response_model=MqttMappingResponse)
def approve_mqtt_mapping(
    mapping_id: str,
    current_user: User = CurrentUserDep,
    service: MqttMappingService = MappingServiceDep,
):
    return service.approve_mapping(mapping_id, current_user=current_user)


@router.post("/mappings/{mapping_id}/revoke", response_model=MqttMappingResponse)
def revoke_mqtt_mapping(
    mapping_id: str,
    current_user: User = CurrentUserDep,
    service: MqttMappingService = MappingServiceDep,
):
    return service.revoke_mapping(mapping_id, current_user=current_user)


@router.get("/mappings/{mapping_id}/thresholds", response_model=MqttMappingThresholds)
def get_mqtt_mapping_thresholds(
    mapping_id: str,
    current_user: User = CurrentUserDep,
    service: MqttMappingService = MappingServiceDep,
):
    return service.get_thresholds(mapping_id, current_user=current_user)


@router.put("/mappings/{mapping_id}/thresholds", response_model=MqttMappingResponse)
def update_mqtt_mapping_thresholds(
    mapping_id: str,
    payload: MqttMappingThresholds,
    current_user: User = CurrentUserDep,
    service: MqttMappingService = MappingServiceDep,
):
    return service.update_thresholds(mapping_id, payload, current_user=current_user)
