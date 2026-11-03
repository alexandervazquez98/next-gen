"""Status-aware PhysicalLink traversal for the correlation cache (feat-539 / T3).

Strict TDD: these tests were written FIRST and drove the implementation of the
status-gated PhysicalLink traversal in ``repositories.topology_repo``.

Locked traversal contract (issue #539 — spec S1/S2/S8, task T3):

* A PhysicalLink crossing is ONE logical hop:
  ``(ci)-[:CONNECTED_VIA]->(pl:PhysicalLink)<-[:CONNECTED_VIA]-(peer:CI)``.
* The crossing may sit at ANY logical position inside the depth-3 budget.
* ``pl.status`` is read in the SAME statement and only the statuses published
  by ``services.correlation_propagation_contract`` propagate.
* A direct CI→CI ``CONNECTED_VIA`` seed edge never matches — the
  ``:PhysicalLink`` intermediate is mandatory.
* PhysicalLink ids never enter the CI adjacency.

The assertions below are behavioural: a small in-memory graph is walked with
the SAME logical-position variants the repository renders, and the fake session
asserts that the rendered query really carries those variants. A regression in
the traversal shape therefore fails the test instead of silently changing the
query text.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import patch

import pytest
from repositories.topology_repo import (
    CORRELATION_MAX_DEPTH,
    build_cycle_parent_index,
    build_open_parent_index,
    correlation_path_variants,
    find_open_parent_event,
    get_topology_relations,
)
from services.correlation_propagation_contract import propagating_physical_link_statuses

_CI_RELATIONSHIP_TYPES = ("DEPENDS_ON", "HOSTED_ON", "CONNECTS_TO")
_SEVERITY_ORDER = {"CRITICAL": 1, "WARNING": 2}


class _Graph:
    """Minimal in-memory graph used to simulate the Neo4j traversal."""

    def __init__(self) -> None:
        self._relationships: dict[str, list[tuple[str, str]]] = {}
        self._links: dict[str, dict[str, Any]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._metrics: dict[str, dict[str, Any]] = {}
        self.ci_ids: set[str] = set()

    # -- graph construction -------------------------------------------------
    def add_ci(self, ci_id: str) -> str:
        self.ci_ids.add(ci_id)
        return ci_id

    def add_ci_relationship(self, source: str, target: str, rel_type: str = "DEPENDS_ON") -> None:
        self.add_ci(source)
        self.add_ci(target)
        self._relationships.setdefault(source, []).append((target, rel_type))

    def add_physical_link(
        self,
        link_id: str,
        endpoint_a: str,
        endpoint_b: str,
        status: str = "UP",
    ) -> None:
        self.add_ci(endpoint_a)
        self.add_ci(endpoint_b)
        self._links[link_id] = {"status": status, "endpoints": (endpoint_a, endpoint_b)}

    def add_event(
        self,
        ci_id: str,
        event_id: str,
        *,
        status: str = "OPEN",
        severity: str = "CRITICAL",
        created_at: int = 1,
        root_cause_ci_id: str | None = None,
        correlation_type: str = "ROOT",
    ) -> None:
        self.add_ci(ci_id)
        self._events.setdefault(ci_id, []).append(
            {
                "id": event_id,
                "status": status,
                "severity": severity,
                "created_at": created_at,
                "root_cause_ci_id": root_cause_ci_id,
                "correlation_type": correlation_type,
            }
        )

    def add_metric(self, metric_id: str, *, can_propagate: bool = True) -> None:
        self._metrics[metric_id] = {"can_propagate": can_propagate}

    # -- traversal helpers --------------------------------------------------
    def ci_peers(self, ci_id: str) -> list[str]:
        """CI peers reachable over the pre-#539 relationship vocabulary."""
        return [
            target
            for target, rel_type in self._relationships.get(ci_id, [])
            if rel_type in _CI_RELATIONSHIP_TYPES
        ]

    def link_peers(self, ci_id: str) -> list[tuple[str, str, str]]:
        """Peers reachable through a PhysicalLink, in either endpoint direction."""
        peers: list[tuple[str, str, str]] = []
        for link_id, link in self._links.items():
            endpoint_a, endpoint_b = link["endpoints"]
            if ci_id == endpoint_a:
                peers.append((endpoint_b, link_id, link["status"]))
            elif ci_id == endpoint_b:
                peers.append((endpoint_a, link_id, link["status"]))
        return peers

    def open_events(self, ci_id: str) -> list[dict[str, Any]]:
        return [
            event for event in self._events.get(ci_id, []) if event["status"] in ("OPEN", "ACK")
        ]

    def metric_can_propagate(self, metric_id: str) -> bool:
        return bool(self._metrics.get(metric_id, {}).get("can_propagate", True))


