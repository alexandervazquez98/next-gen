"""Routers for ITSM service catalog domain.

These endpoints are intentionally isolated from event workflows.
They only manage Service Catalog state via the ITSM API slice and do
not mutate or trigger event/folio side effects.
"""
# ruff: noqa: I001

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

import services.itsm_service_catalog_service as service_catalog_service
from models.itsm import ServiceCatalogCreate
from models.user import User, UserPermission
from services.auth_service import check_permission, get_current_active_user

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]
LimitQuery = Annotated[int, Query(ge=1, le=500)]

router = APIRouter(prefix="/itsm/service-catalog", tags=["ITSM Service Catalog"])


@router.get("", response_model=list[dict[str, Any]])
async def list_service_catalogs(
    current_user: CurrentUserDep,
    limit: LimitQuery = 100,
):
    if not check_permission(UserPermission.ITSM_VIEW, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to view service catalog")
    return service_catalog_service.list_service_catalogs(limit=limit)


@router.get("/{service_id}", response_model=dict[str, Any])
async def get_service_catalog(
    service_id: str,
    current_user: CurrentUserDep,
):
    if not check_permission(UserPermission.ITSM_VIEW, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to view service catalog")
    return service_catalog_service.get_service_catalog(service_id)


@router.post("", response_model=dict[str, Any])
async def create_service_catalog(
    payload: ServiceCatalogCreate,
    current_user: CurrentUserDep,
):
    if not check_permission(UserPermission.ITSM_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to manage service catalog")
    return service_catalog_service.create_service_catalog(
        payload,
        actor=current_user.username,
    )


@router.put("/{service_id}", response_model=dict[str, Any])
async def update_service_catalog(
    service_id: str,
    payload: dict[str, Any],
    current_user: CurrentUserDep,
):
    if not check_permission(UserPermission.ITSM_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to update service catalog")
    return service_catalog_service.update_service_catalog(
        service_id,
        payload,
        actor=current_user.username,
    )


@router.post("/{service_id}/deactivate", response_model=dict[str, Any])
async def deactivate_service_catalog(
    service_id: str,
    current_user: CurrentUserDep,
):
    if not check_permission(UserPermission.ITSM_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to deactivate service catalog")
    return service_catalog_service.deactivate_service_catalog(
        service_id,
        actor=current_user.username,
    )
