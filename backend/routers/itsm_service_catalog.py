"""Routers for ITSM service catalog domain.

These endpoints are intentionally isolated from event workflows.
They only manage Service Catalog state via the ITSM API slice and do
not mutate or trigger event/folio side effects.
"""

from __future__ import annotations

from typing import Annotated, Any

import services.itsm_service_catalog_service as service_catalog_service
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from models.itsm import ServiceCatalogCreate, ServiceCatalogUpdate
from models.user import User, UserPermission
from services.auth_service import check_permission, get_current_active_user
from services.itsm_imports import catalog_import
from services.itsm_imports.value_stream_lookup import MetricDictionaryValueStreamLookup

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
    payload: ServiceCatalogUpdate,
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


# ---------------------------------------------------------------------------
# PR 4 — WU 6 atomic XLSX catalog import.
# ---------------------------------------------------------------------------


@router.get("/template")
async def get_catalog_template(
    current_user: CurrentUserDep,
) -> Response:
    if not check_permission(UserPermission.ITSM_VIEW, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to view service catalog")
    workbook_bytes = catalog_import.build_catalog_template_workbook(
        value_stream_lookup=MetricDictionaryValueStreamLookup()
    )
    return Response(
        content=workbook_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=catalog_import_template.xlsx"},
    )


@router.post("/import")
async def import_catalog_workbook(
    file: UploadFile = File(...),
    current_user: CurrentUserDep = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    if not check_permission(UserPermission.ITSM_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to import service catalog")
    payload = await file.read()
    try:
        return catalog_import.import_catalog_workbook(
            payload,
            actor=current_user.username,
            repository=ServiceCatalogRepository(),
            value_stream_lookup=MetricDictionaryValueStreamLookup(),
        )
    except Exception as exc:  # noqa: BLE001 — surface structured errors to the client
        from fastapi import HTTPException
        from services.itsm_imports.errors import ImportValidationError

        if isinstance(exc, ImportValidationError):
            raise HTTPException(status_code=400, detail=exc.to_payload())
        raise