def _enumerate_paths(
    graph: _Graph,
    ci_id: str,
    allowed_statuses: set[str],
    max_depth: int = CORRELATION_MAX_DEPTH,
) -> list[tuple[tuple[str, ...], tuple[str | None, str | None]]]:
    """Enumerate every traversal path that starts at ``ci_id``.

    A path is the tuple of CI ids it visits (one entry per logical hop) plus
    the ``(link_id, link_status)`` of the PhysicalLink crossing it used, or
    ``(None, None)`` for a pure-CI path. At most ONE crossing per path — that
    is the shape the repository's logical-position variants express.
    """
    paths: list[tuple[tuple[str, ...], tuple[str | None, str | None]]] = []

    def _walk(node: str, chain: list[str], link_meta: tuple[str | None, str | None]) -> None:
        if chain:
            paths.append((tuple(chain), link_meta))
        if len(chain) >= max_depth:
            return
        for peer in graph.ci_peers(node):
            _walk(peer, chain + [peer], link_meta)
        if link_meta[0] is None:
            for peer, link_id, status in graph.link_peers(node):
                if status in allowed_statuses:
                    _walk(peer, chain + [peer], (link_id, status))

    _walk(ci_id, [], (None, None))
    # The sort key must be TOTAL-ORDERED: two paths can visit the same CI chain
    # (one purely, one through a PhysicalLink), and their link metadata tuples
    # start with ``None`` on the pure path. Comparing ``None`` against a str
    # raises TypeError, so the nullable metadata is normalised to "".
    paths.sort(
        key=lambda item: (
            len(item[0]),
            item[0],
            item[1][0] or "",
            item[1][1] or "",
        )
    )
    return paths


