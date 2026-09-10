"""Pydantic v2 DTOs for the CMDB LOD endpoints (REQ-1..9).

These DTOs pin the wire shape for ``GET /graph/overview`` and
``GET /graph/detail/{cluster_id}``. They MUST mirror the TypeScript types
in ``frontend/types/graph.ts`` exactly (parity gate in
``frontend/__tests__/parity.test.ts``).

Sensitive-field policy (REQ-9):

- Overview responses NEVER include ``public_ip``, raw ``metadata``, exact
  geo coordinates, serial numbers, provider account identifiers.
- Detail responses apply the existing ``/graph/full`` projection helper
  (impl in #391).
- ``show_sensitive_metadata`` defaults to ``False``; ``True`` requires BOTH
  the ``graph:aggregate_breakdown:read`` permission AND the caller
  explicitly requested it (``?sensitive=include``).

No IO. No FastAPI dependency — these are pure data shapes.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.aggregate_policy import (
    DEFAULT_MINIMUM_COUNT,
    PERMISSION_REQUIRED,
    SafeGeoPrecision,
)
from contracts.projection import SensitiveSource


# ---------------------------------------------------------------------------
# Re-export for downstream callers
# ---------------------------------------------------------------------------

__all__ = [
    "AggregatePolicy",
    "BoundaryStub",
    "DetailCluster",
    "DetailLink",
    "DetailNode",
    "DetailResponse",
    "EmptyReason",
    "InterClusterLink",
    "Legend",
    "OverviewCluster",
    "OverviewResponse",
    "Page",
    "ProjectionFlags",
    "SafeGeoPrecision",
    "SearchVocabulary",
    "SensitiveSource",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AXIS_LOCATION: Literal["location"] = "location"
PAGE_SIZE_DEFAULT = 100  # Spec overview paging engages when >100 visible clusters
DETAIL_LIMIT_DEFAULT = 500
DETAIL_LIMIT_MIN = 1
DETAIL_LIMIT_MAX = 1000


# ---------------------------------------------------------------------------
# Enums (mirrored as TS string-literal unions)
# ---------------------------------------------------------------------------


class EmptyReason:
    """Empty-result reason for detail responses (REQ-7).

    Values: ``none | no_visible_members | hidden_absent | unavailable``.
    Mirrored on the frontend as a TS string-literal union.
    """

    NONE = "none"
    NO_VISIBLE_MEMBERS = "no_visible_members"
    HIDDEN_ABSENT = "hidden_absent"
    UNAVAILABLE = "unavailable"

    @classmethod
    def values(cls) -> list[str]:
        return [cls.NONE, cls.NO_VISIBLE_MEMBERS, cls.HIDDEN_ABSENT, cls.UNAVAILABLE]


# Pydantic v2: use a Literal type so we get a clean enum-on-the-wire.
EmptyReasonLiteral = Literal["none", "no_visible_members", "hidden_absent", "unavailable"]


class SearchVocabulary:
    """Server-authoritative search resolution vocabulary (REQ-8).

    Values:
        - ``single_visible_cluster`` — fetch detail for the single match
        - ``multiple_visible_clusters`` — require operator selection
        - ``no_visible_cluster`` — empty overview / search state
        - ``ambiguous`` — require refinement or visible-cluster selection
    """

    SINGLE = "single_visible_cluster"
    MULTIPLE = "multiple_visible_clusters"
    NONE = "no_visible_cluster"
    AMBIGUOUS = "ambiguous"

    @classmethod
    def values(cls) -> list[str]:
        return [cls.SINGLE, cls.MULTIPLE, cls.NONE, cls.AMBIGUOUS]


# ---------------------------------------------------------------------------
# Shared base — model_config: serialize by alias, validate on assignment
# ---------------------------------------------------------------------------


def _strict_model() -> ConfigDict:
    return ConfigDict(
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
        use_enum_values=False,
    )


# ---------------------------------------------------------------------------
# Overview response DTOs (REQ-1)
# ---------------------------------------------------------------------------


class AggregatePolicyDTO(BaseModel):
    """Wire shape for ``overview.aggregate_policy``."""

    model_config = _strict_model()

    minimum_count: Annotated[int, Field(ge=1)] = DEFAULT_MINIMUM_COUNT
    permission_required: str = PERMISSION_REQUIRED
    safe_geo_precision: SafeGeoPrecision = SafeGeoPrecision.NONE


class Page(BaseModel):
    """Pagination block — appears on overview and detail responses."""

    model_config = _strict_model()

    next_cursor: str | None = None
    has_more: bool = False


class OverviewCluster(BaseModel):
    """A single visible cluster row in the overview payload."""

    model_config = _strict_model()

    cluster_id: str
    display_label: str
    visible_node_count: int = 0
    visible_link_count: int = 0
    aggregate_redacted: bool = False
    suppression_reason: str | None = None


class InterClusterLink(BaseModel):
    """An aggregate edge between two visible clusters."""

    model_config = _strict_model()

    from_cluster_id: str
    to_cluster_id: str
    visible_link_count: int = 0
    redacted: bool = False


class Legend(BaseModel):
    """Safe summary cards metadata (no per-node data)."""

    model_config = _strict_model()

    cards: list[str] = Field(default_factory=list)


class OverviewResponse(BaseModel):
    """Wire shape for ``GET /graph/overview``."""

    model_config = _strict_model()

    axis: Literal["location"] = AXIS_LOCATION
    filters: dict = Field(default_factory=dict)
    generated_at: str
    revision: str
    aggregate_policy: AggregatePolicyDTO = Field(default_factory=AggregatePolicyDTO)
    clusters: list[OverviewCluster] = Field(default_factory=list)
    inter_cluster_links: list[InterClusterLink] = Field(default_factory=list)
    legend: Legend = Field(default_factory=Legend)
    page: Page = Field(default_factory=Page)


# ---------------------------------------------------------------------------
# Detail response DTOs (REQ-2)
# ---------------------------------------------------------------------------


class DetailCluster(BaseModel):
    """The cluster block on a detail response. Nullable for hidden/absent."""

    model_config = _strict_model()

    cluster_id: str
    axis: Literal["location"] = AXIS_LOCATION
    display_label: str
    visible_node_count: int = 0
    visible_link_count: int = 0


class DetailNode(BaseModel):
    """A single node on a detail response.

    Sensitive fields (public_ip, metadata, geo, serial, provider_account) are
    NEVER present here — see the projection policy (impl in #391).
    """

    model_config = _strict_model()

    id: str
    display_label: str
    kind: str
    ci_type: str
    allowed_public_axes: list[str] = Field(default_factory=list)


class DetailLink(BaseModel):
    """A single link on a detail response.

    No fields beyond what ``/graph/full`` already returns.
    """

    model_config = _strict_model()

    source_node_id: str
    target_node_id: str
    relationship: str


class BoundaryStub(BaseModel):
    """A stub representing an adjacent cluster's visible boundary links.

    ``visible_link_count`` is the count of boundary links AS VISIBLE TO THE
    CALLER. Hidden-adjacent stubs are NEVER emitted. Below ``minimum_count``
    -> ``{redacted: true, redaction_reason: "low_cardinality"}`` (applied
    by #391 runtime; the field names are part of this contract).
    """

    model_config = _strict_model()

    cluster_id: str
    visible_link_count: int
    redacted: bool = False
    redaction_reason: str | None = None


class ProjectionFlags(BaseModel):
    """Projection policy metadata exposed on the detail response."""

    model_config = _strict_model()

    show_sensitive_metadata: bool = False  # ALWAYS False by default (REQ-9)
    sensitive_source: SensitiveSource = SensitiveSource.NEVER


class DetailResponse(BaseModel):
    """Wire shape for ``GET /graph/detail/{cluster_id}``."""

    model_config = _strict_model()

    cluster: DetailCluster | None = None  # Null for hidden/absent (REQ-7)
    filters: dict = Field(default_factory=dict)
    generated_at: str
    revision: str
    nodes: list[DetailNode] = Field(default_factory=list)
    links: list[DetailLink] = Field(default_factory=list)
    boundary_stubs: list[BoundaryStub] = Field(default_factory=list)
    projection_flags: ProjectionFlags = Field(default_factory=ProjectionFlags)
    empty_reason: EmptyReasonLiteral = "none"
    page: Page = Field(default_factory=Page)


# ---------------------------------------------------------------------------
# Backwards-compatible re-exports
# ---------------------------------------------------------------------------

# Aliases used by tests and downstream callers.
AggregatePolicy = AggregatePolicyDTO
