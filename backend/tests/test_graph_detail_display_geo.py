"""DetailNode gains display_geo via safe_geo_precision rounding (#524 follow-up).

Mirror of the OverviewCluster centroid path (``_round_cluster_centroid``),
applied per-node. The repo returns raw ``n.location.lat/long``; the service
applies the privacy-safe rounding tier derived from the focused cluster's
``visible_node_count`` (same ``derive_safe_geo_precision`` ladder).

Tiers:
  - ``none``  -> display_geo = None  (cluster too small to disclose geo).
  - ``region`` -> rounded to 2 decimals  (~1.1 km).
  - ``city``   -> rounded to 4 decimals  (~11 m).

Defense in depth:
  - Raw coordinates (0, 0) from a CI without ``n.location`` are dropped
    to ``display_geo = None`` regardless of the tier. The repo
    COALESCEs ``n.location.lat/long`` to 0.0; (0, 0) is the sentinel
    for "no location set" and is NEVER rendered.
  - The helper returns a NEW node via ``model_copy(update=...)``; the
    input node is never mutated (DetailNode is frozen at request scope).

REQ-9: the raw ``n.location.lat/long`` from the repo is NEVER emitted on
DetailNode.display_geo. Only the rounded value (or None) is exposed.
"""

from __future__ import annotations

from schemas.graph import DetailNode, DisplayGeo


def _principal():
    from unittest.mock import MagicMock

    p = MagicMock()
    p.is_admin = True
    p.permissions = []
    p.allowed_locations = []
    return p


# ---------------------------------------------------------------------------
# Helper: _round_detail_node_geo
# ---------------------------------------------------------------------------


def test_round_detail_node_geo_none_precision_suppresses_to_none():
    """Precision NONE -> display_geo = None (low-cardinality cluster).

    Defense in depth: even if the input has valid coordinates, NONE
    precision suppresses them entirely.
    """
    from contracts.aggregate_policy import SafeGeoPrecision
    from services import graph_lod_service

    node = DetailNode(
        id="ci-1",
        display_label="ci-1",
        kind="CI",
        ci_type="router",
        display_geo=DisplayGeo(lat=40.4168, long=-3.7038),
    )

    result = graph_lod_service._round_detail_node_geo(node, SafeGeoPrecision.NONE.value)

    assert result.display_geo is None


def test_round_detail_node_geo_region_rounds_to_2_decimals():
    """Precision REGION -> lat / long rounded to 2 decimals (~1.1 km)."""
    from contracts.aggregate_policy import SafeGeoPrecision
    from services import graph_lod_service

    node = DetailNode(
        id="ci-1",
        display_label="ci-1",
        kind="CI",
        ci_type="router",
        display_geo=DisplayGeo(lat=40.4168, long=-3.7038),
    )

    result = graph_lod_service._round_detail_node_geo(node, SafeGeoPrecision.REGION.value)

    assert result.display_geo is not None
    assert result.display_geo.lat == 40.42  # banker's rounding: 40.4168 -> 40.42
    assert result.display_geo.long == -3.70


def test_round_detail_node_geo_city_rounds_to_4_decimals():
    """Precision CITY -> lat / long rounded to 4 decimals (~11 m)."""
    from contracts.aggregate_policy import SafeGeoPrecision
    from services import graph_lod_service

    node = DetailNode(
        id="ci-1",
        display_label="ci-1",
        kind="CI",
        ci_type="router",
        display_geo=DisplayGeo(lat=40.41685, long=-3.70375),
    )

    result = graph_lod_service._round_detail_node_geo(node, SafeGeoPrecision.CITY.value)

    assert result.display_geo is not None
    assert result.display_geo.lat == 40.4168
    assert result.display_geo.long == -3.7037  # banker's rounding ties to even


def test_round_detail_node_geo_zero_coords_drop_to_none():
    """Sentinel: raw (0, 0) from CIs without n.location -> display_geo = None.

    The repo COALESCEs missing lat/long to 0.0; (0, 0) means "no location".
    The service MUST NEVER render a marker at (0, 0) regardless of tier.
    """
    from contracts.aggregate_policy import SafeGeoPrecision
    from services import graph_lod_service

    node = DetailNode(
        id="ci-orphan",
        display_label="ci-orphan",
        kind="CI",
        ci_type="router",
        display_geo=DisplayGeo(lat=0.0, long=0.0),
    )

    for precision in (
        SafeGeoPrecision.NONE.value,
        SafeGeoPrecision.REGION.value,
        SafeGeoPrecision.CITY.value,
    ):
        result = graph_lod_service._round_detail_node_geo(node, precision)
        assert (
            result.display_geo is None
        ), f"precision={precision} should drop (0, 0) to None; got {result.display_geo}"