class _FakeResult:
    """Mimics the neo4j Result object."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def single(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _GraphSession:
    """Fake Neo4j session that evaluates the correlation traversal queries.

    The session walks the in-memory graph with the SAME logical-position
    variants the repository renders and asserts that the rendered query
    actually carries them, so a drift between the traversal model and the
    emitted Cypher fails the test.
    """

    def __init__(self, graph: _Graph) -> None:
        self.graph = graph
        self.queries: list[dict[str, Any]] = []

    def __enter__(self) -> _GraphSession:
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def run(self, query: str, **params: Any) -> _FakeResult:
        self.queries.append({"query": query, "params": params})
        self._assert_query_contract(query, params)
        allowed = set(params.get("propagating_link_statuses") or ())
        if "$pairs" in query:
            return _FakeResult(self._index_rows(params, allowed))
        if "$ci_ids" in query:
            return _FakeResult(self._relation_rows(params, allowed))
        return _FakeResult(self._single_rows(params, allowed))

    # -- query contract ----------------------------------------------------
    def _assert_query_contract(self, query: str, params: dict[str, Any]) -> None:
        match = re.search(r"\*1\.\.(\d+)", query)
        depth = int(match.group(1)) if match else CORRELATION_MAX_DEPTH
        for variant in correlation_path_variants(depth):
            assert variant.pattern in query, f"query is missing variant: {variant.pattern}"
        assert "pl.status IN $propagating_link_statuses" in query
        assert params.get("propagating_link_statuses") == propagating_physical_link_statuses()

    # -- simulated results --------------------------------------------------
    def _best_event(self, ci_id: str) -> dict[str, Any] | None:
        events = self.graph.open_events(ci_id)
        if not events:
            return None
        return sorted(
            events,
            key=lambda event: (
                _SEVERITY_ORDER.get(event["severity"], 3),
                event["created_at"],
                event["id"],
            ),
        )[0]

    def _parent_candidates(
        self, ci_id: str, allowed: set[str]
    ) -> list[tuple[int, int, str, str, dict[str, Any], tuple[str | None, str | None]]]:
        candidates = []
        for chain, link_meta in _enumerate_paths(self.graph, ci_id, allowed):
            parent_ci_id = chain[-1]
            event = self._best_event(parent_ci_id)
            if event is None:
                continue
            candidates.append(
                (
                    _SEVERITY_ORDER.get(event["severity"], 3),
                    event["created_at"],
                    parent_ci_id,
                    event["id"],
                    event,
                    link_meta,
                )
            )
        candidates.sort(key=lambda item: item[:4])
        return candidates

    def _single_rows(self, params: dict[str, Any], allowed: set[str]) -> list[dict[str, Any]]:
        candidates = self._parent_candidates(params["ci_id"], allowed)
        if not candidates:
            return []
        _, _, parent_ci_id, _, event, link_meta = candidates[0]
        return [
            {
                "parent_event_id": event["id"],
                "parent_ci_id": parent_ci_id,
                "correlation_type": event["correlation_type"],
                "root_cause_ci_id": event["root_cause_ci_id"] or parent_ci_id,
                "link_id": link_meta[0],
                "link_status": link_meta[1],
            }
        ]

    def _index_rows(self, params: dict[str, Any], allowed: set[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for pair in params["pairs"]:
            metric_id = pair["metric_id"]
            if not self.graph.metric_can_propagate(metric_id):
                continue
            candidates = self._parent_candidates(pair["ci_id"], allowed)
            if not candidates:
                continue
            _, _, parent_ci_id, _, event, link_meta = candidates[0]
            rows.append(
                {
                    "ci_id": pair["ci_id"],
                    "metric_id": metric_id,
                    "parent_event_id": event["id"],
                    "parent_ci_id": parent_ci_id,
                    "root_cause_ci_id": event["root_cause_ci_id"] or parent_ci_id,
                    "correlation_type": event["correlation_type"],
                    "link_id": link_meta[0],
                    "link_status": link_meta[1],
                }
            )
        return rows

    def _relation_rows(self, params: dict[str, Any], allowed: set[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for ci_id in params["ci_ids"]:
            for chain, _link_meta in _enumerate_paths(self.graph, ci_id, allowed):
                path = (ci_id, *chain)
                for index in range(len(path) - 1):
                    edge = (path[index], path[index + 1])
                    if edge in seen:
                        continue
                    seen.add(edge)
                    rows.append({"source_ci_id": edge[0], "parent_ci_id": edge[1]})
        return rows


class _FakeDriver:
    """Minimal driver that hands out the fake session."""

    def __init__(self, session: _GraphSession) -> None:
        self._session = session

    def session(self) -> _GraphSession:
        return self._session


def _obs(node_id: str, metric_id: str, event_type: str = "COLLECTION_FAILURE") -> dict[str, Any]:
    return {"node_id": node_id, "metric_id": metric_id, "event_type": event_type}


# ---------------------------------------------------------------------------
# Logical-position variants (the shared traversal model)
# ---------------------------------------------------------------------------


class TestCorrelationPathVariants:
    """The traversal is expressed as explicit logical-position variants."""

    def test_variants_cover_the_link_at_every_logical_position(self):
        positions = {
            variant.link_position
            for variant in correlation_path_variants(3)
            if variant.link_position is not None
        }

        assert positions == {1, 2, 3}

    def test_link_variant_positions_are_one_based_logical_positions(self):
        for variant in correlation_path_variants(3):
            if variant.link_position is None:
                continue
            hops = variant.hops
            assert hops[variant.link_position - 1] == "link"
            assert hops.count("link") == 1

    def test_link_crossing_costs_exactly_one_logical_hop(self):
        for variant in correlation_path_variants(3):
            if variant.link_position is None:
                continue
            assert len(variant.hops) == variant.total_hops
            assert variant.total_hops <= CORRELATION_MAX_DEPTH

    def test_pure_ci_variant_is_preserved(self):
        pure = [v for v in correlation_path_variants(3) if v.link_position is None]

        assert len(pure) == 1
        assert pure[0].pattern == ("(ci)-[:DEPENDS_ON|HOSTED_ON|CONNECTS_TO*1..3]->(parent:CI)")

    def test_every_variant_renders_the_physical_link_label(self):
        for variant in correlation_path_variants(3):
            if variant.link_position is None:
                continue
            assert ":PhysicalLink" in variant.pattern
            assert "CONNECTED_VIA" in variant.pattern


# ---------------------------------------------------------------------------
# Link crossing at every logical position propagates to an OPEN/ACK parent
# ---------------------------------------------------------------------------


class TestPhysicalLinkCrossingPositions:
    def test_link_at_logical_position_one_propagates(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UP")
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)

        result = build_open_parent_index(session, {("ci-child", "cpu-load")})

        entry = result[("ci-child", "cpu-load")]
        assert entry["parent_event_id"] == "evt-parent"
        assert entry["root_cause_ci_id"] == "ci-parent"
        assert entry["link_id"] == "pl-1"
        assert entry["link_status"] == "UP"

    def test_link_at_logical_position_two_propagates(self):
        graph = _Graph()
        graph.add_ci_relationship("ci-child", "ci-mid")
        graph.add_physical_link("pl-1", "ci-mid", "ci-parent", status="UP")
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)

        result = build_open_parent_index(session, {("ci-child", "cpu-load")})

        entry = result[("ci-child", "cpu-load")]
        assert entry["parent_event_id"] == "evt-parent"
        assert entry["link_id"] == "pl-1"

    def test_link_at_logical_position_three_propagates(self):
        graph = _Graph()
        graph.add_ci_relationship("ci-child", "ci-mid-1")
        graph.add_ci_relationship("ci-mid-1", "ci-mid-2")
        graph.add_physical_link("pl-1", "ci-mid-2", "ci-parent", status="UP")
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)

        result = build_open_parent_index(session, {("ci-child", "cpu-load")})

        entry = result[("ci-child", "cpu-load")]
        assert entry["parent_event_id"] == "evt-parent"
        assert entry["link_id"] == "pl-1"

    def test_link_beyond_the_depth_budget_does_not_propagate(self):
        graph = _Graph()
        graph.add_ci_relationship("ci-child", "ci-mid-1")
        graph.add_ci_relationship("ci-mid-1", "ci-mid-2")
        graph.add_ci_relationship("ci-mid-2", "ci-mid-3")
        graph.add_physical_link("pl-1", "ci-mid-3", "ci-parent", status="UP")
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)

        result = build_open_parent_index(session, {("ci-child", "cpu-load")})

        assert ("ci-child", "cpu-load") not in result

    def test_link_crossing_costs_one_hop_not_two(self):
        """endpoint→PhysicalLink←endpoint is ONE logical hop.

        The parent is two edges away but only ONE logical hop, so it is still
        inside the depth-3 budget.
        """
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UP")
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)

        result = build_open_parent_index(session, {("ci-child", "cpu-load")})

        assert result[("ci-child", "cpu-load")]["parent_event_id"] == "evt-parent"


# ---------------------------------------------------------------------------
# Status gate
# ---------------------------------------------------------------------------


class TestPhysicalLinkStatusGate:
    @pytest.mark.parametrize("status", ["UP", "UNKNOWN"])
    def test_propagating_statuses_propagate(self, status):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status=status)
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)

        result = build_open_parent_index(session, {("ci-child", "cpu-load")})

        assert result[("ci-child", "cpu-load")]["parent_event_id"] == "evt-parent"
        assert result[("ci-child", "cpu-load")]["link_status"] == status

    @pytest.mark.parametrize("status", ["DOWN", "PLANNED"])
    def test_blocking_statuses_do_not_propagate(self, status):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status=status)
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)

        result = build_open_parent_index(session, {("ci-child", "cpu-load")})

        assert ("ci-child", "cpu-load") not in result

    def test_status_is_read_in_the_same_statement(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UP")
        session = _GraphSession(graph)

        build_open_parent_index(session, {("ci-child", "cpu-load")})

        query = session.queries[0]["query"]
        assert "pl.status IN $propagating_link_statuses" in query
        assert "pl.id AS link_id" in query
        assert "pl.status AS link_status" in query

    def test_allowed_status_set_comes_from_the_contract_module(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UP")
        session = _GraphSession(graph)

        build_open_parent_index(session, {("ci-child", "cpu-load")})

        params = session.queries[0]["params"]
        assert params["propagating_link_statuses"] == propagating_physical_link_statuses()
        assert params["propagating_link_statuses"] == ["UNKNOWN", "UP"]

    def test_query_does_not_duplicate_the_allowed_status_literal(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UP")
        session = _GraphSession(graph)

        build_open_parent_index(session, {("ci-child", "cpu-load")})

        query = session.queries[0]["query"]
        assert "'UP'" not in query
        assert "'UNKNOWN'" not in query


# ---------------------------------------------------------------------------
# PhysicalLink intermediate is mandatory
# ---------------------------------------------------------------------------


class TestPhysicalLinkIntermediateIsMandatory:
    def test_direct_ci_to_ci_connected_via_seed_edge_never_matches(self):
        graph = _Graph()
        graph.add_ci_relationship("ci-child", "ci-parent", "CONNECTED_VIA")
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)

        result = build_open_parent_index(session, {("ci-child", "cpu-load")})

        assert ("ci-child", "cpu-load") not in result

    def test_query_only_uses_connected_via_through_a_physical_link(self):
        graph = _Graph()
        session = _GraphSession(graph)

        build_open_parent_index(session, {("ci-child", "cpu-load")})

        query = session.queries[0]["query"]
        for fragment in re.findall(r"-\[:CONNECTED_VIA\]->.{0,40}", query):
            assert fragment.startswith("-[:CONNECTED_VIA]->(pl:PhysicalLink)")


# ---------------------------------------------------------------------------
# Either endpoint direction
# ---------------------------------------------------------------------------


class TestPhysicalLinkEndpointDirection:
    def test_link_is_traversed_from_the_first_endpoint(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UP")
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)

        result = build_open_parent_index(session, {("ci-child", "cpu-load")})

        assert result[("ci-child", "cpu-load")]["parent_event_id"] == "evt-parent"

    def test_link_is_traversed_from_the_second_endpoint(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-parent", "ci-child", status="UP")
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)

        result = build_open_parent_index(session, {("ci-child", "cpu-load")})

        assert result[("ci-child", "cpu-load")]["parent_event_id"] == "evt-parent"


# ---------------------------------------------------------------------------
# Cache metadata
# ---------------------------------------------------------------------------


class TestOpenParentIndexLinkMetadata:
    def test_link_crossing_carries_link_id_and_status(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UNKNOWN")
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)

        result = build_open_parent_index(session, {("ci-child", "cpu-load")})

        entry = result[("ci-child", "cpu-load")]
        assert entry["link_id"] == "pl-1"
        assert entry["link_status"] == "UNKNOWN"

    def test_pure_ci_entry_keeps_the_legacy_shape(self):
        graph = _Graph()
        graph.add_ci_relationship("ci-child", "ci-parent")
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)

        result = build_open_parent_index(session, {("ci-child", "cpu-load")})

        assert result[("ci-child", "cpu-load")] == {
            "parent_event_id": "evt-parent",
            "root_cause_ci_id": "ci-parent",
            "correlation_type": "PROPAGATED",
        }

    def test_pure_ci_entry_has_no_link_metadata(self):
        graph = _Graph()
        graph.add_ci_relationship("ci-child", "ci-parent")
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)

        result = build_open_parent_index(session, {("ci-child", "cpu-load")})

        entry = result[("ci-child", "cpu-load")]
        assert entry.get("link_id") is None
        assert entry.get("link_status") is None

    def test_non_propagating_metric_stays_absent(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UP")
        graph.add_event("ci-parent", "evt-parent")
        graph.add_metric("cpu-noisy", can_propagate=False)
        session = _GraphSession(graph)

        result = build_open_parent_index(session, {("ci-child", "cpu-noisy")})

        assert ("ci-child", "cpu-noisy") not in result


# ---------------------------------------------------------------------------
# find_open_parent_event — additive link metadata
# ---------------------------------------------------------------------------


class TestFindOpenParentEventLinkMetadata:
    def _run(self, graph: _Graph, ci_id: str = "ci-child", max_depth: int = 3):
        session = _GraphSession(graph)
        driver = _FakeDriver(session)
        with patch("repositories.topology_repo.get_db", return_value=driver):
            return find_open_parent_event(ci_id, max_depth=max_depth), session

    def test_link_crossing_returns_the_link_metadata(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UP")
        graph.add_event("ci-parent", "evt-parent")

        result, _session = self._run(graph)

        assert result is not None
        assert result["parent_event_id"] == "evt-parent"
        assert result["root_cause_ci_id"] == "ci-parent"
        assert result["link_id"] == "pl-1"
        assert result["link_status"] == "UP"

    def test_pure_ci_result_keeps_the_legacy_shape(self):
        graph = _Graph()
        graph.add_ci_relationship("ci-child", "ci-parent")
        graph.add_event("ci-parent", "evt-parent")

        result, _session = self._run(graph)

        assert result == {
            "parent_event_id": "evt-parent",
            "root_cause_ci_id": "ci-parent",
            "correlation_type": "ROOT",
        }

    def test_no_parent_event_returns_none(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="DOWN")

        result, _session = self._run(graph)

        assert result is None

    def test_status_gate_applies_to_the_single_event_lookup(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="PLANNED")
        graph.add_event("ci-parent", "evt-parent")

        result, _session = self._run(graph)

        assert result is None


# ---------------------------------------------------------------------------
# get_topology_relations — CI-only adjacency
# ---------------------------------------------------------------------------


class TestTopologyRelationsStayCiOnly:
    def test_link_crossing_contributes_a_ci_to_ci_edge(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UP")
        session = _GraphSession(graph)

        relations = get_topology_relations(session, {"ci-child"})

        assert relations == {"ci-child": {"ci-parent"}}

    def test_adjacency_never_exposes_a_physical_link_id(self):
        graph = _Graph()
        graph.add_physical_link("pl-secret", "ci-child", "ci-parent", status="UP")
        session = _GraphSession(graph)

        relations = get_topology_relations(session, {"ci-child"})

        flat = set(relations)
        for parents in relations.values():
            flat.update(parents)
        assert "pl-secret" not in flat
        assert flat <= graph.ci_ids

    def test_adjacency_query_never_projects_the_physical_link_id(self):
        graph = _Graph()
        session = _GraphSession(graph)

        get_topology_relations(session, {"ci-child"})

        query = session.queries[0]["query"]
        assert "pl.id" not in query

    def test_blocking_link_status_removes_the_adjacency_edge(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="DOWN")
        session = _GraphSession(graph)

        relations = get_topology_relations(session, {"ci-child"})

        assert relations == {}

    def test_link_at_position_three_keeps_the_full_edge_chain(self):
        graph = _Graph()
        graph.add_ci_relationship("ci-child", "ci-mid-1")
        graph.add_ci_relationship("ci-mid-1", "ci-mid-2")
        graph.add_physical_link("pl-1", "ci-mid-2", "ci-parent", status="UP")
        session = _GraphSession(graph)

        relations = get_topology_relations(session, {"ci-child"})

        assert relations == {
            "ci-child": {"ci-mid-1"},
            "ci-mid-1": {"ci-mid-2"},
            "ci-mid-2": {"ci-parent"},
        }

    def test_pure_ci_adjacency_is_preserved(self):
        graph = _Graph()
        graph.add_ci_relationship("ci-child", "ci-parent")
        session = _GraphSession(graph)

        relations = get_topology_relations(session, {"ci-child"})

        assert relations == {"ci-child": {"ci-parent"}}


# ---------------------------------------------------------------------------
# build_cycle_parent_index honours the link-aware adjacency
# ---------------------------------------------------------------------------


class TestCycleParentIndexHonoursLinkAwareAdjacency:
    def test_link_aware_adjacency_resolves_the_observed_ancestor(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UP")
        session = _GraphSession(graph)
        relations = get_topology_relations(session, {"ci-child"})

        observations = [
            _obs("ci-parent", "cpu-load"),
            _obs("ci-child", "cpu-load"),
        ]

        result = build_cycle_parent_index(observations, relations)

        assert result == {("ci-child", "cpu-load"): "ci-parent"}

    def test_cycle_parent_index_never_leaks_a_physical_link_id(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UP")
        session = _GraphSession(graph)
        relations = get_topology_relations(session, {"ci-child"})

        observations = [
            _obs("ci-parent", "cpu-load"),
            _obs("ci-child", "cpu-load"),
        ]

        result = build_cycle_parent_index(observations, relations)

        assert "pl-1" not in set(result.values())

    def test_blocking_link_status_keeps_the_child_independent(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="DOWN")
        session = _GraphSession(graph)
        relations = get_topology_relations(session, {"ci-child"})

        observations = [
            _obs("ci-parent", "cpu-load"),
            _obs("ci-child", "cpu-load"),
        ]

        result = build_cycle_parent_index(observations, relations)

        assert result == {}

    def test_nearest_observed_ancestor_wins_and_is_sorted(self):
        graph = _Graph()
        graph.add_ci_relationship("ci-child", "ci-mid")
        graph.add_ci_relationship("ci-child", "ci-other")
        graph.add_ci_relationship("ci-mid", "ci-root")
        graph.add_ci_relationship("ci-other", "ci-root")
        session = _GraphSession(graph)
        relations = get_topology_relations(session, {"ci-child"})

        observations = [
            _obs("ci-root", "cpu-load"),
            _obs("ci-child", "cpu-load"),
        ]

        result = build_cycle_parent_index(observations, relations)

        assert result == {("ci-child", "cpu-load"): "ci-root"}


# ---------------------------------------------------------------------------
# Dual-path resolution is deterministic (review finding MAJOR-1)
# ---------------------------------------------------------------------------


class TestDualPathResolutionPrefersTheCrossing:
    """MAJOR-1: a CI reachable BOTH purely and through a link reaches the same
    parent event twice, once with link metadata and once without.

    Before the fix the final ORDER BY had no tiebreaker, so the pure-CI row
    always won the tie and the link metadata was dropped. The consequence was
    silent: no degraded WARNING child was created for such a CI, because the
    traversal never reported the crossed link.
    """

    def test_batch_index_ordering_prefers_the_crossing_row_on_a_tie(self):
        graph = _Graph()
        graph.add_ci_relationship("ci-child", "ci-parent")
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UNKNOWN")
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)

        build_open_parent_index(session, {("ci-child", "cpu-load")})

        query = session.queries[0]["query"]
        # The tiebreaker must come AFTER the event choice (severity, created_at)
        # so a more severe event still wins over a crossing row.
        assert "link_id IS NULL ASC" in query
        assert query.index("pe.created_at ASC") < query.index("link_id IS NULL ASC")

    def test_single_lookup_ordering_prefers_the_crossing_row_on_a_tie(self):
        graph = _Graph()
        graph.add_ci_relationship("ci-child", "ci-parent")
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UNKNOWN")
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)
        driver = _FakeDriver(session)

        with patch("repositories.topology_repo.get_db", return_value=driver):
            find_open_parent_event("ci-child", max_depth=3)

        query = session.queries[0]["query"]
        assert "link_id IS NULL ASC" in query
        assert query.index("pe.created_at ASC") < query.index("link_id IS NULL ASC")


# ---------------------------------------------------------------------------
# A PROPAGATED child is never a correlation parent (review finding MAJOR-2)
# ---------------------------------------------------------------------------


class TestPropagatedEventsAreNeverCorrelationParents:
    """MAJOR-2: the traversal matched ANY OPEN/ACK event on the parent CI,
    including a degraded PROPAGATED child.

    The worker then refused to enrich a non-ROOT parent and refused to create
    a degraded child without link metadata, so the CI behind such a parent
    produced NO event at all and appeared in no ROOT's affected_ci_ids — the
    failure vanished from the operator feed.

    A correlation parent must always be a ROOT event: that is what carries the
    authoritative root cause and the blast radius.
    """

    def test_batch_index_parent_match_excludes_propagated_events(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UNKNOWN")
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)

        build_open_parent_index(session, {("ci-child", "cpu-load")})

        query = session.queries[0]["query"]
        assert "coalesce(pe.correlation_type, 'ROOT') = 'ROOT'" in query

    def test_single_lookup_parent_match_excludes_propagated_events(self):
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UNKNOWN")
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)
        driver = _FakeDriver(session)

        with patch("repositories.topology_repo.get_db", return_value=driver):
            find_open_parent_event("ci-child", max_depth=3)

        query = session.queries[0]["query"]
        assert "coalesce(pe.correlation_type, 'ROOT') = 'ROOT'" in query

    def test_a_root_event_is_still_matched(self):
        """The filter must keep every ROOT event matchable."""
        graph = _Graph()
        graph.add_physical_link("pl-1", "ci-child", "ci-parent", status="UNKNOWN")
        graph.add_event("ci-parent", "evt-parent")
        session = _GraphSession(graph)

        result = build_open_parent_index(session, {("ci-child", "cpu-load")})

        assert ("ci-child", "cpu-load") in result
