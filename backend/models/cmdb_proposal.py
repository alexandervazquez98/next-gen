"""Pydantic models for the CMDB AI proposal lifecycle — feat-cmdb-ai-handoff.

The capability is split across two pieces:

- ``CIProposalStatus`` — string enum mirroring the lifecycle states.
- ``ManifestPayload`` — the JSON document an AI agent submits to propose a CI.

Validation rules mirror REQ-CMAP-001 and REQ-CMAP-013:
- ``schema_version`` must be 1.
- ``ci.id``, ``ci.label``, ``ci.category`` are required.
- ``ci.metadata`` keys MUST NOT collide with ``BLOCKED_AI_UPDATE_FIELDS``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from models.core import Node
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CIProposalStatus(StrEnum):
    """Lifecycle states for a :CIProposal node.

    Mirrors the precedent set by ``MqttMetricMapping`` (DRAFT/APPROVED/REVOKED).
    """

    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"


# feat-cmdb-ai-handoff: relocated from ``services.node_service`` so the AI-safe
# field allow-list is owned by the data model, not the service. Service-level
# callers continue to work via re-export.
BLOCKED_AI_UPDATE_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "label",
        "type",
        "brand",
        "model",
        "serialNumber",
        "firmwareVersion",
        "ip",
        "snmp",
        "location",
    }
)


class ManifestPayload(BaseModel):
    """The structured manifest an AI agent submits to propose a new CI.

    ``schema_version`` MUST be 1 (REQ-CMAP-001). The ``ci`` block mirrors the
    ``Node`` shape and reuses its Pydantic validation (incl. ``public_ip``).

    The ``ci`` field accepts ``category`` as a friendlier alias for the Node's
    required ``type`` string — the catalog already keys by ``category`` name
    (``backend/services/catalog_service.get_categories``), so requiring agents
    to repeat themselves as ``type`` would be friction.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    schema_version: int = Field(default=1, ge=1)
    ci: Node
    rationale: str = Field(default="", max_length=1024)
    source_refs: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError(f"unsupported schema_version {value}; the only known version is 1")
        return value

    @model_validator(mode="before")
    @classmethod
    def _coerce_category_to_type(cls, data: Any) -> Any:
        """Map ``ci.category`` → ``ci.type`` so the manifest can use the catalog term.

        ``Node.type`` is the required field on the underlying Pydantic model; the
        spec uses ``category`` for readability against the live Category catalog.
        We copy without deleting so downstream auditors can still see what the
        agent submitted.
        """
        if isinstance(data, dict) and isinstance(data.get("ci"), dict):
            ci = dict(data["ci"])
            if "type" not in ci and "category" in ci:
                ci["type"] = ci["category"]
            data = {**data, "ci": ci}
        return data

    @model_validator(mode="after")
    def _reject_blocked_metadata_keys(self) -> ManifestPayload:
        metadata = self.ci.metadata or {}
        blocked = [k for k in metadata if k in BLOCKED_AI_UPDATE_FIELDS]
        if blocked:
            raise ValueError(f"metadata must not contain blocked AI fields keys: {blocked}")
        return self


__all__ = [
    "BLOCKED_AI_UPDATE_FIELDS",
    "CIProposalStatus",
    "ManifestPayload",
]


def _ensure_node_alias(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Forward-compat helper: pass-through (kept for potential future use)."""
    return metadata or {}
