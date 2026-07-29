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


# ---------------------------------------------------------------------------
# P0 (fix #416) — current_cycle_parent_candidates
#
# Pure helper that enumerates the (ci_id, metric_id, event_type) tuples
# representing event-producing observations in the current cycle. It is the
# in-memory complement to ``build_open_parent_index`` (vocabulary) — same
# "what is a candidate that could become ROOT" intent, but with no Neo4j
# I/O so it can be unit-tested without a driver.
#
# Coverage: REQ-002 (order-independence) and REQ-005 (safe independent-ROOT
# behavior when the lookup is unavailable). SCN-006 (no parent relationship)
# and SCN-007 (non-propagating metric) manifest as "the observation IS a
# candidate" because the helper has no topology index to filter against.
# ---------------------------------------------------------------------------


def _obs(node_id, metric_id, event_type, **extra):
    """Build a minimal event-producing observation row."""
    row = {
        "node_id": node_id,
        "metric_id": metric_id,
        "event_type": event_type,
    }
    row.update(extra)
    return row


def test_current_cycle_parent_candidates_empty_observations_returns_empty_set():
    """No observations → empty candidate set, no key error."""
    from repositories.topology_repo import current_cycle_parent_candidates

    assert current_cycle_parent_candidates([]) == set()


def test_current_cycle_parent_candidates_returns_all_event_producing_tuples():
    """Every event-producing observation surfaces as a candidate ROOT tuple."""
    from repositories.topology_repo import current_cycle_parent_candidates

    observations = [
        _obs("ci-A", "cpu-load", "COLLECTION_FAILURE"),
        _obs("ci-B", "ping", "AVAILABILITY"),
        _obs("ci-C", "icmp_latency_ms", "THRESHOLD_BREACH"),
    ]

    result = current_cycle_parent_candidates(observations)

    assert result == {
        ("ci-A", "cpu-load", "COLLECTION_FAILURE"),
        ("ci-B", "ping", "AVAILABILITY"),
        ("ci-C", "icmp_latency_ms", "THRESHOLD_BREACH"),
    }


def test_current_cycle_parent_candidates_dedupes_identical_triples():
    """Two observations for the same (ci, metric, event_type) collapse to one candidate."""
    from repositories.topology_repo import current_cycle_parent_candidates

    observations = [
        _obs("ci-A", "cpu-load", "COLLECTION_FAILURE"),
        _obs("ci-A", "cpu-load", "COLLECTION_FAILURE"),
    ]

    result = current_cycle_parent_candidates(observations)

    assert result == {("ci-A", "cpu-load", "COLLECTION_FAILURE")}


def test_current_cycle_parent_candidates_skips_rows_without_event_type():
    """Rows without event_type are not event-producing — skip them (REQ-002)."""
    from repositories.topology_repo import current_cycle_parent_candidates

    observations = [
        _obs("ci-A", "cpu-load", None),
        _obs("ci-B", "ping", "AVAILABILITY"),
    ]

    result = current_cycle_parent_candidates(observations)

    assert ("ci-A", "cpu-load", None) not in result
    assert ("ci-B", "ping", "AVAILABILITY") in result


def test_current_cycle_parent_candidates_skips_rows_missing_node_or_metric():
    """Rows missing (node_id, metric_id) cannot form a cache key — skip them."""
    from repositories.topology_repo import current_cycle_parent_candidates

    observations = [
        {"node_id": None, "metric_id": "cpu-load", "event_type": "COLLECTION_FAILURE"},
        {"node_id": "ci-A", "metric_id": None, "event_type": "COLLECTION_FAILURE"},
        {"node_id": "", "metric_id": "cpu-load", "event_type": "COLLECTION_FAILURE"},
        _obs("ci-B", "cpu-load", "COLLECTION_FAILURE"),
    ]

    result = current_cycle_parent_candidates(observations)

    assert ("ci-B", "cpu-load", "COLLECTION_FAILURE") in result
    assert len(result) == 1


def test_current_cycle_parent_candidates_order_independent():
    """REQ-002: any order of observations produces the same candidate set."""
    from repositories.topology_repo import current_cycle_parent_candidates

    forward = [
        _obs("ci-A", "cpu-load", "COLLECTION_FAILURE"),
        _obs("ci-B", "ping", "AVAILABILITY"),
        _obs("ci-C", "icmp_latency_ms", "THRESHOLD_BREACH"),
    ]
    reverse = list(reversed(forward))
    interleaved = [forward[0], forward[2], forward[1], forward[0], forward[1]]

    assert current_cycle_parent_candidates(forward) == current_cycle_parent_candidates(reverse)
    assert current_cycle_parent_candidates(forward) == current_cycle_parent_candidates(interleaved)


def test_current_cycle_parent_candidates_never_raises_on_malformed_observations():
    """REQ-005: malformed rows must be silently dropped, not raised."""
    from repositories.topology_repo import current_cycle_parent_candidates

    bad = [
        None,
        {},
        {"node_id": 123, "metric_id": "cpu-load", "event_type": "COLLECTION_FAILURE"},
        _obs("ci-A", "cpu-load", "COLLECTION_FAILURE"),
    ]

    result = current_cycle_parent_candidates(bad)  # type: ignore[arg-type]

    assert ("ci-A", "cpu-load", "COLLECTION_FAILURE") in result


def test_current_cycle_parent_candidates_is_pure_no_session_argument():
    """REQ-002: signature MUST NOT take a Neo4j session (pure helper)."""
    import inspect

    from repositories.topology_repo import current_cycle_parent_candidates

    sig = inspect.signature(current_cycle_parent_candidates)
    params = list(sig.parameters.values())
    # First parameter is the observations list; there is NO Neo4j session.
    assert params[0].name == "observations"
    assert len(params) == 1

