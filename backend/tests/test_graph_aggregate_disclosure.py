"""Aggregate disclosure policy integration tests (#391 PR3).

REQ-OVERVIEW-2 from ``openspec/changes/cmdb-graph-lod-runtime/specs/cmdb-graph-overview-api/spec.md``.

Verifies the end-to-end aggregate policy behavior on real aggregation
results. Complements the unit tests in ``test_graph_overview_aggregation.py``
(which mock the repo) by exercising the service against the actual
``derive_safe_geo_precision`` ladder.

Tests:

- ``SafeGeoPrecision.NONE`` when max_visible_count < minimum_count
- ``SafeGeoPrecision.REGION`` when count in mid range (min <= count < min*4)
- ``SafeGeoPrecision.CITY`` when count high + permission + scope
- Silent downgrade to ``REGION`` when permission absent
- Silent downgrade to ``REGION`` when scope excludes all high-count clusters
- Per-cluster ``aggregate_redacted`` marker for low-cardinality clusters
"""

from __future__ import annotations

from unittest.mock import MagicMock

from contracts.aggregate_policy import DEFAULT_MINIMUM_COUNT


def _principal(*, is_admin: bool = False, permissions=None, aggregate_breakdown_regions=None):
    p = MagicMock()
    p.is_admin = is_admin
    p.allowed_locations = []
    p.permissions = permissions or []
    p.aggregate_breakdown_regions = (
        [] if aggregate_breakdown_regions is None else list(aggregate_breakdown_regions)
    )
    return p


def _cluster(
    cluster_id: str,
    count: int,
    *,
    critical_count: int = 0,
    warning_count: int = 0,
    event_count: int = 0,
) -> dict:
    return {
        "cluster_id": cluster_id,
        "display_label": cluster_id.split(":", 1)[1],
        "visible_node_count": count,
        "visible_link_count": 0,
        "aggregate_redacted": False,
        "suppression_reason": None,
        # #524 — severity count fields. Default 0 keeps pre-#524
        # callers valid; tests pass non-zero values explicitly when
        # exercising severity paths.
        "critical_count": critical_count,
        "warning_count": warning_count,
        "event_count": event_count,
    }


# ---------------------------------------------------------------------------
# Tier ladder (REQ-OVERVIEW-2 scenarios 1, 2, 3)
# ---------------------------------------------------------------------------


def test_tier_none_when_max_visible_count_below_minimum(monkeypatch):
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    monkeypatch.setattr(
        repo_module,
        "aggregate_overview_clusters",
        lambda **kwargs: [
            _cluster("location:Tiny", DEFAULT_MINIMUM_COUNT - 1),
        ],
    )

    resp = graph_lod_service.get_overview(principal=_principal(is_admin=True), filters={})

    assert resp.aggregate_policy.safe_geo_precision.value == "none"
    assert resp.aggregate_policy.minimum_count == DEFAULT_MINIMUM_COUNT


def test_tier_region_when_max_visible_in_mid_range(monkeypatch):
    """minimum_count <= count < minimum_count * 4 -> 'region'."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    # Default min=5, so 10 (between 5 and 19) -> region
    mid_count = DEFAULT_MINIMUM_COUNT + 1
    monkeypatch.setattr(
        repo_module,
        "aggregate_overview_clusters",
        lambda **kwargs: [_cluster("location:Mid", mid_count)],
    )

    resp = graph_lod_service.get_overview(principal=_principal(is_admin=True), filters={})

    assert resp.aggregate_policy.safe_geo_precision.value == "region"


def test_tier_city_when_max_visible_high_and_global_breakdown(monkeypatch):
    """count >= minimum_count * 4 AND permission AND empty regions list -> 'city'."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    high_count = DEFAULT_MINIMUM_COUNT * 4 + 10
    monkeypatch.setattr(
        repo_module,
        "aggregate_overview_clusters",
        lambda **kwargs: [_cluster("location:Big", high_count)],
    )

    resp = graph_lod_service.get_overview(
        principal=_principal(
            is_admin=True,
            permissions=["graph:aggregate_breakdown:read"],
            aggregate_breakdown_regions=[],
        ),
        filters={},
    )

    assert resp.aggregate_policy.safe_geo_precision.value == "city"


