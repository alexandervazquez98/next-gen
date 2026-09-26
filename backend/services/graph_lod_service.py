"""Graph LOD service layer (#391 PR1).

Orchestrates the ``GET /graph/overview`` flow:

1. Resolve principal's visible-set (delegated to the repository's
   pre-aggregation filter — see ``repositories.graph_lod_repo``).
2. Aggregate clusters via the repository.
3. Apply the aggregate policy (REQ-OVERVIEW-2) to derive
   ``SafeGeoPrecision``.
4. Apply the per-user aggregate breakdown scope (permission +
   ``aggregate_breakdown_regions``) for the city tier.
5. Mark low-cardinality clusters as ``aggregate_redacted=True`` with a
   ``suppression_reason`` so the frontend can render the redaction UI.
6. Shape the ``OverviewResponse`` DTO.

Hard rule (REQ-OVERVIEW-3): hidden and absent clusters are externally
indistinguishable. The repository's pre-aggregation filter is the single
source of truth for visibility — the service never inspects the full
graph to "see if a cluster should be hidden".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from contracts.aggregate_policy import (
    DEFAULT_MINIMUM_COUNT,
    PERMISSION_REQUIRED,
    derive_safe_geo_precision,
)
from repositories import graph_lod_repo
from schemas.graph import (
    AggregatePolicyDTO,
    Legend,
    OverviewCluster,
    OverviewResponse,
    Page,
    SafeGeoPrecision,
)

LOW_CARDINALITY_THRESHOLD_MULTIPLIER = 4  # mirrors derive_safe_geo_precision ladder
LOW_CARDINALITY_REASON = "low_cardinality"


def _resolve_visible_set(principal: Any) -> tuple[list[str] | None, bool]:
    """Translate the principal into (allowed_locations, is_admin) for the repo."""
    is_admin = bool(getattr(principal, "is_admin", False))
    if is_admin:
        return None, True
    allowed = list(getattr(principal, "allowed_locations", []) or [])
    return (allowed or None), False


def _has_breakdown_permission(principal: Any) -> bool:
    perms = list(getattr(principal, "permissions", []) or [])
    return PERMISSION_REQUIRED in perms


def _region_in_breakdown_scope(principal: Any, region_label: str) -> bool:
    """Empty list = global breakdown; populated list = scoped membership."""
    regions = list(getattr(principal, "aggregate_breakdown_regions", []) or [])
    if not regions:
        return True
    return region_label in regions


def _derive_safe_geo_precision_for_principal(
    principal: Any,
    visible_count: int,
    minimum_count: int,
) -> str:
    """Combine the aggregate tier ladder with permission + scope resolution.

    Tier ladder (from ``derive_safe_geo_precision``):
        * visible_count < minimum_count     -> 'none'
        * visible_count < minimum_count * 4 -> 'region'
        * otherwise                          -> 'city' (capability required)

    If the principal lacks the capability OR the region is out of scope,
    silently downgrade 'city' to 'region' so the response shape is
    externally indistinguishable.
    """
    base_tier = derive_safe_geo_precision(visible_count, minimum_count)
    if base_tier != SafeGeoPrecision.CITY.value:
        return base_tier
    if not _has_breakdown_permission(principal):
        return SafeGeoPrecision.REGION.value
    return SafeGeoPrecision.CITY.value


def _shape_cluster(
    principal: Any,
    raw: dict[str, Any],
    minimum_count: int,
) -> OverviewCluster:
    visible_node_count = int(raw.get("visible_node_count", 0))
    cluster_id = str(raw["cluster_id"])
    display_label = str(raw.get("display_label") or cluster_id)
    is_low_cardinality = visible_node_count < minimum_count
    return OverviewCluster(
        cluster_id=cluster_id,
        display_label=display_label,
        visible_node_count=visible_node_count,
        visible_link_count=int(raw.get("visible_link_count", 0)),
        aggregate_redacted=is_low_cardinality,
        suppression_reason=LOW_CARDINALITY_REASON if is_low_cardinality else None,
    )


def get_overview(principal: Any, filters: dict[str, Any]) -> OverviewResponse:
    """Build the ``OverviewResponse`` for the given principal."""
    allowed_locations, is_admin = _resolve_visible_set(principal)
    raw_clusters = graph_lod_repo.aggregate_overview_clusters(
        allowed_locations=allowed_locations,
        is_admin=is_admin,
    )

    minimum_count = DEFAULT_MINIMUM_COUNT
    clusters = [_shape_cluster(principal, raw, minimum_count) for raw in raw_clusters]

    # Derive the aggregate policy tier using the largest cluster's visible count.
    # The per-cluster scope check (``_region_in_breakdown_scope``) only
    # elevates to CITY when at least one high-count cluster is in scope; if
    # every high-count cluster is out of scope, silently downgrade to REGION.
    max_visible = max((c.visible_node_count for c in clusters), default=0)
    base_tier = derive_safe_geo_precision(max_visible, minimum_count)
    if base_tier == SafeGeoPrecision.CITY.value:
        if not _has_breakdown_permission(principal):
            # No capability -> silent downgrade to region (REQ-OVERVIEW-2 scenario 4)
            safe_geo_precision = SafeGeoPrecision.REGION.value
        else:
            # Capability present -> city only if at least one high-count
            # cluster is in scope; otherwise silent downgrade to region
            any_in_scope = any(
                c.visible_node_count >= minimum_count * LOW_CARDINALITY_THRESHOLD_MULTIPLIER
                and _region_in_breakdown_scope(principal, c.display_label)
                for c in clusters
            )
            safe_geo_precision = (
                SafeGeoPrecision.CITY.value if any_in_scope else SafeGeoPrecision.REGION.value
            )
    else:
        safe_geo_precision = base_tier

    aggregate_policy = AggregatePolicyDTO(
        minimum_count=minimum_count,
        permission_required=PERMISSION_REQUIRED,
        safe_geo_precision=SafeGeoPrecision(safe_geo_precision),
    )

    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    revision = f"revision-{int(datetime.now(UTC).timestamp())}"

    return OverviewResponse(
        axis="location",
        filters=dict(filters or {}),
        generated_at=generated_at,
        revision=revision,
        aggregate_policy=aggregate_policy,
        clusters=clusters,
        inter_cluster_links=[],  # populated in a follow-up slice (inter-cluster edges)
        legend=Legend(),
        page=Page(),
    )
