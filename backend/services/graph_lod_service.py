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
from contracts.cluster_id import (
    assert_axis_matches,
    parse_cluster_id,
)
from contracts.cursor import (
    InvalidCursorError,
    decode_cursor,
    derive_principal_hash,
    encode_cursor,
)
from contracts.projection import SensitiveSource
from contracts.revision import Revision
from repositories import graph_lod_repo
from schemas.graph import (
    AggregatePolicyDTO,
    DetailCluster,
    DetailLink,
    DetailNode,
    DetailResponse,
    Legend,
    OverviewCluster,
    OverviewResponse,
    Page,
    ProjectionFlags,
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
    # #524 — aggregated severity counts. Repo returns them when the
    # aggregation query joins against the Event label; on redacted
    # clusters (low-cardinality) we MUST zero them so the aggregate
    # never discloses per-CI severity. Same REQ-9 policy that already
    # hides public_ip / metadata on the cluster aggregate.
    if is_low_cardinality:
        critical_count = 0
        warning_count = 0
        event_count = 0
    else:
        critical_count = int(raw.get("critical_count", 0))
        warning_count = int(raw.get("warning_count", 0))
        event_count = int(raw.get("event_count", 0))
    return OverviewCluster(
        cluster_id=cluster_id,
        display_label=display_label,
        visible_node_count=visible_node_count,
        visible_link_count=int(raw.get("visible_link_count", 0)),
        aggregate_redacted=is_low_cardinality,
        suppression_reason=LOW_CARDINALITY_REASON if is_low_cardinality else None,
        critical_count=critical_count,
        warning_count=warning_count,
        event_count=event_count,
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


# ---------------------------------------------------------------------------
# #391 PR2: detail endpoint orchestration
# ---------------------------------------------------------------------------


def _resolve_revision() -> Revision:
    """Compute the current server revision token.

    Stub implementation per ``contracts.revision.Revision.derive`` docstring:
    full impl belongs alongside the aggregation queries in a follow-up. For
    now, a deterministic time-based stub is sufficient for cursor round-trip
    tests; it changes on every call (so stale cursors are detectable) but
    is opaque to clients.
    """
    from datetime import UTC, datetime as _dt

    snapshot = str(_dt.now(UTC).timestamp()).encode("utf-8")
    return Revision(f"revision-{int.from_bytes(snapshot[:4], 'big')}")


def _strip_sensitive_fields(node_dict: dict[str, Any]) -> dict[str, Any]:
    """Strip sensitive fields from a detail node (REQ-DETAIL-5)."""
    sensitive_keys = {"public_ip", "metadata", "geo", "serial", "provider_account"}
    return {k: v for k, v in node_dict.items() if k not in sensitive_keys}


def _principal_permissions(principal: Any) -> frozenset[str]:
    return frozenset(getattr(principal, "permissions", []) or [])


def _projection_policy(principal: Any, sensitive_requested: bool) -> ProjectionFlags:
    """Compute projection flags per the DetailProjectionPolicy contract.

    show_sensitive_metadata=True ONLY when:
      - principal has graph:aggregate_breakdown:read AND
      - caller explicitly requested sensitive fields (?sensitive=include)

    Otherwise False. The endpoint NEVER defaults to True.
    """
    has_perm = PERMISSION_REQUIRED in _principal_permissions(principal)
    if has_perm and sensitive_requested:
        return ProjectionFlags(
            show_sensitive_metadata=True,
            sensitive_source=SensitiveSource.PRINCIPAL_WITH_PERMISSION,
        )
    if has_perm and not sensitive_requested:
        return ProjectionFlags(
            show_sensitive_metadata=False,
            sensitive_source=SensitiveSource.NEVER,
        )
    if (not has_perm) and sensitive_requested:
        return ProjectionFlags(
            show_sensitive_metadata=False,
            sensitive_source=SensitiveSource.NEVER,
        )
    return ProjectionFlags(
        show_sensitive_metadata=False,
        sensitive_source=SensitiveSource.NEVER,
    )


def _shape_detail_node(raw: dict[str, Any], projection: ProjectionFlags) -> DetailNode:
    """Apply projection to a raw node dict and shape it as DetailNode."""
    node_data = dict(raw) if projection.show_sensitive_metadata else _strip_sensitive_fields(raw)
    allowed_axes = node_data.get("allowed_public_axes") or []
    return DetailNode(
        id=str(node_data["id"]),
        display_label=str(node_data.get("display_label") or node_data["id"]),
        kind=str(node_data.get("kind") or "CI"),
        ci_type=str(node_data.get("ci_type") or "CI"),
        allowed_public_axes=list(allowed_axes),
    )


def _shape_detail_link(raw: dict[str, Any]) -> DetailLink:
    return DetailLink(
        source_node_id=str(raw["source_node_id"]),
        target_node_id=str(raw["target_node_id"]),
        relationship=str(raw["relationship"]),
    )


def _shape_detail_cluster(cluster_id: str, raw: dict[str, Any]) -> DetailCluster:
    return DetailCluster(
        cluster_id=cluster_id,
        axis="location",
        display_label=str(raw.get("display_label") or cluster_id.split(":", 1)[1]),
        visible_node_count=int(raw.get("visible_node_count", 0)),
        visible_link_count=int(raw.get("visible_link_count", 0)),
    )


def get_detail(
    *,
    cluster_id_raw: str,
    principal: Any,
    filters: dict[str, Any],
    cursor: str | None,
    limit: int,
    sensitive_requested: bool,
    axis_query: str | None = None,
) -> DetailResponse:
    """Build the DetailResponse for the given cluster and principal.

    Hard rules (mirrored from the spec):

    - Authorization/scoping happens BEFORE aggregation (delegated to repo).
    - Hidden cluster and absent cluster produce byte-equivalent responses
      (``cluster: null`` + ``empty_reason: "hidden_absent"``).
    - Cursor is bound to (cluster_id, filters_hash, revision, principal_hash).
      Stale revisions surface as 409; permission changes as 400.
    - ``?axis=`` query parameter is validated BEFORE any auth-sensitive
      lookup (REQ-DETAIL-2).
    - Sensitive metadata is included only when principal has
      ``graph:aggregate_breakdown:read`` AND caller requested it.

    Raises:

    - :class:`contracts.cluster_id.InvalidClusterIdError` for malformed
      cluster_id (router translates to 400 invalid_cluster_id).
    - :class:`contracts.cluster_id.AxisConflictError` for axis mismatch
      (router translates to 400 axis_conflict).
    - :class:`contracts.cursor.InvalidCursorError` for malformed cursor
      (router translates to 400 invalid_cursor).
    - :class:`contracts.cursor.StaleCursorError` for stale revision
      (router translates to 409 stale_cursor).
    - :class:`contracts.cursor.PermissionChangedError` for principal
      drift (router translates to 400 stale_cursor / permission_changed).
    """
    # Step 1: parse cluster_id and verify axis match BEFORE any DB call
    parsed = parse_cluster_id(cluster_id_raw)
    assert_axis_matches(parsed, axis_query)
    cluster_id = parsed.wire

    # Step 2: decode cursor if present. Errors propagate (router handles HTTP)
    current_revision = _resolve_revision()
    current_principal_hash = derive_principal_hash(_principal_permissions(principal))
    decoded_cursor = None
    if cursor:
        decoded_cursor = decode_cursor(
            cursor,
            current_revision=current_revision,
            current_principal_hash=current_principal_hash,
        )
        # Cursor cluster_id must match the parsed cluster_id
        if decoded_cursor.cluster_id != cluster_id:
            raise InvalidCursorError(
                f"cursor cluster_id {decoded_cursor.cluster_id!r} does not match "
                f"path cluster_id {cluster_id!r}"
            )

    # Step 3: resolve visible-set and aggregate
    is_admin = bool(getattr(principal, "is_admin", False))
    allowed_locations: list[str] | None = None
    if not is_admin:
        allowed = list(getattr(principal, "allowed_locations", []) or [])
        allowed_locations = allowed or None

    raw_subgraph = graph_lod_repo.aggregate_detail_subgraph(
        cluster_id=cluster_id,
        allowed_locations=allowed_locations,
        is_admin=is_admin,
        limit=limit,
    )

    # Step 4: apply projection
    projection = _projection_policy(principal, sensitive_requested)

    # Step 5: shape response — hidden/absent parity (REQ-DETAIL-4)
    now = datetime.now(UTC)
    generated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    revision_value = current_revision.value

    if raw_subgraph is None or raw_subgraph.get("cluster") is None:
        # Hidden or absent — externally indistinguishable response
        return DetailResponse(
            cluster=None,
            filters=dict(filters or {}),
            generated_at=generated_at,
            revision=revision_value,
            nodes=[],
            links=[],
            boundary_stubs=[],
            projection_flags=projection,
            empty_reason="hidden_absent",
            page=Page(has_more=False, next_cursor=None),
        )

    cluster_meta = raw_subgraph["cluster"]
    nodes = [_shape_detail_node(n, projection) for n in raw_subgraph.get("nodes") or []]
    links = [_shape_detail_link(link) for link in raw_subgraph.get("links") or []]
    has_more = bool(raw_subgraph.get("has_more", False))

    # Build next cursor only when there are more pages
    next_cursor = None
    if has_more:
        next_cursor = encode_cursor(
            cluster_id=cluster_id,
            filters=filters or {},
            revision=current_revision,
            principal_hash=current_principal_hash,
        )

    return DetailResponse(
        cluster=_shape_detail_cluster(cluster_id, cluster_meta),
        filters=dict(filters or {}),
        generated_at=generated_at,
        revision=revision_value,
        nodes=nodes,
        links=links,
        boundary_stubs=[],
        projection_flags=projection,
        empty_reason="none",
        page=Page(has_more=has_more, next_cursor=next_cursor),
    )
