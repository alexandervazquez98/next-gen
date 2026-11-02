import re
from unittest.mock import MagicMock


class _SessionBoundResult:
    def __init__(self, rows, is_session_open):
        self._rows = rows
        self._is_session_open = is_session_open

    def __iter__(self):
        if not self._is_session_open():
            raise RuntimeError("Cannot consume Neo4j result after session is closed")
        return iter(self._rows)


class _SessionBoundDriver:
    def __init__(self, rows):
        self.session_instance = _SessionBoundSession(rows)

    def session(self):
        return self.session_instance


class _SessionBoundSession:
    def __init__(self, rows):
        self._open = False
        self._rows = rows
        self.run = MagicMock(side_effect=self._run)

    def __enter__(self):
        self._open = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self._open = False
        return False

    def _run(self, *args, **kwargs):
        return _SessionBoundResult(self._rows, lambda: self._open)


def _mock_driver():
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    driver.session.return_value.__exit__.return_value = False
    session.run.return_value = []
    return driver, session


def test_get_nodes_does_not_require_coordinates_for_admin(monkeypatch):
    from repositories import topology_repo

    driver, session = _mock_driver()
    monkeypatch.setattr(topology_repo, "get_db", lambda: driver)

    topology_repo.get_nodes(allowed_locations=None, is_admin=True)

    query = session.run.call_args.args[0]
    assert "MATCH (n:CI)" in query
    assert "n.location IS NOT NULL" not in query
    assert "n.location.latitude IS NOT NULL" not in query
    assert "n.location.longitude IS NOT NULL" not in query


def test_get_nodes_keeps_location_scope_for_non_admin(monkeypatch):
    from repositories import topology_repo

    driver, session = _mock_driver()
    monkeypatch.setattr(topology_repo, "get_db", lambda: driver)

    topology_repo.get_nodes(allowed_locations=["HQ-Madrid"], is_admin=False)

    query = session.run.call_args.args[0]
    params = session.run.call_args.kwargs
    assert "n.location_name IN $allowed_locations" in query
    assert params["allowed_locations"] == ["HQ-Madrid"]


def test_get_nodes_returns_category_icon_key_field(monkeypatch):
    from repositories import topology_repo

    driver, session = _mock_driver()
    monkeypatch.setattr(topology_repo, "get_db", lambda: driver)

    topology_repo.get_nodes(allowed_locations=None, is_admin=True)

    query = session.run.call_args.args[0]
    assert "c.icon_key as category_icon_key" in query


def test_get_nodes_consumes_neo4j_result_before_session_closes(monkeypatch):
    from repositories import topology_repo

    row = {
        "n": {"id": "ci-001", "name": "Router-01"},
        "category": "Router",
        "category_icon_key": "router",
        "metrics": [],
    }
    driver = _SessionBoundDriver([row])
    monkeypatch.setattr(topology_repo, "get_db", lambda: driver)

    result = topology_repo.get_nodes(allowed_locations=None, is_admin=True)

    assert result == [
        {
            "node": {"id": "ci-001", "name": "Router-01"},
            "category": "Router",
            "category_icon_key": "router",
            "metrics": [],
        }
    ]


def test_get_filtered_graph_data_includes_cis_without_coordinates(monkeypatch):
    from repositories import topology_repo

    driver, session = _mock_driver()
    session.run.side_effect = [
        [
            {
                "n": {"id": "ci-no-geo", "name": "Router without geo"},
                "lat": None,
                "lng": None,
                "labels": ["CI"],
                "metrics": [],
            }
        ],
        [],
    ]
    monkeypatch.setattr(topology_repo, "get_db", lambda: driver)

    nodes, links = topology_repo.get_filtered_graph_data(is_admin=True)

    node_query = session.run.call_args_list[0].args[0]
    assert "n.location IS NOT NULL" not in node_query
    assert "n.location.latitude IS NOT NULL" not in node_query
    assert nodes == [
        {
            "id": "ci-no-geo",
            "name": "Router without geo",
            "_labels": ["CI"],
            "metrics": [],
        }
    ]
    assert links == []


def test_get_filtered_graph_data_builds_valid_where_without_coordinate_filter(monkeypatch):
    from repositories import topology_repo

    driver, session = _mock_driver()
    session.run.side_effect = [[], []]
    monkeypatch.setattr(topology_repo, "get_db", lambda: driver)

    topology_repo.get_filtered_graph_data(location="HQ-Madrid", is_admin=True)

    node_query = session.run.call_args_list[0].args[0]
    assert "WHERE n.location_name IN $locations" in node_query
    assert "MATCH (n:CI)\n            AND" not in node_query
    assert session.run.call_args_list[0].kwargs["locations"] == ["HQ-Madrid"]


