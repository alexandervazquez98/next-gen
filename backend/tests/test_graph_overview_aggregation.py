"""Overview endpoint aggregation + aggregate policy (#391 PR1).

REQ-OVERVIEW-1..4 from ``openspec/changes/cmdb-graph-lod-runtime/specs/cmdb-graph-overview-api/spec.md``.

Covers:

- Endpoint returns ``OverviewResponse`` shape with axis, filters, clusters,
  aggregate_policy.
- ``SafeGeoPrecision`` tier selection based on visible count.
- ``graph:aggregate_breakdown:read`` permission gating.
- Per-user ``aggregate_breakdown_regions`` scope resolution.
- Hidden ≡ absent parity for clusters outside the principal's scope.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock


def _principal(
    *,
    is_admin: bool = False,
    allowed_locations: list[str] | None = None,
    permissions: list[str] | None = None,
    aggregate_breakdown_regions: list[str] | None = None,
):
    """Build a minimal principal-like object for service tests."""
    p = MagicMock()
    p.is_admin = is_admin
    p.allowed_locations = allowed_locations or []
    p.permissions = permissions or []
    p.aggregate_breakdown_regions = (
        [] if aggregate_breakdown_regions is None else list(aggregate_breakdown_regions)
    )
    return p


def _cluster(
    cluster_id: str,
    visible_node_count: int,
    visible_link_count: int = 0,
    *,
    critical_count: int = 0,
    warning_count: int = 0,
    event_count: int = 0,
) -> dict:
    return {
        "cluster_id": cluster_id,
        "display_label": cluster_id.split(":", 1)[1] if ":" in cluster_id else cluster_id,
        "visible_node_count": visible_node_count,
        "visible_link_count": visible_link_count,
        "aggregate_redacted": False,
        "suppression_reason": None,
        # #524 — severity count fields. Default 0 keeps the
        # pre-#524 helper invocations valid; tests that want to
        # exercise non-zero counts pass them explicitly.
        "critical_count": critical_count,
        "warning_count": warning_count,
        "event_count": event_count,
    }


def _patch_repo(monkeypatch, return_value: list[dict]) -> None:
    from repositories import graph_lod_repo

    monkeypatch.setattr(
        graph_lod_repo,
        "aggregate_overview_clusters",
        lambda allowed_locations=None, is_admin=False: return_value,
    )


# ---------------------------------------------------------------------------
# Endpoint shape
# ---------------------------------------------------------------------------


def test_overview_returns_overview_response_shape(monkeypatch):
    from services import graph_lod_service

    _patch_repo(
        monkeypatch,
        [_cluster("location:HQ-Madrid", 10), _cluster("location:DC-East", 5)],
    )
    principal = _principal(is_admin=True)

    result = graph_lod_service.get_overview(principal=principal, filters={})

    assert result.axis == "location"
    assert result.filters == {}
    assert result.aggregate_policy.minimum_count == 5
    assert result.aggregate_policy.permission_required == "graph:aggregate_breakdown:read"
    assert len(result.clusters) == 2


def test_overview_includes_revision_and_generated_at(monkeypatch):
    from services import graph_lod_service

    _patch_repo(monkeypatch, [])
    result = graph_lod_service.get_overview(principal=_principal(), filters={})

    assert result.generated_at
    # ISO 8601 with timezone
    parsed = datetime.fromisoformat(result.generated_at.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


# ---------------------------------------------------------------------------
# SafeGeoPrecision tier selection
# ---------------------------------------------------------------------------


def test_aggregate_policy_none_when_visible_count_below_minimum(monkeypatch):
    """count < minimum_count -> safe_geo_precision='none' (REQ-OVERVIEW-2 scenario 1)."""
    from services import graph_lod_service

    _patch_repo(monkeypatch, [_cluster("location:Tiny", 2)])
    result = graph_lod_service.get_overview(principal=_principal(is_admin=True), filters={})

    assert result.aggregate_policy.safe_geo_precision == "none"


def test_aggregate_policy_region_when_visible_count_mid_range(monkeypatch):
    """minimum_count <= count < minimum_count * 4 -> 'region'."""
    from services import graph_lod_service

    # minimum_count default = 5, so 10 (between 5 and 20) -> region
    _patch_repo(monkeypatch, [_cluster("location:Mid", 10)])
    result = graph_lod_service.get_overview(principal=_principal(is_admin=True), filters={})

    assert result.aggregate_policy.safe_geo_precision == "region"


def test_aggregate_policy_city_when_visible_count_high_and_global_permission(monkeypatch):
    """count >= min*4 AND permission AND regions list empty -> 'city' (REQ-OVERVIEW-2 scenario 3)."""
    from services import graph_lod_service

    _patch_repo(monkeypatch, [_cluster("location:Big", 100)])
    principal = _principal(
        is_admin=True,
        permissions=["graph:aggregate_breakdown:read"],
        aggregate_breakdown_regions=[],  # global breakdown
    )
    result = graph_lod_service.get_overview(principal=principal, filters={})

    assert result.aggregate_policy.safe_geo_precision == "city"


def test_aggregate_policy_city_when_visible_count_high_and_region_in_scope(monkeypatch):
    """count >= min*4 AND permission AND region in scope -> 'city'."""
    from services import graph_lod_service

    _patch_repo(monkeypatch, [_cluster("location:Big", 100)])
    principal = _principal(
        is_admin=True,
        permissions=["graph:aggregate_breakdown:read"],
        aggregate_breakdown_regions=["Big"],
    )
    result = graph_lod_service.get_overview(principal=principal, filters={})

    assert result.aggregate_policy.safe_geo_precision == "city"


def test_aggregate_policy_downgrades_to_region_when_region_out_of_scope(monkeypatch):
    """count >= min*4 AND permission AND region NOT in scope -> silent downgrade to 'region'."""
    from services import graph_lod_service

    _patch_repo(monkeypatch, [_cluster("location:Big", 100)])
    principal = _principal(
        is_admin=True,
        permissions=["graph:aggregate_breakdown:read"],
        aggregate_breakdown_regions=["OtherRegion"],
    )
    result = graph_lod_service.get_overview(principal=principal, filters={})

    assert result.aggregate_policy.safe_geo_precision == "region"


def test_aggregate_policy_downgrades_to_region_without_permission(monkeypatch):
    """count >= min*4 AND no permission -> 'region' (REQ-OVERVIEW-2 scenario 4)."""
    from services import graph_lod_service

    _patch_repo(monkeypatch, [_cluster("location:Big", 100)])
    principal = _principal(is_admin=True, permissions=[])
    result = graph_lod_service.get_overview(principal=principal, filters={})

    assert result.aggregate_policy.safe_geo_precision == "region"


# ---------------------------------------------------------------------------
# Hidden ≡ absent parity (REQ-OVERVIEW-3)
# ---------------------------------------------------------------------------


def test_overview_does_not_leak_hidden_clusters_in_response(monkeypatch):
    """The repo is responsible for visibility; service must not double-process.

    If a cluster is hidden by the visibility filter, it is absent from the
    repo result. The service trusts the repo's pre-aggregation filtering.
    """
    from services import graph_lod_service

    # Repo returned only the visible cluster
    _patch_repo(monkeypatch, [_cluster("location:HQ-Madrid", 10)])
    principal = _principal(allowed_locations=["HQ-Madrid"])
    result = graph_lod_service.get_overview(principal=principal, filters={})

    assert [c.cluster_id for c in result.clusters] == ["location:HQ-Madrid"]


def test_overview_empty_for_principal_with_no_scope(monkeypatch):
    """A non-admin with no scope gets an empty overview (REQ-OVERVIEW-2)."""
    from services import graph_lod_service

    _patch_repo(monkeypatch, [])  # repo returns empty for unscoped non-admin
    principal = _principal(allowed_locations=[])
    result = graph_lod_service.get_overview(principal=principal, filters={})

    assert result.clusters == []


# ---------------------------------------------------------------------------
# Cluster-level redaction markers
# ---------------------------------------------------------------------------


def test_overview_marks_low_cardinality_clusters_as_aggregate_redacted(monkeypatch):
    """A cluster with visible_node_count < minimum_count is marked redacted."""
    from services import graph_lod_service

    _patch_repo(
        monkeypatch,
        [
            _cluster("location:Tiny", 2),
            _cluster("location:Big", 50),
        ],
    )
    result = graph_lod_service.get_overview(principal=_principal(is_admin=True), filters={})

    by_id = {c.cluster_id: c for c in result.clusters}
    assert by_id["location:Tiny"].aggregate_redacted is True
    assert by_id["location:Tiny"].suppression_reason == "low_cardinality"
    assert by_id["location:Big"].aggregate_redacted is False
    assert by_id["location:Big"].suppression_reason is None


# ---------------------------------------------------------------------------
# Filter forwarding
# ---------------------------------------------------------------------------


def test_overview_passes_filters_to_response(monkeypatch):
    from services import graph_lod_service

    _patch_repo(monkeypatch, [])
    result = graph_lod_service.get_overview(
        principal=_principal(is_admin=True),
        filters={"severity": "CRITICAL"},
    )
    assert result.filters == {"severity": "CRITICAL"}
