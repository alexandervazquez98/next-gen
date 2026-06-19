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