# ---------------------------------------------------------------------------
# Silent downgrade paths (REQ-OVERVIEW-2 scenario 4)
# ---------------------------------------------------------------------------


def test_tier_downgrades_to_region_without_permission(monkeypatch):
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    high_count = DEFAULT_MINIMUM_COUNT * 4 + 10
    monkeypatch.setattr(
        repo_module,
        "aggregate_overview_clusters",
        lambda **kwargs: [_cluster("location:Big", high_count)],
    )

    resp = graph_lod_service.get_overview(
        principal=_principal(is_admin=True, permissions=[]),
        filters={},
    )

    assert resp.aggregate_policy.safe_geo_precision.value == "region"


def test_tier_downgrades_to_region_when_region_out_of_scope(monkeypatch):
    """Permission granted but region not in scope -> silent downgrade."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    high_count = DEFAULT_MINIMUM_COUNT * 4 + 10
    monkeypatch.setattr(
        repo_module,
        "aggregate_overview_clusters",
        lambda **kwargs: [_cluster("location:Big", high_count)],
    )

    resp = graph_lod_service.get_overview(
        principal=_principal(
            is_admin=True,
            permissions=["graph:aggregate_breakdown:read"],
            aggregate_breakdown_regions=["OtherRegion"],
        ),
        filters={},
    )

    assert resp.aggregate_policy.safe_geo_precision.value == "region"


def test_tier_city_when_some_high_count_cluster_in_scope(monkeypatch):
    """Multiple clusters: city available if any high-count cluster is in scope."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    high_count = DEFAULT_MINIMUM_COUNT * 4 + 10
    monkeypatch.setattr(
        repo_module,
        "aggregate_overview_clusters",
        lambda **kwargs: [
            _cluster("location:Big", high_count),
            _cluster("location:OtherRegion", high_count),
        ],
    )

    # "Big" is in scope, "OtherRegion" is not. City available.
    resp = graph_lod_service.get_overview(
        principal=_principal(
            is_admin=True,
            permissions=["graph:aggregate_breakdown:read"],
            aggregate_breakdown_regions=["Big"],
        ),
        filters={},
    )

    assert resp.aggregate_policy.safe_geo_precision.value == "city"


# ---------------------------------------------------------------------------
# Per-cluster redaction markers
# ---------------------------------------------------------------------------


def test_clusters_with_count_below_minimum_marked_redacted(monkeypatch):
    """A cluster with visible_node_count < minimum_count is marked aggregate_redacted=True."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    monkeypatch.setattr(
        repo_module,
        "aggregate_overview_clusters",
        lambda **kwargs: [
            _cluster("location:Tiny", DEFAULT_MINIMUM_COUNT - 1),
            _cluster("location:Big", DEFAULT_MINIMUM_COUNT * 10),
        ],
    )

    resp = graph_lod_service.get_overview(principal=_principal(is_admin=True), filters={})

    by_id = {c.cluster_id: c for c in resp.clusters}
    assert by_id["location:Tiny"].aggregate_redacted is True
    assert by_id["location:Tiny"].suppression_reason == "low_cardinality"
    assert by_id["location:Big"].aggregate_redacted is False
    assert by_id["location:Big"].suppression_reason is None


# ---------------------------------------------------------------------------
# Aggregate breakdown regions field on User (model integration)
# ---------------------------------------------------------------------------


def test_user_model_has_aggregate_breakdown_regions_field():
    """The User model exposes the per-user scope field (default empty list)."""
    from models.user import User

    u = User(username="test", role="VIEWER")
    assert hasattr(u, "aggregate_breakdown_regions")
    assert u.aggregate_breakdown_regions == []


def test_user_update_supports_aggregate_breakdown_regions():
    """UserUpdate can set aggregate_breakdown_regions."""
    from models.user import UserUpdate

    update = UserUpdate(
        username="test",
        aggregate_breakdown_regions=["DC-East", "DC-West"],
    )
    assert update.aggregate_breakdown_regions == ["DC-East", "DC-West"]


def test_user_permission_enum_has_graph_aggregate_breakdown_read():
    """UserPermission enum exposes the capability gate."""
    from models.user import UserPermission

    assert UserPermission.GRAPH_AGGREGATE_BREAKDOWN_READ.value == "graph:aggregate_breakdown:read"
