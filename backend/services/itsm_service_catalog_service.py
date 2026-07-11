"""Service orchestration for ITSM service catalog nodes.

The service layer normalizes input models, enforces read/write guard rails,
handles partial-update safety, and delegates persistence to the repository.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from models.itsm import ServiceCatalogCreate, ServiceCatalogUpdate
from pydantic import ValidationError
from repositories.itsm_service_catalog_repo import ServiceCatalogRepository, ValueStreamLookup


def _to_catalog_create(payload: Any) -> ServiceCatalogCreate:
    return payload if isinstance(payload, ServiceCatalogCreate) else ServiceCatalogCreate(**payload)


def _to_catalog_update(payload: Any) -> ServiceCatalogUpdate:
    return payload if isinstance(payload, ServiceCatalogUpdate) else ServiceCatalogUpdate(**payload)


def _http_bad_request(message: str) -> None:
    raise HTTPException(status_code=400, detail=message)


def _http_not_found(service_id: str) -> None:
    raise HTTPException(status_code=404, detail=f"Service catalog not found: {service_id}")


def _validate_value_stream(value_stream: str, lookup: ValueStreamLookup) -> None:
    if not lookup.is_active(value_stream):
        _http_bad_request(f"value_stream must reference an active value stream: {value_stream}")


def _validate_unique_catalog(
    payload: ServiceCatalogCreate,
    repository: ServiceCatalogRepository,
    *,
    exclude_service_id: str | None = None,
) -> None:
    existing = repository.get_by_id(payload.service_id)
    if isinstance(existing, dict) and payload.service_id != exclude_service_id:
        _http_bad_request(f"service_id already exists: {payload.service_id}")
    finder = getattr(repository, "find_by_type_and_normalized_name", None)
    conflict = finder(
        payload.service_type,
        payload.name,
        exclude_service_id=exclude_service_id,
    ) if finder else None
    if isinstance(conflict, dict):
        _http_bad_request("name must be unique within service_type")


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
    value_stream_lookup: ValueStreamLookup | None = None,
):
    """Create a governed service catalog entry.

    This endpoint is idempotent from repository perspective because WU1 uses
    MERGE. We still keep strict validation and normalize actor metadata here.
    """

    repository = repository or ServiceCatalogRepository()
    value_stream_lookup = value_stream_lookup or ValueStreamLookup()
    try:
        payload_model = _to_catalog_create(payload).model_copy(update={"updated_by": actor})
    except ValidationError as exc:
        _http_bad_request(str(exc))

    _validate_value_stream(payload_model.value_stream, value_stream_lookup)
    _validate_unique_catalog(payload_model, repository)
    return repository.upsert(payload_model)


def update_service_catalog(
    service_id: str,
    payload: Any,
    *,
    actor: str | None = None,
    repository: ServiceCatalogRepository | None = None,
    value_stream_lookup: ValueStreamLookup | None = None,
):
    """Apply partial updates to one governed service catalog.

    Partial updates with no mutable fields return the current record without
    writing (zero side-effects policy).
    """

    repository = repository or ServiceCatalogRepository()
    value_stream_lookup = value_stream_lookup or ValueStreamLookup()
    current = repository.get_by_id(service_id)
    if not current:
        _http_not_found(service_id)

    try:
        update_model = _to_catalog_update(payload)
    except ValidationError as exc:
        _http_bad_request(str(exc))

    update_values = update_model.model_dump(exclude_unset=True)

    if "service_type" in update_values:
        if update_values["service_type"] != current.get("service_type"):
            _http_bad_request("service_type is immutable after catalog creation")
        # An unchanged immutable field is accepted, but must not reach the
        # repository's mutation guard alongside mutable updates.
        update_values.pop("service_type")
        update_model = ServiceCatalogUpdate(**update_values)

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

    if "value_stream" in update_values:
        _validate_value_stream(update_values["value_stream"], value_stream_lookup)
    if "name" in update_values:
        finder = getattr(repository, "find_by_type_and_normalized_name", None)
        conflict = finder(
            current["service_type"], update_values["name"], exclude_service_id=service_id
        ) if finder else None
        if isinstance(conflict, dict):
            _http_bad_request("name must be unique within service_type")

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