# ---------------------------------------------------------------------------
# Slice 1 (feat-324) — public_ip field on CI nodes
# ---------------------------------------------------------------------------


def test_node_model_accepts_valid_public_ip():
    """Slice 1 / VPN-Rel R1 / Sc 1: a Node with a valid public_ip round-trips
    through the Pydantic model unchanged."""
    from models.core import Node

    node = Node(
        id="ci-001",
        label="Hub-01",
        type="vpn_hub",
        public_ip="203.0.113.10",
    )

    assert node.public_ip == "203.0.113.10"


def test_node_model_accepts_ipv6_public_ip():
    """Slice 1 / VPN-Rel R1 / Sc 1: IPv6 addresses are also accepted by
    Python's ipaddress.ip_address validator."""
    from models.core import Node

    node = Node(
        id="ci-002",
        label="Hub-02",
        type="vpn_hub",
        public_ip="2001:db8::1",
    )

    assert node.public_ip == "2001:db8::1"


def test_node_model_rejects_invalid_public_ip():
    """Slice 1 / VPN-Rel R1 / Sc 2: invalid IP strings raise ValidationError."""
    from models.core import Node
    from pydantic import ValidationError

    try:
        Node(
            id="ci-003",
            label="Hub-03",
            type="vpn_hub",
            public_ip="not-an-ip",
        )
    except ValidationError:
        return

    raise AssertionError("Node accepted an invalid public_ip")


def test_node_model_allows_missing_public_ip():
    """Slice 1 / VPN-Rel R1 / Sc 3: public_ip is optional and defaults to None
    so existing CIs are not backfilled."""
    from models.core import Node

    node = Node(id="ci-004", label="Hub-04", type="vpn_hub")

    assert node.public_ip is None


def test_upsert_node_persists_public_ip(monkeypatch):
    """Slice 1 / VPN-Rel R1 / Sc 1: topology_repo.upsert_node persists the
    public_ip value through the Cypher SET clause."""
    from models.core import Node
    from repositories import topology_repo

    driver, session = _mock_driver()
    monkeypatch.setattr(topology_repo, "get_db", lambda: driver)

    topology_repo.upsert_node(
        Node(
            id="ci-100",
            label="Hub-100",
            type="vpn_hub",
            public_ip="198.51.100.7",
        )
    )

    query = session.run.call_args.args[0]
    params = session.run.call_args.kwargs
    assert "n.public_ip = $public_ip" in query
    assert params["public_ip"] == "198.51.100.7"


def test_upsert_node_passes_none_when_public_ip_missing(monkeypatch):
    """Slice 1 / VPN-Rel R1 / Sc 3: when public_ip is absent, the parameter is
    passed as None (no backfill)."""
    from models.core import Node
    from repositories import topology_repo

    driver, session = _mock_driver()
    monkeypatch.setattr(topology_repo, "get_db", lambda: driver)

    topology_repo.upsert_node(Node(id="ci-101", label="Hub-101", type="vpn_hub"))

    query = session.run.call_args.args[0]
    params = session.run.call_args.kwargs
    assert "n.public_ip = $public_ip" in query
    assert params["public_ip"] is None


def test_vpn_hub_layer_distinct_from_router():
    """Slice 1 / VPN-Rel R1 / Sc 1: 'vpn_hub' is accepted as a distinct layer
    value alongside 'router' (no migration required)."""
    from models.core import Node

    hub = Node(id="ci-hub", label="Hub", type="vpn_hub")
    router = Node(id="ci-rtr", label="Router", type="router")

    assert hub.type == "vpn_hub"
    assert router.type == "router"
    assert hub.type != router.type


# ---------------------------------------------------------------------------
# Slice 1 (feat-324) — public_ip validation at service layer
# ---------------------------------------------------------------------------


def test_create_update_node_rejects_invalid_public_ip(monkeypatch):
    """Slice 1 / VPN-Rel R1 / Sc 2: invalid public_ip surfaces as 400 with no
    partial persistence when the CI is saved through node_service."""
    from fastapi import HTTPException
    from models.core import Node
    from models.user import User
    from repositories import topology_repo
    from services import node_service

    user = User(
        username="admin",
        role="ADMIN",
        permissions=["CI_EDIT"],
        allowed_locations=[],
    )
    # Use model_construct to skip Pydantic's __init__ validation so we can
    # exercise the service-level guard that converts ValidationError -> 400.
    bad_node = Node.model_construct(
        id="ci-bad-ip",
        label="Hub-bad",
        type="vpn_hub",
        public_ip="not-an-ip",
    )

    # Ensure we never reach the repository on the failure path.
    def _fail(*args, **kwargs):
        raise AssertionError("repository called despite invalid public_ip")

    monkeypatch.setattr(topology_repo, "upsert_node", _fail)

    raised = False
    try:
        node_service.create_update_node(bad_node, user)
    except HTTPException as exc:
        raised = exc.status_code == 400
    assert raised, "expected HTTP 400 on invalid public_ip"


