"""ITSM domain models and lifecycle helpers.

This module defines schema objects for Service Catalog and Ticket/Folio with
explicit backward-compatible aliases for the existing event domain shape:

- ``id`` ↔ ``service_id``
- ``service_tier`` ↔ ``tier``
- ``sla_minutes`` ↔ ``sla_target_minutes``

The schemas keep migration/runtime compatibility while moving to
English-named canonical fields.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

ServiceCatalogId = str
TicketId = int


TICKET_STATUS_ORDER = (
    "open",
    "in_progress",
    "in_validation",
    "resolved",
    "closed",
)


class TicketStatus:
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    IN_VALIDATION = "in_validation"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketFolioType:
    INCIDENT = "incident"
    SERVICE_REQUEST = "service_request"


class ServiceCatalogCreate(BaseModel):
    """Input contract for creating ServiceCatalog-like records.

    Canonical fields are English-native names; the legacy aliases are synchronized
    so both event and inventory-style call sites remain readable during the
    migration.
    """

    service_id: str
    name: str
    owner_team: str | None = None
    category: str | None = None
    tier: str | None = None
    criticality: str | None = None
    sla_target_minutes: int = Field(..., ge=0)
    description: str
    service_type: str
    value_stream: str
    active: bool = True
    updated_by: str | None = None

    # Backward-compatible aliases (kept explicit for migration safety).
    id: str | None = None
    service_tier: str | None = None
    sla_minutes: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("service_id")
    @classmethod
    def _validate_service_id(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("service_id cannot be empty")
        return value

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("name cannot be empty")
        return value.strip()

    @field_validator("description", "value_stream")
    @classmethod
    def _validate_required_text(cls, value: str, info) -> str:
        if not str(value).strip():
            raise ValueError(f"{info.field_name} cannot be empty")
        return value.strip()

    @field_validator("sla_target_minutes")
    @classmethod
    def _validate_sla_target_minutes(cls, value: int) -> int:
        if value < 0:
            raise ValueError("sla_target_minutes must be >= 0")
        return value

    @field_validator("service_type")
    @classmethod
    def _validate_service_type(cls, value: str) -> str:
        if value not in (TicketFolioType.INCIDENT, TicketFolioType.SERVICE_REQUEST):
            raise ValueError("service_type must be either 'incident' or 'service_request'")
        return value

    @field_validator("sla_minutes")
    @classmethod
    def _validate_legacy_sla_minutes(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value < 0:
            raise ValueError("sla_minutes must be >= 0")
        return value

    @model_validator(mode="before")
    @classmethod
    def _normalize_compatibility_aliases(cls, values: Any) -> Any:
        values = dict(values)

        if "service_id" not in values or values.get("service_id") is None:
            legacy_service_id = values.get("id")
            if legacy_service_id:
                values["service_id"] = legacy_service_id

        if values.get("service_id") is None and values.get("id") is None:
            raise ValueError("service_id is required (or legacy id as fallback).")

        if values.get("id") is None:
            values["id"] = values.get("service_id")
        elif values.get("service_id") != values.get("id"):
            raise ValueError("service_id and id must match when both are provided.")

        if values.get("service_tier") is not None and values.get("tier") is None:
            values["tier"] = values.get("service_tier")
        elif (
            values.get("service_tier") is not None
            and values.get("tier") is not None
            and values.get("service_tier") != values.get("tier")
        ):
            raise ValueError("service_tier and tier must match when both are provided.")

        if values.get("sla_minutes") is not None:
            if values.get("sla_target_minutes") is None:
                values["sla_target_minutes"] = values["sla_minutes"]
            elif values["sla_target_minutes"] != values["sla_minutes"]:
                raise ValueError(
                    "sla_target_minutes and sla_minutes must match when both are provided."
                )

        return values

    @model_validator(mode="after")
    def _sync_legacy_aliases(self):
        if self.service_id:
            self.id = self.id or self.service_id
        if self.tier:
            self.service_tier = self.service_tier or self.tier
        if self.sla_target_minutes is not None:
            self.sla_minutes = self.sla_target_minutes
        if self.created_at is None:
            self.created_at = datetime.utcnow().replace(microsecond=0).isoformat()
        if self.updated_at is None:
            self.updated_at = datetime.utcnow().replace(microsecond=0).isoformat()
        return self


class ServiceCatalogUpdate(BaseModel):
    """Update payload for ServiceCatalog records."""

    service_id: str | None = None
    name: str | None = None
    owner_team: str | None = None
    category: str | None = None
    tier: str | None = None
    criticality: str | None = None
    sla_target_minutes: int | None = None
    description: str | None = None
    service_type: str | None = None
    value_stream: str | None = None
    active: bool | None = None
    updated_by: str | None = None

    # Backward-compatible aliases (kept explicit for compatibility-safe updates).
    id: str | None = None
    service_tier: str | None = None
    sla_minutes: int | None = None

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("description cannot be empty")
        return value.strip()

    @field_validator("sla_target_minutes")
    @classmethod
    def _validate_sla_target_minutes(cls, value: int | None) -> int:
        if value is None or value < 0:
            raise ValueError("sla_target_minutes must be non-null and >= 0")
        return value

    @field_validator("sla_minutes")
    @classmethod
    def _validate_legacy_sla_minutes(cls, value: int | None) -> int:
        if value is None or value < 0:
            raise ValueError("sla_minutes must be non-null and >= 0")
        return value

    @model_validator(mode="before")
    @classmethod
    def _normalize_compatibility_aliases(cls, values: Any) -> Any:
        values = dict(values)

        if values.get("service_id") is None and values.get("id") is not None:
            values["service_id"] = values["id"]

        if values.get("service_tier") is not None and values.get("tier") is None:
            values["tier"] = values.get("service_tier")
        elif (
            values.get("service_tier") is not None
            and values.get("tier") is not None
            and values["service_tier"] != values["tier"]
        ):
            raise ValueError("service_tier and tier must match when both are provided.")

        if values.get("sla_minutes") is not None and values.get("sla_target_minutes") is None:
            values["sla_target_minutes"] = values["sla_minutes"]
        elif (
            values.get("sla_minutes") is not None
            and values.get("sla_target_minutes") is not None
            and values["sla_minutes"] != values["sla_target_minutes"]
        ):
            raise ValueError(
                "sla_target_minutes and sla_minutes must match when both are provided."
            )

        return values

    @model_validator(mode="after")
    def _sync_aliases(self):
        if self.id is None and self.service_id is not None:
            self.id = self.service_id
        if self.service_tier is None and self.tier is not None:
            self.service_tier = self.tier
        if self.sla_target_minutes is not None:
            self.sla_minutes = self.sla_target_minutes
        return self


    @field_validator("service_type")
    @classmethod
    def _validate_service_type(cls, value: str) -> str:
        if value not in (TicketFolioType.INCIDENT, TicketFolioType.SERVICE_REQUEST):
            raise ValueError("service_type must be either 'incident' or 'service_request'")
        return value


class ServiceCatalogResponse(ServiceCatalogCreate):
    """Response contract for ServiceCatalog domain reads."""

    service_id: str


class TicketFolioCreate(BaseModel):
    """Input contract for creating a ticket; the server allocates its ID."""

    model_config = {"extra": "forbid"}

    type: str
    title: str
    description: str | None = None
    service_catalog_id: str
    status: str = TicketStatus.OPEN
    archived: bool = False
    closed_reason: str | None = None
    updated_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        if value not in (TicketFolioType.INCIDENT, TicketFolioType.SERVICE_REQUEST):
            raise ValueError("type must be either 'incident' or 'service_request'")
        return value

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("title cannot be empty")
        return value

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        if value not in TICKET_STATUS_ORDER:
            raise ValueError(f"invalid status '{value}'")
        return value

    @model_validator(mode="after")
    def _normalize_defaults(self):
        if self.status != TicketStatus.OPEN:
            raise ValueError("New folios must start as 'open'")
        return self


class TicketFolioResponse(BaseModel):
    """Response contract exposing the server-generated numeric ticket ID."""

    ticket_id: int
    type: str
    title: str
    description: str | None = None
    service_catalog_id: str | None = None
    status: str = TicketStatus.OPEN
    archived: bool = False
    closed_reason: str | None = None
    updated_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        if value not in (TicketFolioType.INCIDENT, TicketFolioType.SERVICE_REQUEST):
            raise ValueError("type must be either 'incident' or 'service_request'")
        return value


class TicketFolioUpdate(BaseModel):
    """Update payload for ticket/folio logical lifecycle operations."""

    title: str | None = None
    description: str | None = None
    service_catalog_id: str | None = None
    status: str | None = None
    archived: bool | None = None
    closed_reason: str | None = None
    updated_by: str | None = None

    @field_validator("title")
    @classmethod
    def _validate_update_title(cls, value: str | None) -> str | None:
        if value is not None and not str(value).strip():
            raise ValueError("title cannot be empty")
        return value

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in TICKET_STATUS_ORDER:
            raise ValueError(f"invalid status '{value}'")
        return value


class TicketFolioUpdateArchive(BaseModel):
    """Convenience schema for explicit archive transition inputs."""

    archived: bool
    closed_reason: str | None = None


def validate_ticket_transition(current_status: str, next_status: str) -> bool:
    """Validate a single ticket lifecycle transition.

    Returns:
        True when the transition is valid.

    Raises:
        ValueError when invalid.
    """

    if current_status not in TICKET_STATUS_ORDER:
        raise ValueError(f"Invalid current status '{current_status}'")
    if next_status not in TICKET_STATUS_ORDER:
        raise ValueError(f"Invalid next status '{next_status}'")
    if current_status == next_status:
        raise ValueError("Ticket status transition to same state is not allowed")

    current_idx = TICKET_STATUS_ORDER.index(current_status)
    next_idx = TICKET_STATUS_ORDER.index(next_status)

    if current_status == TicketStatus.CLOSED:
        raise ValueError("Closed folios cannot transition to another state")

    if next_idx != current_idx + 1:
        raise ValueError("Invalid ticket status transition. Expected strict forward linear steps.")

    return True
