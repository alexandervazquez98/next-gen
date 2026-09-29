"""Repo-layer severity count aggregation (#524).

The Cypher in ``graph_lod_repo._build_query`` is extended to join
``(n)-[:HAS_EVENT]->(e:Event)`` and aggregate per-cluster:

- ``critical_count`` — count of active events with severity='CRITICAL'.
- ``warning_count`` — count of active events with severity='WARNING'.
- ``event_count`` — count of all active events.

Active = ``status IN ['OPEN', 'ACK']``. RECOVERED and CLOSED events
are EXCLUDED — they don't drive the Geo View's color encoding (the
Geo View marks a CI OK when its underlying condition clears).

REQ-9 sensitivity policy: the join is at the cluster aggregate level,
never per-CI. The Cypher returns cluster totals; per-CI severity is
never disclosed via this endpoint.
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
# Cypher shape — the query must join :Event and aggregate severity counts
# ---------------------------------------------------------------------------


def test_aggregation_query_joins_event_label_via_has_event(monkeypatch):
    """The Cypher must traverse ``(n:CI)-[:HAS_EVENT]->(e:Event)`` so it can
    aggregate per-cluster severity counts."""
    driver, session = _mock_driver()
    monkeypatch.setattr(graph_lod_repo, "get_db", lambda: driver)

    graph_lod_repo.aggregate_overview_clusters(allowed_locations=["HQ-Madrid"], is_admin=False)

    query = session.run.call_args.args[0]
    assert ":HAS_EVENT" in query
    assert ":Event" in query


def test_aggregation_query_filters_active_events_only(monkeypatch):
    """Only OPEN + ACK events drive severity counts. RECOVERED + CLOSED
    events are excluded so the cluster color reflects the live state."""
    driver, session = _mock_driver()
    monkeypatch.setattr(graph_lod_repo, "get_db", lambda: driver)

    graph_lod_repo.aggregate_overview_clusters(allowed_locations=["HQ-Madrid"], is_admin=False)

    query = session.run.call_args.args[0]
    # The WHERE clause must filter on event status.
    assert "e.status" in query
    assert "OPEN" in query
    assert "ACK" in query
    # RECOVERED must NOT appear in the status filter list (would inflate
    # counts on clusters whose underlying conditions already cleared).
    assert "RECOVERED" not in query


def test_aggregation_query_returns_severity_count_fields(monkeypatch):
    """The RETURN clause must project critical_count, warning_count, event_count."""
    driver, session = _mock_driver()
    monkeypatch.setattr(graph_lod_repo, "get_db", lambda: driver)

    graph_lod_repo.aggregate_overview_clusters(allowed_locations=["HQ-Madrid"], is_admin=False)

    query = session.run.call_args.args[0]
    assert "critical_count" in query
    assert "warning_count" in query
    assert "event_count" in query


def test_aggregation_query_uses_severity_predicate(monkeypatch):
    """The aggregation must branch on severity='CRITICAL' / 'WARNING'."""
    driver, session = _mock_driver()
    monkeypatch.setattr(graph_lod_repo, "get_db", lambda: driver)

    graph_lod_repo.aggregate_overview_clusters(allowed_locations=["HQ-Madrid"], is_admin=False)

    query = session.run.call_args.args[0]
    assert "CRITICAL" in query
    assert "WARNING" in query


def test_aggregation_query_aggregates_centroid(monkeypatch):
    """#524 — the Cypher must aggregate n.location.lat / n.location.long
    via avg() so the Geo View can place cluster markers on the map.
    The service layer applies safe_geo_precision rounding; the repo
    just returns the unrounded averages."""
    driver, session = _mock_driver()
    monkeypatch.setattr(graph_lod_repo, "get_db", lambda: driver)

    graph_lod_repo.aggregate_overview_clusters(allowed_locations=["HQ-Madrid"], is_admin=False)

    query = session.run.call_args.args[0]
    assert "avg(n.location.lat)" in query
    assert "avg(n.location.long)" in query
    assert "centroid_lat" in query
    assert "centroid_long" in query


def test_admin_query_also_aggregates_severity(monkeypatch):
    """Admin path (no visible-set WHERE) must still aggregate severity counts."""
    driver, session = _mock_driver()
    monkeypatch.setattr(graph_lod_repo, "get_db", lambda: driver)

    graph_lod_repo.aggregate_overview_clusters(allowed_locations=None, is_admin=True)

    query = session.run.call_args.args[0]
    assert ":HAS_EVENT" in query
    assert "critical_count" in query
    assert "warning_count" in query
    assert "event_count" in query


# ---------------------------------------------------------------------------
# Pass-through — the repo rows flow into OverviewCluster unchanged
# ---------------------------------------------------------------------------


def test_repo_returns_severity_count_fields_from_db(monkeypatch):
    """When Neo4j returns rows with severity_count fields, the repo must
    include them in the dict returned to the caller (no field stripping)."""
    repo_rows = [
        {
            "cluster_id": "location:HQ-Madrid",
            "display_label": "HQ-Madrid",
            "visible_node_count": 42,
            "visible_link_count": 17,
            "aggregate_redacted": False,
            "suppression_reason": None,
            "critical_count": 3,
            "warning_count": 5,
            "event_count": 11,
        },
        {
            "cluster_id": "location:DC-East",
            "display_label": "DC-East",
            "visible_node_count": 8,
            "visible_link_count": 0,
            "aggregate_redacted": False,
            "suppression_reason": None,
            "critical_count": 0,
            "warning_count": 2,
            "event_count": 2,
        },
    ]
    driver, session = _mock_driver(rows=repo_rows)
    monkeypatch.setattr(graph_lod_repo, "get_db", lambda: driver)

    result = graph_lod_repo.aggregate_overview_clusters(
        allowed_locations=None, is_admin=True
    )

    assert len(result) == 2
    by_id = {row["cluster_id"]: row for row in result}
    assert by_id["location:HQ-Madrid"]["critical_count"] == 3
    assert by_id["location:HQ-Madrid"]["warning_count"] == 5
    assert by_id["location:HQ-Madrid"]["event_count"] == 11
    assert by_id["location:DC-East"]["critical_count"] == 0
    assert by_id["location:DC-East"]["warning_count"] == 2
    assert by_id["location:DC-East"]["event_count"] == 2


def test_repo_handles_missing_severity_count_fields(monkeypatch):
    """Additive change: if an older query (or a partial Neo4j row) omits
    the severity_count fields, the repo still returns the row without
    raising. The schema defaults kick in (0)."""
    repo_rows = [
        {
            "cluster_id": "location:HQ-Madrid",
            "display_label": "HQ-Madrid",
            "visible_node_count": 5,
            "visible_link_count": 0,
            "aggregate_redacted": False,
            "suppression_reason": None,
            # No critical_count, warning_count, event_count.
        },
    ]
    driver, session = _mock_driver(rows=repo_rows)
    monkeypatch.setattr(graph_lod_repo, "get_db", lambda: driver)

    result = graph_lod_repo.aggregate_overview_clusters(
        allowed_locations=None, is_admin=True
    )

    assert len(result) == 1
    # The repo passes through whatever Neo4j returns; missing keys are not
    # the repo's concern (the service layer / schema apply defaults).
    assert "critical_count" not in result[0]
    assert "warning_count" not in result[0]
    assert "event_count" not in result[0]