# ---------------------------------------------------------------------------
# feat-539 / S1 — canonical PhysicalLink connectivity
# ---------------------------------------------------------------------------


def _run_usage_query(monkeypatch, count=4):
    """Run ``get_node_usage`` against a mocked session and return its call data."""
    from repositories import topology_repo

    driver, session = _mock_driver()
    result = MagicMock()
    result.single.return_value = {"count": count}
    session.run.return_value = result
    monkeypatch.setattr(topology_repo, "get_db", lambda: driver)

    usage = topology_repo.get_node_usage("ci-001")

    query = " ".join(session.run.call_args.args[0].lower().split())
    params = session.run.call_args.kwargs
    return usage, query, params


def _usage_where_clause(query):
    """Extract the normalized WHERE clause of the usage query."""
    where = re.search(r"\bwhere\b(.*?)\breturn\b", query, re.DOTALL)
    assert where, "expected a WHERE clause on the usage query"
    return where.group(1).strip()


def _usage_predicate_counts(clause, params, rel_type, other_labels):
    """Evaluate the usage WHERE clause for one incident relationship.

    Supported grammar (the boolean subset used by the usage query): an
    optional ``not (...)`` wrapper around a conjunction of a relationship-type
    comparison (``type(r) = $param``) and node label checks
    (``<variable>:<Label>``). ``n`` is the anchored CI (labels ``{"CI"}``) and
    ``other`` is the matched neighbour. Any other predicate shape must extend
    this evaluator instead of silently passing.
    """
    text = clause.strip()
    negated = False
    if text.startswith("not ("):
        negated = True
        text = text[len("not (") :].rstrip()
        assert text.endswith(")"), f"unterminated NOT(...) in {clause!r}"
        text = text[:-1]
    assert " or " not in text, f"unsupported OR predicate in {clause!r}"

    variables = {"n": {"CI"}, "other": set(other_labels)}
    included = True
    for atom in re.split(r"\s+and\s+", text):
        atom = atom.strip()
        type_match = re.fullmatch(r"type\(r\)\s*=\s*\$([a-z_][a-z0-9_]*)", atom)
        if type_match:
            condition = rel_type == params[type_match.group(1)]
        else:
            label_match = re.fullmatch(r"([a-z_][a-z0-9_]*)\s*:\s*([A-Za-z_][A-Za-z0-9_]*)", atom)
            assert label_match, f"unsupported predicate atom: {atom!r}"
            variable, label = label_match.group(1), label_match.group(2)
            assert variable in variables, f"unsupported predicate variable: {variable!r}"
            # Labels are compared case-insensitively: the query text is
            # normalized to lowercase before it reaches this evaluator.
            condition = label.lower() in {known.lower() for known in variables[variable]}
        included = bool(condition) and included
    return (not included) if negated else included


def test_delete_node_removes_physical_link_listing_the_deleted_endpoint(monkeypatch):
    """Deleting an endpoint CI removes its PhysicalLink and incident edges atomically."""
    from repositories import topology_repo

    driver, session = _mock_driver()
    monkeypatch.setattr(topology_repo, "get_db", lambda: driver)

    topology_repo.delete_node("ci-001")

    assert session.run.call_count == 1
    query = " ".join(session.run.call_args.args[0].lower().split())
    assert "match (n:ci {id: $id})" in query
    assert "match (pl:physicallink)" in query
    assert "$id in pl.endpoints" in query
    assert "detach delete pl" in query
    assert "detach delete n" in query
    assert query.index("detach delete pl") < query.index("detach delete n")


