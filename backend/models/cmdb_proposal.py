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
from typing import Any, Literal

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

    feat-489 Slice 1B: the manifest can also carry ``cis: list[Node]`` for
    bulk submissions (admin CSV import). When ``cis`` is non-empty the
    ``mode`` is set to ``"bulk"`` and ``ci`` must be omitted; vice-versa for
    single-CI submissions. The repo stores the manifest opaquely so older
    rows keep working unchanged.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    schema_version: int = Field(default=1, ge=1)
    ci: Node | None = None
    cis: list[Node] | None = None
    mode: Literal["single", "bulk"] = "single"
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
        """Map ``ci.category`` / ``cis[*].category`` → ``.type`` so the
        manifest can use the catalog term.

        ``Node.type`` is the required field on the underlying Pydantic model; the
        spec uses ``category`` for readability against the live Category catalog.
        We copy without deleting so downstream auditors can still see what the
        agent submitted.
        """
        if not isinstance(data, dict):
            return data
        if isinstance(data.get("ci"), dict):
            ci = dict(data["ci"])
            if "type" not in ci and "category" in ci:
                ci["type"] = ci["category"]
            data = {**data, "ci": ci}
        if isinstance(data.get("cis"), list):
            coerced = []
            for entry in data["cis"]:
                if isinstance(entry, dict):
                    entry = dict(entry)
                    if "type" not in entry and "category" in entry:
                        entry["type"] = entry["category"]
                    coerced.append(entry)
                else:
                    coerced.append(entry)
            data = {**data, "cis": coerced}
        return data

    @model_validator(mode="after")
    def _enforce_single_or_bulk_invariant(self) -> ManifestPayload:
        """Exactly one of ``ci`` / ``cis`` must be set; ``mode`` must match.

        feat-489 Slice 1B: bulk manifest requires ``cis`` to be non-empty;
        single-CI manifest requires ``ci`` to be set. ``mode`` must align.
        Blocked AI metadata keys are rejected on every CI in the bulk array.
        """
        has_ci = self.ci is not None
        has_cis = self.cis is not None and len(self.cis) > 0
        if has_ci and has_cis:
            raise ValueError(
                "manifest must set either 'ci' (single) or 'cis' (bulk), not both"
            )
        if not has_ci and not has_cis:
            raise ValueError("manifest must set either 'ci' (single) or 'cis' (bulk)")
        if has_cis:
            if self.mode != "bulk":
                raise ValueError(
                    f"manifest has cis[] but mode={self.mode!r}; expected 'bulk'"
                )
            for idx, ci in enumerate(self.cis or []):
                metadata = ci.metadata or {}
                blocked = [k for k in metadata if k in BLOCKED_AI_UPDATE_FIELDS]
                if blocked:
                    raise ValueError(
                        f"cis[{idx}].metadata must not contain blocked AI fields keys: {blocked}"
                    )
        else:
            if self.mode != "single":
                raise ValueError(
                    f"manifest has ci (single) but mode={self.mode!r}; expected 'single'"
                )
            metadata = (self.ci.metadata if self.ci else {}) or {}
            blocked = [k for k in metadata if k in BLOCKED_AI_UPDATE_FIELDS]
            if blocked:
                raise ValueError(
                    f"metadata must not contain blocked AI fields keys: {blocked}"
                )
        return self


__all__ = [
    "BLOCKED_AI_UPDATE_FIELDS",
    "CIProposalStatus",
    "ManifestPayload",
]


def _ensure_node_alias(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Forward-compat helper: pass-through (kept for potential future use)."""
    return metadata or {}
