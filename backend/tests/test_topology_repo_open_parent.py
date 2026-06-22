"""Tests for build_open_parent_index — batched open-parent cache (Task 1).

Strict TDD: these tests were written FIRST and drove the implementation of
``repositories.topology_repo.build_open_parent_index``.

The function mirrors ``find_open_parent_event`` but batches the work: it takes a
set of ``(ci_id, metric_id)`` pairs and returns a dict keyed by the same pair.
Non-propagating metrics (``MetricDef.can_propagate = false``) are filtered INSIDE
the Cypher at cache-build time (design C2 fix) — they never appear as keys.
"""

from __future__ import annotations

from unittest.mock import patch

from repositories.topology_repo import build_open_parent_index


class _FakeResult:
    """Mimics the neo4j Result object enough for build_open_parent_index."""

    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    """Captures the Cypher + params and returns a canned result list."""

    def __init__(self, rows):
        self._rows = rows
        self.last_query = ""
        self.last_params: dict = {}

    def run(self, query, **params):
        self.last_query = query
        self.last_params = params
        return _FakeResult(self._rows)


def _row(ci_id, metric_id, parent_event_id=None, root_cause_ci_id=None, parent_ci_id=None):
    return {
        "ci_id": ci_id,
        "metric_id": metric_id,
        "parent_event_id": parent_event_id,
        "parent_ci_id": parent_ci_id,
        "root_cause_ci_id": root_cause_ci_id,
    }


def test_build_open_parent_index_returns_parent_for_propagating_metric():
    """One (ci, metric) pair with an OPEN parent via DEPENDS_ON → hit."""
    session = _FakeSession([
        _row("ci-E", "cpu-load", parent_event_id="evt-A", root_cause_ci_id="ci-A", parent_ci_id="ci-A"),
    ])

    result = build_open_parent_index(session, {("ci-E", "cpu-load")})

    assert result[("ci-E", "cpu-load")] == {
        "parent_event_id": "evt-A",
        "root_cause_ci_id": "ci-A",
        "correlation_type": "PROPAGATED",
    }


def test_build_open_parent_index_skips_can_propagate_false():
    """Metric with can_propagate=false is ABSENT from the result dict (C2).

    The Cypher-side ``WHERE coalesce(m.can_propagate, true) = true`` filter means
    the DB never returns a row for that pair, so the key is missing → ROOT.
    """
    session = _FakeSession([])  # query filtered the pair out, no rows returned

    result = build_open_parent_index(session, {("ci-E", "cpu-noisy")})

    assert ("ci-E", "cpu-noisy") not in result


def test_build_open_parent_index_keys_by_ci_metric_pair():
    """Same CI, two metrics with different parents → two independent keys."""
    session = _FakeSession([
        _row("ci-E", "cpu-load", parent_event_id="evt-A", root_cause_ci_id="ci-A", parent_ci_id="ci-A"),
        _row("ci-E", "mem-load", parent_event_id="evt-B", root_cause_ci_id="ci-B", parent_ci_id="ci-B"),
    ])

    result = build_open_parent_index(session, {("ci-E", "cpu-load"), ("ci-E", "mem-load")})

    assert result[("ci-E", "cpu-load")]["parent_event_id"] == "evt-A"
    assert result[("ci-E", "mem-load")]["parent_event_id"] == "evt-B"


def test_build_open_parent_index_respects_max_depth_3():
    """Parent beyond depth 3 → absent. The Cypher uses *1..3."""
    session = _FakeSession([])  # no parent within depth 3

    result = build_open_parent_index(session, {("ci-E", "cpu-load")})

    assert ("ci-E", "cpu-load") not in result


def test_build_open_parent_index_traverses_connects_to():
    """Open parent reachable only via CONNECTS_TO → hit.

    The query must include CONNECTS_TO in the relationship traversal, mirroring
    find_open_parent_event.
    """
    session = _FakeSession([
        _row("ci-E", "cpu-load", parent_event_id="evt-A", root_cause_ci_id="ci-A", parent_ci_id="ci-A"),
    ])

    result = build_open_parent_index(session, {("ci-E", "cpu-load")})

    # Verify the Cypher traverses CONNECTS_TO alongside DEPENDS_ON/HOSTED_ON
    assert "CONNECTS_TO" in session.last_query
    assert "DEPENDS_ON" in session.last_query
    assert "HOSTED_ON" in session.last_query
    assert result[("ci-E", "cpu-load")]["parent_event_id"] == "evt-A"


def test_build_open_parent_index_filters_can_propagate_in_cypher():
    """The Cypher must apply the WHERE coalesce(m.can_propagate, true) = true filter (C2)."""
    session = _FakeSession([])

    build_open_parent_index(session, {("ci-E", "cpu-load")})

    assert "coalesce(m.can_propagate, true) = true" in session.last_query


def test_build_open_parent_index_uses_depth_3_in_cypher():
    """The Cypher must walk *1..3 (mirror find_open_parent_event default)."""
    session = _FakeSession([])

    build_open_parent_index(session, {("ci-E", "cpu-load")})

    assert "*1..3" in session.last_query


def test_build_open_parent_index_empty_input_returns_empty_dict():
    """Empty pairs → empty dict, no query round-trip semantics issue."""
    session = _FakeSession([])

    result = build_open_parent_index(session, set())

    assert result == {}


def test_build_open_parent_index_prefers_critical_over_warning():
    """ORDER BY severity mirrors find_open_parent_event — CRITICAL wins."""
    session = _FakeSession([
        # First row in DB order is WARNING, but query ORDER BY should surface CRITICAL.
        # Here we simulate the DB already returning the CRITICAL one first (post-ORDER BY).
        _row("ci-E", "cpu-load", parent_event_id="evt-crit", root_cause_ci_id="ci-A", parent_ci_id="ci-A"),
    ])

    result = build_open_parent_index(session, {("ci-E", "cpu-load")})

    assert "CASE pe.severity" in session.last_query or "CASE parent.severity" in session.last_query
    assert result[("ci-E", "cpu-load")]["parent_event_id"] == "evt-crit"
