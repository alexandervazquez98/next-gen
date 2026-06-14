from unittest.mock import MagicMock


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
