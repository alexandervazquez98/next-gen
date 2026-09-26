"""Authorization/scoping happens BEFORE aggregation (#391 PR1).

REQ-OVERVIEW-2 from ``openspec/changes/cmdb-graph-lod-runtime/specs/cmdb-graph-overview-api/spec.md``.

Hard rule: visible-set filtering is applied in the Cypher WHERE clause,
not post-aggregation. A non-admin principal without allowed_locations
must NOT trigger any database query (and must NOT receive data leaked
via aggregate counts on the full graph).
"""
from __future__ import annotations

from unittest.mock import MagicMock


def _mock_driver():
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    driver.session.return_value.__exit__.return_value = False
    session.run.return_value = []
    return driver, session


# ---------------------------------------------------------------------------
# Authorization gating — no DB hit without scope
# ---------------------------------------------------------------------------


def test_aggregate_overview_requires_visible_set_for_non_admin(monkeypatch):
    """Non-admin without allowed_locations gets empty overview; no DB hit."""
    from repositories import graph_lod_repo

    driver, session = _mock_driver()
    monkeypatch.setattr(graph_lod_repo, "get_db", lambda: driver)

    result = graph_lod_repo.aggregate_overview_clusters(
        allowed_locations=None, is_admin=False
    )

    assert result == []
    # Hard rule: no auth → no DB query, so no data can leak via timing or counts
    session.run.assert_not_called()


def test_aggregate_overview_empty_visible_set_returns_empty_for_non_admin(monkeypatch):
    """Non-admin with empty allowed_locations list also gets empty overview."""
    from repositories import graph_lod_repo

    driver, session = _mock_driver()
    monkeypatch.setattr(graph_lod_repo, "get_db", lambda: driver)

    result = graph_lod_repo.aggregate_overview_clusters(
        allowed_locations=[], is_admin=False
    )

    assert result == []
    session.run.assert_not_called()


# ---------------------------------------------------------------------------
# Visible-set filtering in the WHERE clause
# ---------------------------------------------------------------------------


def test_aggregate_overview_passes_visible_set_in_where_clause(monkeypatch):
    """The Cypher query must include the visible-set WHERE clause for non-admin."""
    from repositories import graph_lod_repo

    driver, session = _mock_driver()
    monkeypatch.setattr(graph_lod_repo, "get_db", lambda: driver)

    graph_lod_repo.aggregate_overview_clusters(
        allowed_locations=["HQ-Madrid"], is_admin=False
    )

    query = session.run.call_args.args[0]
    params = session.run.call_args.kwargs
    # Hard rule: visible-set filtering is in the WHERE clause, not post-aggregation
    assert "WHERE" in query or "where" in query.lower()
    assert "allowed_locations" in params
    assert params["allowed_locations"] == ["HQ-Madrid"]


def test_aggregate_overview_admin_skips_visibility_filter(monkeypatch):
    """Admin with is_admin=True aggregates over the entire visible graph."""
    from repositories import graph_lod_repo

    driver, session = _mock_driver()
    monkeypatch.setattr(graph_lod_repo, "get_db", lambda: driver)

    graph_lod_repo.aggregate_overview_clusters(
        allowed_locations=None, is_admin=True
    )

    query = session.run.call_args.args[0]
    params = session.run.call_args.kwargs
    # Admin path: no visible-set WHERE clause, no allowed_locations param
    assert "allowed_locations" not in params
    assert "$allowed_locations" not in query


# ---------------------------------------------------------------------------
# Pre-aggregation ordering — auth must precede any aggregation step
# ---------------------------------------------------------------------------


def test_aggregate_overview_calls_db_after_resolving_visibility(monkeypatch):
    """The repo function checks visibility BEFORE invoking session.run().

    This guards against a regression where someone moves the visibility
    filter to a post-processing step.
    """
    from repositories import graph_lod_repo

    call_log: list[str] = []

    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    driver.session.return_value.__exit__.return_value = False

    def _track_session(*args, **kwargs):
        call_log.append("session.run")
        return []

    session.run.side_effect = _track_session
    monkeypatch.setattr(graph_lod_repo, "get_db", lambda: driver)

    # Non-admin without scope → session.run is NOT called
    result = graph_lod_repo.aggregate_overview_clusters(
        allowed_locations=None, is_admin=False
    )
    assert result == []
    assert call_log == []

    # Non-admin with scope → session.run IS called
    graph_lod_repo.aggregate_overview_clusters(
        allowed_locations=["HQ-Madrid"], is_admin=False
    )
    assert call_log == ["session.run"]