def test_get_node_usage_preserves_incident_relationship_count_except_physicallink_edges(
    monkeypatch,
):
    """feat-539 / S1: usage keeps the pre-#539 "every incident relationship" count.

    Before #539 ``get_node_usage`` counted EVERY relationship incident to the
    CI (CATEGORIZED_AS, OWNED_BY, HAS_EVENT, CI<->CI links, ...). The canonical
    CI->PhysicalLink connectivity added ``CONNECTED_VIA`` edges between a CI
    and a ``:PhysicalLink`` node; those infrastructure edges are the ONLY
    relationships excluded from the public count, in both directions.
    """
    usage, query, params = _run_usage_query(monkeypatch)

    assert usage == 4
    assert params["id"] == "ci-001"

    # 1. Pre-#539 semantics: EVERY relationship incident to the CI is counted,
    #    so the matched endpoint is NOT narrowed to :CI.
    assert "match (n:ci {id: $id})-[r]-" in query
    assert "-(:ci)" not in query
    assert "count(r)" in query

    # 2. Both directions of an incident relationship are matched, so a
    #    PhysicalLink->CI edge is excluded just like a CI->PhysicalLink edge.
    assert "-[r]->" not in query
    assert "<-[r]-" not in query

    # 3. The only exclusion is a CONNECTED_VIA relationship touching a
    #    :PhysicalLink, expressed as a parameterized type check conjoined with
    #    the PhysicalLink label check.
    clause = _usage_where_clause(query)
    assert "not (" in clause
    assert ":physicallink" in clause
    type_param = re.search(r"type\(r\)\s*=\s*\$([a-z_][a-z0-9_]*)", clause)
    assert type_param, "expected a parameterized relationship-type check"
    assert params[type_param.group(1)] == "CONNECTED_VIA"
    assert re.search(
        r"type\(r\)\s*=\s*\$[a-z_][a-z0-9_]*\s+and\s+[a-z_][a-z0-9_]*:physicallink", clause
    ) or re.search(
        r"[a-z_][a-z0-9_]*:physicallink\s+and\s+type\(r\)\s*=\s*\$[a-z_][a-z0-9_]*", clause
    ), "the relationship-type check and the PhysicalLink check must be conjoined"


def test_get_node_usage_excludes_only_physicallink_connected_via_edges(monkeypatch):
    """feat-539 / S1: only the CI<->PhysicalLink infrastructure edges are dropped.

    Every other incident relationship keeps its pre-#539 contribution: the
    non-CI targets (CATEGORIZED_AS, OWNED_BY, HAS_EVENT, HAS_METRIC), the
    CI<->CI links, and even a ``CONNECTED_VIA`` edge that does not touch a
    ``:PhysicalLink``.
    """
    _, query, params = _run_usage_query(monkeypatch)
    clause = _usage_where_clause(query)

    # (relationship type, labels of the matched neighbour, counted in the usage)
    fixtures = (
        ("CATEGORIZED_AS", ("Category",), True),
        ("OWNED_BY", ("OwnerGroup",), True),
        ("HAS_EVENT", ("Event",), True),
        ("HAS_METRIC", ("MetricDef",), True),
        ("CONNECTS_TO", ("CI",), True),
        ("CONNECTED_VIA", ("CI",), True),
        ("OWNED_BY", ("PhysicalLink",), True),
        ("CONNECTED_VIA", ("PhysicalLink",), False),
    )

    for rel_type, other_labels, counted in fixtures:
        included = _usage_predicate_counts(clause, params, rel_type, other_labels)
        assert (
            included is counted
        ), f"{rel_type} -> {other_labels} counted={counted}, predicate says {included}"


def test_get_node_usage_excludes_physicallink_edge_in_both_directions(monkeypatch):
    """feat-539 / S1: the exclusion is direction-agnostic.

    The canonical edge is written as ``(:CI)-[:CONNECTED_VIA]->(:PhysicalLink)``
    but the reversed ``(:PhysicalLink)-[:CONNECTED_VIA]->(:CI)`` edge must be
    excluded as well.
    """
    _, query, params = _run_usage_query(monkeypatch)
    clause = _usage_where_clause(query)

    # The incident relationship is matched undirected, so both orientations of
    # the CI<->PhysicalLink edge reach the same predicate.
    assert "-[r]->" not in query
    assert "<-[r]-" not in query

    # The label check applies to the MATCHED NEIGHBOUR (the PhysicalLink), not
    # to the anchored CI, so the reversed orientation is excluded too.
    label_variables = re.findall(r"([a-z_][a-z0-9_]*)\s*:\s*physicallink", clause)
    assert label_variables, "expected a PhysicalLink label check"
    assert (
        "n" not in label_variables
    ), "the PhysicalLink check must target the matched neighbour, not the anchored CI"

    # The neighbour of the anchored CI is the PhysicalLink in both directions.
    assert _usage_predicate_counts(clause, params, "CONNECTED_VIA", ("PhysicalLink",)) is False