def test_round_detail_node_geo_does_not_mutate_input():
    """The helper returns a NEW node; the input is never mutated.

    DetailNode is logically immutable at request scope; if the caller
    caches the rounded node across requests, mutations would leak.
    """
    from contracts.aggregate_policy import SafeGeoPrecision
    from services import graph_lod_service

    node = DetailNode(
        id="ci-1",
        display_label="ci-1",
        kind="CI",
        ci_type="router",
        display_geo=DisplayGeo(lat=40.4168, long=-3.7038),
    )
    original_geo = node.display_geo

    _ = graph_lod_service._round_detail_node_geo(node, SafeGeoPrecision.CITY.value)

    assert node.display_geo is original_geo
    assert node.display_geo.lat == 40.4168


def test_round_detail_node_geo_preserves_other_fields():
    """Rounding must not drop or alter the non-geo fields."""
    from contracts.aggregate_policy import SafeGeoPrecision
    from services import graph_lod_service

    node = DetailNode(
        id="ci-mad-01",
        display_label="HQ-Madrid-RT-01",
        kind="CI",
        ci_type="router",
        allowed_public_axes=["ci_type"],
        display_geo=DisplayGeo(lat=40.4168, long=-3.7038),
    )

    result = graph_lod_service._round_detail_node_geo(node, SafeGeoPrecision.REGION.value)

    assert result.id == "ci-mad-01"
    assert result.display_label == "HQ-Madrid-RT-01"
    assert result.kind == "CI"
    assert result.ci_type == "router"
    assert result.allowed_public_axes == ["ci_type"]


def test_round_detail_node_geo_none_input_passes_through():
    """If display_geo is already None, the helper must return None (no crash)."""
    from contracts.aggregate_policy import SafeGeoPrecision
    from services import graph_lod_service

    node = DetailNode(
        id="ci-1",
        display_label="ci-1",
        kind="CI",
        ci_type="router",
    )

    for precision in (
        SafeGeoPrecision.NONE.value,
        SafeGeoPrecision.REGION.value,
        SafeGeoPrecision.CITY.value,
    ):
        result = graph_lod_service._round_detail_node_geo(node, precision)
        assert result.display_geo is None


# ---------------------------------------------------------------------------
# Wire shape contract: DetailNode MUST NEVER expose raw ``location`` (REQ-9)
# ---------------------------------------------------------------------------


def test_shape_detail_node_does_not_expose_raw_location_key():
    """_shape_detail_node strips the raw location dict; only display_geo remains.

    Even if the repo returns ``location: { lat: ..., long: ... }`` in the
    raw node dict, the wire shape carries ``display_geo`` only. The raw
    ``location`` key MUST NEVER appear on a DetailNode dump.
    """
    from schemas.graph import ProjectionFlags, SensitiveSource
    from services import graph_lod_service

    raw = {
        "id": "ci-1",
        "display_label": "ci-1",
        "kind": "CI",
        "ci_type": "router",
        "allowed_public_axes": [],
        "location": {"lat": 40.4168, "long": -3.7038},
    }
    projection = ProjectionFlags(
        show_sensitive_metadata=False, sensitive_source=SensitiveSource.NEVER
    )

    node = graph_lod_service._shape_detail_node(raw, projection)

    dumped = node.model_dump(mode="json")
    assert "location" not in dumped, f"raw location leaked into wire shape: {dumped}"
    # ``lat`` / ``long`` are nested under ``display_geo`` (privacy-safe rounded)
    # — that is the only allowed emission. Verify the keys exist ONLY there.
    if dumped.get("display_geo") is not None:
        assert set(dumped["display_geo"].keys()) == {"lat", "long"}


# ---------------------------------------------------------------------------
# Integration: get_detail applies safe_geo_precision per focused cluster
# ---------------------------------------------------------------------------


def _principal(*, is_admin: bool = True, permissions: list[str] | None = None):
    from unittest.mock import MagicMock

    p = MagicMock()
    p.is_admin = is_admin
    p.allowed_locations = []
    p.permissions = permissions or []
    p.aggregate_breakdown_regions = []
    return p


def _raw_subgraph(
    *,
    visible_node_count: int,
    nodes: list[dict],
) -> dict:
    return {
        "cluster": {
            "cluster_id": "location:HQ-Madrid",
            "display_label": "HQ-Madrid",
            "visible_node_count": visible_node_count,
            "visible_link_count": 0,
        },
        "nodes": nodes,
        "links": [],
        "has_more": False,
    }


