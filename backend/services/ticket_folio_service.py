"""Service orchestration for ITSM Ticket/Folio lifecycle.

This service layer validates lifecycle transitions and ensures compatibility
constraints (status progressions, archive semantics, and catalog reference
checks) before persistence.
"""

from __future__ import annotations

from fastapi import HTTPException
from models.itsm import (
    TicketFolioCreate,
    TicketFolioUpdate,
    validate_ticket_transition,
)
from pydantic import ValidationError
from repositories.itsm_service_catalog_repo import ServiceCatalogRepository
from repositories.ticket_folio_repo import TicketFolioRepository


def _to_ticket_create(payload) -> TicketFolioCreate:
    return payload if isinstance(payload, TicketFolioCreate) else TicketFolioCreate(**payload)


def _to_ticket_update(payload) -> TicketFolioUpdate:
    return payload if isinstance(payload, TicketFolioUpdate) else TicketFolioUpdate(**payload)


def _raise_bad_request(message: str) -> None:
    raise HTTPException(status_code=400, detail=message)


def _raise_not_found(message: str) -> None:
    raise HTTPException(status_code=404, detail=message)


def _raise_conflict(message: str) -> None:
    raise HTTPException(status_code=409, detail=message)


def _check_catalog_exists(
    service_catalog_id: str | None,
    *,
    catalog_repository: ServiceCatalogRepository | None = None,
) -> None:
    if not service_catalog_id:
        return

    catalog_repository = catalog_repository or ServiceCatalogRepository()
    catalog = catalog_repository.get_by_id(service_catalog_id)
    if not catalog:
        _raise_not_found(f"service_catalog not found: {service_catalog_id}")


def _sync_relation(
    ticket_id: str, service_catalog_id: str | None, repository: TicketFolioRepository
) -> None:
    # Keep property and relationship in sync for migration compatibility.
    repository.sync_service_relationship(ticket_id, service_catalog_id)


def list_ticket_folios(
    *,
    status: str | None = None,
    service_catalog_id: str | None = None,
    archived: bool | None = None,
    limit: int = 100,
    repository: TicketFolioRepository | None = None,
):
    repository = repository or TicketFolioRepository()
    return repository.list(
        status=status, service_catalog_id=service_catalog_id, archived=archived, limit=limit
    )


def get_ticket_folio(
    ticket_id: str,
    *,
    repository: TicketFolioRepository | None = None,
):
    repository = repository or TicketFolioRepository()
    record = repository.get(ticket_id)
    if not record:
        _raise_not_found(f"Ticket folio not found: {ticket_id}")
    return record


def create_ticket_folio(
    payload,
    *,
    actor: str | None = None,
    repository: TicketFolioRepository | None = None,
    catalog_repository: ServiceCatalogRepository | None = None,
):
    repository = repository or TicketFolioRepository()

    try:
        payload_model = _to_ticket_create(payload)
    except ValidationError as exc:
        _raise_bad_request(str(exc))

    _check_catalog_exists(payload_model.service_catalog_id, catalog_repository=catalog_repository)

    payload_model = payload_model.model_copy(update={"updated_by": actor})
    created = repository.upsert(payload_model)

    # Keep legacy relationship up to date for read compatibility; property is
    # authoritative.
    _sync_relation(created["ticket_id"], created.get("service_catalog_id"), repository)
    return created


def update_ticket_folio(
    ticket_id: str,
    payload,
    *,
    actor: str | None = None,
    repository: TicketFolioRepository | None = None,
    catalog_repository: ServiceCatalogRepository | None = None,
):
    repository = repository or TicketFolioRepository()

    current = repository.get(ticket_id)
    if not current:
        _raise_not_found(f"Ticket folio not found: {ticket_id}")

    try:
        update_model = _to_ticket_update(payload)
    except ValidationError as exc:
        _raise_bad_request(str(exc))

    updates = update_model.model_dump(exclude_unset=True)
    if not updates:
        return current

    if current.get("status") == "closed":
        _raise_conflict("Closed ticket folios are read-only")

    if "archived" in updates and updates.get("status") != "closed":
        _raise_conflict("archived can only be changed by transitioning to closed")

    next_status = updates.get("status")
    if next_status is not None:
        try:
            validate_ticket_transition(current["status"], next_status)
        except ValueError as exc:
            _raise_conflict(str(exc))

        if next_status == "closed" and not updates.get("closed_reason"):
            _raise_bad_request("closed_reason is required when transitioning to closed")

    has_service_catalog_update = "service_catalog_id" in updates
    new_service_catalog_id = updates.get("service_catalog_id")
    if has_service_catalog_update:
        _check_catalog_exists(new_service_catalog_id, catalog_repository=catalog_repository)

    normalized_updates = {**updates, "updated_by": actor}
    if next_status == "closed":
        normalized_updates["archived"] = True

    updated = repository.update(ticket_id, _to_ticket_update(normalized_updates))
    if has_service_catalog_update:
        _sync_relation(ticket_id, new_service_catalog_id, repository)

    return updated


def transition_ticket_folio(
    ticket_id: str,
    *,
    next_status: str,
    closed_reason: str | None = None,
    actor: str | None = None,
    repository: TicketFolioRepository | None = None,
    catalog_repository: ServiceCatalogRepository | None = None,
):
    """Explicit transition endpoint facade with the same validation pipeline as update."""

    payload = {"status": next_status}
    if closed_reason is not None:
        payload["closed_reason"] = closed_reason
    return update_ticket_folio(
        ticket_id,
        payload,
        actor=actor,
        repository=repository,
        catalog_repository=catalog_repository,
    )
