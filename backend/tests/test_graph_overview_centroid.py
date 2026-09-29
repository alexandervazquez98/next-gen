"""OverviewCluster carries a privacy-safe centroid (#524).

Adds ``centroid_lat`` and ``centroid_long`` to ``OverviewCluster`` so the
Geo View of MonitoringConsole can place cluster markers on the Leaflet
map at country zoom. The original LOD overview payload only carried
the cluster_id (``location:HQ-Madrid``) and the display_label — neither
of which is enough to render a marker at a position on the map.

Privacy policy (REQ-9, same as the existing safe_geo_precision ladder):

- ``safe_geo_precision == "none"`` — centroid is suppressed (0.0 / 0.0).
  Redacted clusters (aggregate_redacted=True) always suppress.
- ``safe_geo_precision == "region"`` — centroid rounded to 2 decimals
  (~1.1 km precision).
- ``safe_geo_precision == "city"``   — centroid rounded to 4 decimals
  (~11 m precision).

The rounding is applied by the service layer AFTER the per-principal
precision tier is resolved. The Cypher repo returns the unrounded
centroid; the service applies the rounding. That keeps the repo
deterministic and the policy decision in one place.

The wire shape mirrors ``frontend/types/graph.ts::OverviewCluster`` and
is enforced by the parity gate.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from services import graph_lod_service


def _principal(*, is_admin: bool = True, with_breakdown_perm: bool = False):
    p = MagicMock()
    p.is_admin = is_admin
    p.allowed_locations = []
    p.permissions = ["graph:aggregate_breakdown:read"] if with_breakdown_perm else []
    p.aggregate_breakdown_regions = []
    return p


# ---------------------------------------------------------------------------
# Schema — pure data shape
# ---------------------------------------------------------------------------


def test_overview_cluster_exposes_centroid_fields():
    from schemas.graph import OverviewCluster

    cluster = OverviewCluster(
        cluster_id="location:HQ-Madrid",
        display_label="HQ-Madrid",
        visible_node_count=10,
        centroid_lat=40.4168,
        centroid_long=-3.7038,
    )

    assert cluster.centroid_lat == 40.4168
    assert cluster.centroid_long == -3.7038


def test_overview_cluster_centroid_defaults_to_zero():
    """Additive change: existing fixtures that omit centroid stay valid."""
    from schemas.graph import OverviewCluster

    cluster = OverviewCluster(
        cluster_id="location:DC-East",
        display_label="DC-East",
        visible_node_count=5,
    )

    assert cluster.centroid_lat == 0.0
    assert cluster.centroid_long == 0.0


# ---------------------------------------------------------------------------
# Service — apply safe_geo_precision rounding
# ---------------------------------------------------------------------------


def _patch_repo(monkeypatch, rows: list[dict]) -> None:
    from repositories import graph_lod_repo

    monkeypatch.setattr(
        graph_lod_repo,
        "aggregate_overview_clusters",
        lambda allowed_locations=None, is_admin=False: rows,
    )


def test_centroid_is_zeroed_on_redacted_clusters(monkeypatch):
    """REQ-9: redacted clusters (low-cardinality) must NOT disclose centroid."""
    rows = [
        {
            "cluster_id": "location:Tiny",
            "display_label": "Tiny",
            "visible_node_count": 1,  # < minimum_count (5) → redacted
            "visible_link_count": 0,
            "aggregate_redacted": False,
            "suppression_reason": None,
            "critical_count": 0,
            "warning_count": 0,
            "event_count": 0,
            "centroid_lat": 40.4168,
            "centroid_long": -3.7038,
        },
    ]
    _patch_repo(monkeypatch, rows)

    result = graph_lod_service.get_overview(principal=_principal(), filters={})
    assert len(result.clusters) == 1
    assert result.clusters[0].centroid_lat == 0.0
    assert result.clusters[0].centroid_long == 0.0


def test_centroid_is_suppressed_when_precision_is_none(monkeypatch):
    """When the response-level safe_geo_precision is 'none', centroids are 0.0.

    'none' precision happens when even the largest cluster has fewer
    than minimum_count CIs — i.e., NO cluster qualifies for region/city
    precision. In that case we suppress ALL centroids (defense in depth).
    """
    rows = [
        {
            "cluster_id": "location:Tiny",
            "display_label": "Tiny",
            "visible_node_count": 3,  # below minimum_count=5
            "visible_link_count": 0,
            "aggregate_redacted": False,
            "suppression_reason": None,
            "critical_count": 0,
            "warning_count": 0,
            "event_count": 0,
            "centroid_lat": 40.4168,
            "centroid_long": -3.7038,
        },
    ]
    _patch_repo(monkeypatch, rows)

    result = graph_lod_service.get_overview(principal=_principal(), filters={})
    assert result.aggregate_policy.safe_geo_precision == "none"
    assert result.clusters[0].centroid_lat == 0.0
    assert result.clusters[0].centroid_long == 0.0


def test_centroid_is_rounded_to_region_precision(monkeypatch):
    """Region precision rounds to 2 decimals (~1.1 km)."""
    rows = [
        {
            "cluster_id": "location:Region-A",
            "display_label": "Region-A",
            # visible_count in the [min, min*4) range → region precision
            "visible_node_count": 8,  # >= 5 and < 20
            "visible_link_count": 0,
            "aggregate_redacted": False,
            "suppression_reason": None,
            "critical_count": 0,
            "warning_count": 0,
            "event_count": 0,
            "centroid_lat": 40.416775,  # unrounded
            "centroid_long": -3.703790,  # unrounded
        },
    ]
    _patch_repo(monkeypatch, rows)

    result = graph_lod_service.get_overview(principal=_principal(), filters={})
    assert result.aggregate_policy.safe_geo_precision == "region"
    # 2 decimals → 40.42 / -3.70
    assert result.clusters[0].centroid_lat == 40.42
    assert result.clusters[0].centroid_long == -3.70


def test_centroid_is_rounded_to_city_precision(monkeypatch):
    """City precision rounds to 4 decimals (~11 m)."""
    rows = [
        {
            "cluster_id": "location:BigCity",
            "display_label": "BigCity",
            # visible_count >= min * 4 → city precision (admin path)
            "visible_node_count": 100,
            "visible_link_count": 0,
            "aggregate_redacted": False,
            "suppression_reason": None,
            "critical_count": 0,
            "warning_count": 0,
            "event_count": 0,
            "centroid_lat": 40.41677555,  # unrounded
            "centroid_long": -3.70379042,  # unrounded
        },
    ]
    _patch_repo(monkeypatch, rows)

    # Admin path with breakdown permission → city precision is granted.
    result = graph_lod_service.get_overview(
        principal=_principal(is_admin=True, with_breakdown_perm=True),
        filters={},
    )
    assert result.aggregate_policy.safe_geo_precision == "city"
    # 4 decimals → 40.4168 / -3.7038
    assert result.clusters[0].centroid_lat == 40.4168
    assert result.clusters[0].centroid_long == -3.7038


def test_centroid_passes_through_when_no_rounding_needed(monkeypatch):
    """Values already at the precision tier are unchanged."""
    rows = [
        {
            "cluster_id": "location:Already-Rounded",
            "display_label": "Already-Rounded",
            "visible_node_count": 100,  # city precision
            "visible_link_count": 0,
            "aggregate_redacted": False,
            "suppression_reason": None,
            "critical_count": 0,
            "warning_count": 0,
            "event_count": 0,
            "centroid_lat": 40.4168,  # already 4 decimals
            "centroid_long": -3.7038,
        },
    ]
    _patch_repo(monkeypatch, rows)

    result = graph_lod_service.get_overview(
        principal=_principal(is_admin=True, with_breakdown_perm=True),
        filters={},
    )
    assert result.clusters[0].centroid_lat == 40.4168
    assert result.clusters[0].centroid_long == -3.7038


def test_centroid_zero_handling_at_negative_coordinates(monkeypatch):
    """Negative longitudes round correctly under city precision."""
    rows = [
        {
            "cluster_id": "location:WEST",
            "display_label": "WEST",
            "visible_node_count": 100,
            "visible_link_count": 0,
            "aggregate_redacted": False,
            "suppression_reason": None,
            "critical_count": 0,
            "warning_count": 0,
            "event_count": 0,
            "centroid_lat": 39.51209,
            "centroid_long": -100.39068,  # 5th decimal > 5 → rounds up unambiguously
        },
    ]
    _patch_repo(monkeypatch, rows)

    result = graph_lod_service.get_overview(
        principal=_principal(is_admin=True, with_breakdown_perm=True),
        filters={},
    )
    assert result.clusters[0].centroid_lat == 39.5121
    assert result.clusters[0].centroid_long == -100.3907  # sign preserved