def _node_with_location(node_id: str, lat: float, lng: float) -> dict:
    return {
        "id": node_id,
        "display_label": node_id,
        "kind": "CI",
        "ci_type": "router",
        "allowed_public_axes": [],
        "location": {"lat": lat, "long": lng},
    }


def test_get_detail_low_cardinality_cluster_suppresses_display_geo(monkeypatch):
    """visible_node_count < minimum_count (5) -> precision=NONE -> display_geo=None for all.

    Integration test: get_detail resolves the tier from visible_node_count
    and applies it to every node. CIs without location set (raw (0, 0))
    also produce display_geo=None.
    """
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    monkeypatch.setattr(
        repo_module,
        "aggregate_detail_subgraph",
        lambda **kwargs: _raw_subgraph(
            visible_node_count=3,  # < 5 -> NONE
            nodes=[
                _node_with_location("ci-mad-01", 40.4168, -3.7038),
                _node_with_location("ci-orphan", 0.0, 0.0),
            ],
        ),
    )

    response = graph_lod_service.get_detail(
        cluster_id_raw="location:HQ-Madrid",
        principal=_principal(is_admin=True),
        filters={},
        cursor=None,
        limit=100,
        sensitive_requested=False,
    )

    assert len(response.nodes) == 2
    for node in response.nodes:
        assert node.display_geo is None, f"node {node.id} leaked geo at tier NONE"


def test_get_detail_region_precision_rounds_to_2_decimals(monkeypatch):
    """visible_node_count=10 -> precision=REGION -> display_geo rounded to 2 decimals."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    monkeypatch.setattr(
        repo_module,
        "aggregate_detail_subgraph",
        lambda **kwargs: _raw_subgraph(
            visible_node_count=10,  # < 20 -> REGION
            nodes=[_node_with_location("ci-mad-01", 40.4168, -3.7038)],
        ),
    )

    response = graph_lod_service.get_detail(
        cluster_id_raw="location:HQ-Madrid",
        principal=_principal(is_admin=True),
        filters={},
        cursor=None,
        limit=100,
        sensitive_requested=False,
    )

    assert response.nodes[0].display_geo is not None
    assert response.nodes[0].display_geo.lat == 40.42
    assert response.nodes[0].display_geo.long == -3.7


def test_get_detail_city_precision_rounds_to_4_decimals(monkeypatch):
    """visible_node_count=25 -> precision=CITY -> display_geo rounded to 4 decimals."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    monkeypatch.setattr(
        repo_module,
        "aggregate_detail_subgraph",
        lambda **kwargs: _raw_subgraph(
            visible_node_count=25,  # >= 20 -> CITY
            nodes=[_node_with_location("ci-mad-01", 40.41685, -3.70375)],
        ),
    )

    response = graph_lod_service.get_detail(
        cluster_id_raw="location:HQ-Madrid",
        principal=_principal(is_admin=True, permissions=["graph:aggregate_breakdown:read"]),
        filters={},
        cursor=None,
        limit=100,
        sensitive_requested=False,
    )

    assert response.nodes[0].display_geo is not None
    assert response.nodes[0].display_geo.lat == 40.4168
    assert response.nodes[0].display_geo.long == -3.7037


def test_get_detail_wire_shape_does_not_leak_raw_n_location(monkeypatch):
    """The DetailResponse JSON dump MUST NOT carry raw lat/long on a node.

    The only allowed emission of ``lat``/``long`` is nested under
    ``display_geo`` (privacy-safe rounded). Top-level ``location``,
    ``lat``, or ``long`` keys on a node dump = REQ-9 violation.
    """
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    monkeypatch.setattr(
        repo_module,
        "aggregate_detail_subgraph",
        lambda **kwargs: _raw_subgraph(
            visible_node_count=25,
            nodes=[_node_with_location("ci-mad-01", 40.41685, -3.70375)],
        ),
    )

    response = graph_lod_service.get_detail(
        cluster_id_raw="location:HQ-Madrid",
        principal=_principal(is_admin=True, permissions=["graph:aggregate_breakdown:read"]),
        filters={},
        cursor=None,
        limit=100,
        sensitive_requested=False,
    )

    dumped = response.model_dump(mode="json")
    for node_dump in dumped["nodes"]:
        assert "location" not in node_dump
        # Top-level lat / long MUST NOT exist on the node dump.
        assert "lat" not in node_dump
        assert "long" not in node_dump
        # The only allowed lat / long emission is nested under display_geo.
        if node_dump.get("display_geo") is not None:
            assert set(node_dump["display_geo"].keys()) == {"lat", "long"}
