"""Detail repo — `_build_detail_query` projects per-node geo for #524 follow-up.

The detail Cypher in ``graph_lod_repo._build_detail_query`` is extended
so the ``nodes_page`` map literal carries a per-node ``location`` object
with ``lat`` / ``long`` from ``n.location``. The service layer reads
those raw coordinates, applies ``safe_geo_precision`` rounding, and
populates the new ``DetailNode.display_geo`` field (REQ-9: the raw
``n.location.lat`` is NEVER exposed to clients — the service shapes it
into the privacy-safe DisplayGeo, or drops it to ``None``).

Privacy policy:

- The repo returns raw coordinates; the service decides what to emit.
- Redacted CIs (REQ-9 sensitive) are projected by the service into
  ``display_geo=None`` regardless of the repo's location payload.
- The Cypher never returns lat/long for a node that has no
  ``n.location`` — see COALESCE in the projection.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from repositories import graph_lod_repo


def _mock_driver(rows: list[dict] | None = None):
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    driver.session.return_value.__exit__.return_value = False
    session.run.return_value = rows if rows is not None else []
    return driver, session


# ---------------------------------------------------------------------------
# Cypher shape — the detail query must project n.location.lat / n.location.long
# into the per-node map literal so the service can compute display_geo.
# ---------------------------------------------------------------------------


def test_detail_query_projects_n_location_lat_into_nodes_page(monkeypatch):
    """The per-node map literal in nodes_page must read n.location.lat."""
    driver, session = _mock_driver()
    monkeypatch.setattr(graph_lod_repo, "get_db", lambda: driver)

    graph_lod_repo.aggregate_detail_subgraph(
        cluster_id="location:HQ-Madrid",
        allowed_locations=["HQ-Madrid"],
        is_admin=False,
    )

    query = session.run.call_args.args[0]
    assert "n.location.lat" in query


def test_detail_query_projects_n_location_long_into_nodes_page(monkeypatch):
    """The per-node map literal must read n.location.long as well."""
    driver, session = _mock_driver()
    monkeypatch.setattr(graph_lod_repo, "get_db", lambda: driver)

    graph_lod_repo.aggregate_detail_subgraph(
        cluster_id="location:HQ-Madrid",
        allowed_locations=["HQ-Madrid"],
        is_admin=False,
    )

    query = session.run.call_args.args[0]
    assert "n.location.long" in query


def test_detail_query_returns_nodes_with_location_key(monkeypatch):
    """The RETURN-shaped nodes carry a ``location`` key per node (#524 follow-up).

    Higher-level test: a fake driver returns one row whose ``nodes`` field
    is a list of dicts; each dict must have ``location`` with ``lat`` and
    ``long``. This pins what the service consumes.
    """
    driver, session = _mock_driver(
        rows=[
            {
                "display_label": "HQ-Madrid",
                "visible_node_count": 1,
                "visible_link_count": 0,
                "nodes": [
                    {
                        "id": "ci-1",
                        "display_label": "ci-1",
                        "kind": "CI",
                        "ci_type": "router",
                        "allowed_public_axes": [],
                        "location": {"lat": 40.4168, "long": -3.7038},
                    }
                ],
                "links": [],
                "has_more": False,
            }
        ]
    )
    monkeypatch.setattr(graph_lod_repo, "get_db", lambda: driver)

    row = graph_lod_repo.aggregate_detail_subgraph(
        cluster_id="location:HQ-Madrid",
        allowed_locations=["HQ-Madrid"],
        is_admin=False,
    )
    assert row is not None
    assert len(row["nodes"]) == 1
    assert row["nodes"][0]["location"] == {"lat": 40.4168, "long": -3.7038}