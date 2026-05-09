# backend/routers/rtus.py
"""RTU and Sensor API — CRUD endpoints for RTU devices and their sensors.

Router prefix: /api/v1 (applied in main.py)
Tags: ["RTUs"]
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ValidationError

from models.rtu_sensor import (
    RTUCreate,
    RTUUpdate,
    RTUResponse,
    SensorCreate,
    SensorUpdate,
    SensorResponse,
)
from models.user import User
from services.auth_service import get_current_active_user
from services.rtu_service import RTUService

router = APIRouter(
    prefix="/rtus",
    tags=["RTUs"],
    responses={404: {"description": "Not found"}},
)


# ── Service factory ───────────────────────────────────────────────────────────


def get_rtu_service() -> RTUService:
    """Dependency that provides an RTUService instance.

    Allows tests to inject a mock service.
    """
    return RTUService()


# ── Request/Response schemas ─────────────────────────────────────────────────


class ErrorDetail(BaseModel):
    error: str
    message: str
    details: Optional[List[dict]] = None


class SensorCreateInternal(SensorCreate):
    """SensorCreate with rtu_id injected from path."""

    pass


# ── RTU Endpoints ─────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=List[RTUResponse],
    summary="List all RTUs",
    description="Returns all RTU nodes, optionally filtered by location_id query param.",
)
async def list_rtus(
    location_id: Optional[UUID] = Query(None, description="Filter by location UUID"),
    current_user: User = Depends(get_current_active_user),
    service: RTUService = Depends(get_rtu_service),
) -> List[RTUResponse]:
    """GET /api/v1/rtus — list all RTUs (optionally filtered by location)."""
    rtus = service.list_rtus(location_id=location_id)
    return [RTUResponse(**rtu) for rtu in rtus]


@router.get(
    "/{rtu_id}",
    response_model=RTUResponse,
    summary="Get RTU by ID",
    description="Returns a single RTU node by its UUID.",
)
async def get_rtu(
    rtu_id: UUID,
    current_user: User = Depends(get_current_active_user),
    service: RTUService = Depends(get_rtu_service),
) -> RTUResponse:
    """GET /api/v1/rtus/{rtu_id} — get RTU by ID."""
    rtu = service.get_rtu(str(rtu_id))
    if rtu is None:
        raise HTTPException(status_code=404, detail=f"RTU {rtu_id} not found")
    return RTUResponse(**rtu)


@router.post(
    "",
    response_model=RTUResponse,
    status_code=201,
    summary="Create RTU",
    description="Creates a new RTU node linked to a Location.",
)
async def create_rtu(
    rtu_in: RTUCreate,
    current_user: User = Depends(get_current_active_user),
    service: RTUService = Depends(get_rtu_service),
) -> RTUResponse:
    """POST /api/v1/rtus — create a new RTU node."""
    rtu = service.create_rtu(
        name=rtu_in.name,
        location_id=rtu_in.location_id,
        ip=rtu_in.ip,
        mqtt_config=rtu_in.mqtt_config,
    )
    return RTUResponse(**rtu)


@router.put(
    "/{rtu_id}",
    response_model=RTUResponse,
    summary="Update RTU",
    description="Updates RTU properties (name, ip, status, mqtt_config).",
)
async def update_rtu(
    rtu_id: UUID,
    rtu_in: RTUUpdate,
    current_user: User = Depends(get_current_active_user),
    service: RTUService = Depends(get_rtu_service),
) -> RTUResponse:
    """PUT /api/v1/rtus/{rtu_id} — update RTU properties."""
    rtu = service.update_rtu(
        rtu_id=str(rtu_id),
        name=rtu_in.name,
        ip=rtu_in.ip,
        status=rtu_in.status,
        mqtt_config=rtu_in.mqtt_config,
    )
    if rtu is None:
        raise HTTPException(status_code=404, detail=f"RTU {rtu_id} not found")
    return RTUResponse(**rtu)


@router.delete(
    "/{rtu_id}",
    status_code=204,
    summary="Delete RTU",
    description="Deletes an RTU node and cascades to all its Sensor children.",
)
async def delete_rtu(
    rtu_id: UUID,
    current_user: User = Depends(get_current_active_user),
    service: RTUService = Depends(get_rtu_service),
) -> None:
    """DELETE /api/v1/rtus/{rtu_id} — delete RTU (cascade sensors)."""
    deleted = service.delete_rtu(str(rtu_id))
    if not deleted:
        raise HTTPException(status_code=404, detail=f"RTU {rtu_id} not found")


# ── Sensor Endpoints ────────────────────────────────────────────────────────────


@router.get(
    "/{rtu_id}/sensors",
    response_model=List[SensorResponse],
    summary="List sensors for RTU",
    description="Returns all Sensor nodes attached to this RTU via HAS_SENSOR.",
)
async def list_sensors(
    rtu_id: UUID,
    current_user: User = Depends(get_current_active_user),
    service: RTUService = Depends(get_rtu_service),
) -> List[SensorResponse]:
    """GET /api/v1/rtus/{rtu_id}/sensors — list sensors for an RTU."""
    sensors = service.list_sensors(str(rtu_id))
    return [SensorResponse(**s) for s in sensors]


@router.post(
    "/{rtu_id}/sensors",
    response_model=SensorResponse,
    status_code=201,
    summary="Register sensor on RTU",
    description="Creates a new Sensor node attached to the specified RTU.",
)
async def create_sensor(
    rtu_id: UUID,
    sensor_in: SensorCreate,
    current_user: User = Depends(get_current_active_user),
    service: RTUService = Depends(get_rtu_service),
) -> SensorResponse:
    """POST /api/v1/rtus/{rtu_id}/sensors — create sensor on RTU."""
    sensor = service.create_sensor(
        rtu_id=str(rtu_id),
        name=sensor_in.name,
        register_addr=sensor_in.register_addr,
        register_count=sensor_in.register_count,
        unit=sensor_in.unit,
        sensor_type=sensor_in.sensor_type,
    )
    return SensorResponse(**sensor)


@router.put(
    "/{rtu_id}/sensors/{sensor_id}",
    response_model=SensorResponse,
    summary="Update sensor",
    description="Updates sensor properties (name, unit).",
)
async def update_sensor(
    rtu_id: UUID,
    sensor_id: UUID,
    sensor_in: SensorUpdate,
    current_user: User = Depends(get_current_active_user),
    service: RTUService = Depends(get_rtu_service),
) -> SensorResponse:
    """PUT /api/v1/rtus/{rtu_id}/sensors/{sensor_id} — update sensor."""
    sensor = service.update_sensor(
        rtu_id=str(rtu_id),
        sensor_id=str(sensor_id),
        name=sensor_in.name,
        unit=sensor_in.unit,
    )
    if sensor is None:
        raise HTTPException(status_code=404, detail=f"Sensor {sensor_id} not found")
    return SensorResponse(**sensor)


@router.delete(
    "/{rtu_id}/sensors/{sensor_id}",
    status_code=204,
    summary="Delete sensor",
    description="Deletes a single Sensor node.",
)
async def delete_sensor(
    rtu_id: UUID,
    sensor_id: UUID,
    current_user: User = Depends(get_current_active_user),
    service: RTUService = Depends(get_rtu_service),
) -> None:
    """DELETE /api/v1/rtus/{rtu_id}/sensors/{sensor_id} — delete sensor."""
    deleted = service.delete_sensor(rtu_id=str(rtu_id), sensor_id=str(sensor_id))
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Sensor {sensor_id} not found")
