"""Service orchestration for ITSM service catalog nodes.

The service layer normalizes input models, enforces read/write guard rails,
handles partial-update safety, and delegates persistence to the repository.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from models.itsm import ServiceCatalogCreate, ServiceCatalogUpdate
from pydantic import ValidationError
from repositories.itsm_service_catalog_repo import ServiceCatalogRepository


def _to_catalog_create(payload: Any) -> ServiceCatalogCreate:
    return payload if isinstance(payload, ServiceCatalogCreate) else ServiceCatalogCreate(**payload)


def _to_catalog_update(payload: Any) -> ServiceCatalogUpdate:
    return payload if isinstance(payload, ServiceCatalogUpdate) else ServiceCatalogUpdate(**payload)


def _http_bad_request(message: str) -> None:
    raise HTTPException(status_code=400, detail=message)


def _http_not_found(service_id: str) -> None:
    raise HTTPException(status_code=404, detail=f"Service catalog not found: {service_id}")


def list_service_catalogs(*, limit: int = 100, repository: ServiceCatalogRepository | None = None):
    """Return a bounded page of service catalog nodes."""

    repository = repository or ServiceCatalogRepository()
    return repository.list(limit=limit)


def get_service_catalog(service_id: str, *, repository: ServiceCatalogRepository | None = None):
    """Fetch one service catalog by its canonical id."""

    repository = repository or ServiceCatalogRepository()
    record = repository.get_by_id(service_id)
    if not record:
        _http_not_found(service_id)
    return record


def create_service_catalog(
    payload: Any,
    *,
    actor: str | None = None,
    repository: ServiceCatalogRepository | None = None,
):
    """Create or upsert a service catalog entry.

    This endpoint is idempotent from repository perspective because WU1 uses
    MERGE. We still keep strict validation and normalize actor metadata here.
    """

    repository = repository or ServiceCatalogRepository()
    try:
        payload_model = _to_catalog_create(payload).model_copy(update={"updated_by": actor})
    except ValidationError as exc:
        _http_bad_request(str(exc))

    return repository.upsert(payload_model)


def update_service_catalog(
    service_id: str,
    payload: Any,
    *,
    actor: str | None = None,
    repository: ServiceCatalogRepository | None = None,
):
    """Apply partial updates to one service catalog.

    Partial updates with no mutable fields return the current record without
    writing (zero side-effects policy).
    """

    repository = repository or ServiceCatalogRepository()
    current = repository.get_by_id(service_id)
    if not current:
        _http_not_found(service_id)

    try:
        update_model = _to_catalog_update(payload)
    except ValidationError as exc:
        _http_bad_request(str(exc))

    update_values = update_model.model_dump(exclude_unset=True)

    # Authoritative path is service_id in URL.
    path_fields = {"service_id", "id"}
    for key in path_fields:
        if (
            key in update_values
            and update_values[key] is not None
            and update_values[key] != service_id
        ):
            _http_bad_request(f"{key} must match service_id '{service_id}' when provided")

    if not update_values:
        return current

    normalized_payload = update_model.model_copy(
        update={
            "service_id": service_id,
            "id": service_id,
            "updated_by": actor,
        },
    )
    return repository.update(service_id, normalized_payload)


def deactivate_service_catalog(
    service_id: str,
    *,
    actor: str | None = None,
    repository: ServiceCatalogRepository | None = None,
):
    """Soft deactivate a service catalog (logical delete)."""

    repository = repository or ServiceCatalogRepository()
    record = repository.deactivate(service_id, updated_by=actor)
    if not record:
        _http_not_found(service_id)
    return record
