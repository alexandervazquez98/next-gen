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
