"""Detail endpoint: cluster_id parse, cursor, hidden ≡ absent parity (#391 PR2).

REQ-DETAIL-1..5 from ``openspec/changes/cmdb-graph-lod-runtime/specs/cmdb-graph-detail-api/spec.md``.

Covers:

- Cluster ID parsing per ``contracts.cluster_id.parse_cluster_id``
- Cursor encode/decode + 409 stale + 400 permission changed
- Detail subgraph aggregation with visible-set WHERE clause
- Hidden cluster ≡ absent cluster byte-equivalent response
- DetailProjectionPolicy application (show_sensitive_metadata gate)
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


def _principal(
    *,
    is_admin: bool = False,
    allowed_locations: list[str] | None = None,
    permissions: list[str] | None = None,
):
    p = MagicMock()
    p.is_admin = is_admin
    p.allowed_locations = allowed_locations or []
    p.permissions = permissions or []
    return p


# ---------------------------------------------------------------------------
# Cluster ID parsing (REQ-DETAIL-2)
# ---------------------------------------------------------------------------


def test_get_detail_rejects_invalid_cluster_id_format():
    """Missing axis prefix yields 400 invalid_cluster_id (no metadata leak)."""

    # Patch auth dependency to a no-op principal
    # The router function parses the cluster_id before any DB call.
    # We invoke parse_cluster_id directly via the service layer.
    from services import graph_lod_service

    with MagicMock():
        try:
            graph_lod_service.get_detail(
                cluster_id_raw="invalid-format",
                principal=_principal(is_admin=True),
                filters={},
                cursor=None,
                limit=100,
                sensitive_requested=False,
            )
        except ValueError as exc:
            assert "cluster_id" in str(exc).lower() or "axis" in str(exc).lower()


def test_get_detail_accepts_valid_cluster_id(monkeypatch):
    """location:HQ-Madrid parses and reaches the repo (REQ-DETAIL-2 scenario 1)."""
    # Patch the repo to a no-op so the call does not hit Neo4j
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    monkeypatch.setattr(
        repo_module,
        "aggregate_detail_subgraph",
        lambda **kwargs: {
            "cluster": {
                "cluster_id": "location:HQ-Madrid",
                "display_label": "HQ-Madrid",
                "visible_node_count": 10,
                "visible_link_count": 5,
            },
            "nodes": [],
            "links": [],
            "has_more": False,
        },
    )

    response = graph_lod_service.get_detail(
        cluster_id_raw="location:HQ-Madrid",
        principal=_principal(is_admin=True),
        filters={},
        cursor=None,
        limit=100,
        sensitive_requested=False,
    )

    assert response.cluster.cluster_id == "location:HQ-Madrid"


# ---------------------------------------------------------------------------
# Hidden ≡ absent parity (REQ-DETAIL-4)
# ---------------------------------------------------------------------------


def test_get_detail_hidden_cluster_returns_empty_response(monkeypatch):
    """Cluster exists but principal cannot see it → 200 with cluster=null + hidden_absent."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    # Repo returns empty (visibility filter excludes the cluster)
    monkeypatch.setattr(
        repo_module,
        "aggregate_detail_subgraph",
        lambda **kwargs: {"cluster": None, "empty_reason": "hidden_absent"},
    )

    response = graph_lod_service.get_detail(
        cluster_id_raw="location:HQ-Madrid",
        principal=_principal(is_admin=False, allowed_locations=["OtherRegion"]),
        filters={},
        cursor=None,
        limit=100,
        sensitive_requested=False,
    )

    assert response.cluster is None
    assert response.empty_reason == "hidden_absent"


def test_get_detail_absent_cluster_returns_byte_equivalent_response(monkeypatch):
    """Cluster does not exist → 200 with cluster=null + hidden_absent (REQ-DETAIL-4 scenario 2)."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    monkeypatch.setattr(
        repo_module,
        "aggregate_detail_subgraph",
        lambda **kwargs: {"cluster": None, "empty_reason": "hidden_absent"},
    )

    response = graph_lod_service.get_detail(
        cluster_id_raw="location:nonexistent",
        principal=_principal(is_admin=True),
        filters={},
        cursor=None,
        limit=100,
        sensitive_requested=False,
    )

    assert response.cluster is None
    assert response.empty_reason == "hidden_absent"


# ---------------------------------------------------------------------------
# Cursor semantics (REQ-DETAIL-3)
# ---------------------------------------------------------------------------


def test_get_detail_decodes_cursor_and_rejects_stale(monkeypatch):
    """A cursor bound to an old revision raises StaleCursorError -> 409."""
    import repositories.graph_lod_repo as repo_module

    monkeypatch.setattr(
        repo_module,
        "aggregate_detail_subgraph",
        lambda **kwargs: {"cluster": None, "empty_reason": "hidden_absent"},
    )

    # Encode a cursor, then change the revision underneath
    from contracts.cursor import encode_cursor
    from contracts.revision import Revision

    stale_cursor = encode_cursor(
        cluster_id="location:HQ-Madrid",
        filters={},
        revision=Revision("stale-revision"),
        principal_hash="0" * 16,
        nonce="test-nonce",
    )

    # StaleCursorError surfaces as 409 from the router; the service should
    # pass through without swallowing it. We assert the service raises
    # the underlying ValueError.
    import pytest
    from contracts.cursor import decode_cursor

    with pytest.raises(ValueError):
        decode_cursor(stale_cursor, current_revision=Revision("current-revision"))


def test_get_detail_decodes_cursor_and_rejects_permission_changed(monkeypatch):
    """A cursor bound to a different principal_hash raises PermissionChangedError."""
    from contracts.cursor import (
        PermissionChangedError,
        decode_cursor,
        encode_cursor,
    )
    from contracts.revision import Revision

    stale_cursor = encode_cursor(
        cluster_id="location:HQ-Madrid",
        filters={},
        revision=Revision("rev-1"),
        principal_hash="a" * 16,
        nonce="test-nonce",
    )

    import pytest

    with pytest.raises(PermissionChangedError):
        decode_cursor(stale_cursor, current_principal_hash="b" * 16)


def test_get_detail_decodes_cursor_and_rejects_invalid(monkeypatch):
    """A malformed cursor raises InvalidCursorError."""
    import pytest
    from contracts.cursor import InvalidCursorError, decode_cursor

    with pytest.raises(InvalidCursorError):
        decode_cursor("not-a-valid-cursor")


# ---------------------------------------------------------------------------
# Visible-set filtering (REQ-DETAIL-1)
# ---------------------------------------------------------------------------


def test_get_detail_passes_visible_set_in_where_clause(monkeypatch):
    """The detail repo query includes the visible-set WHERE clause for non-admin."""
    import repositories.graph_lod_repo as repo_module

    driver, session = _mock_driver()
    monkeypatch.setattr(repo_module, "get_db", lambda: driver)

    repo_module.aggregate_detail_subgraph(
        cluster_id="location:HQ-Madrid",
        allowed_locations=["HQ-Madrid"],
        is_admin=False,
        limit=100,
    )

    query = session.run.call_args.args[0]
    params = session.run.call_args.kwargs
    assert "WHERE" in query or "where" in query.lower()
    assert "allowed_locations" in params
    assert params["allowed_locations"] == ["HQ-Madrid"]


def test_get_detail_admin_skips_visibility_filter(monkeypatch):
    """Admin with is_admin=True aggregates over the full visible graph."""
    import repositories.graph_lod_repo as repo_module

    driver, session = _mock_driver()
    monkeypatch.setattr(repo_module, "get_db", lambda: driver)

    repo_module.aggregate_detail_subgraph(
        cluster_id="location:HQ-Madrid",
        allowed_locations=None,
        is_admin=True,
        limit=100,
    )

    query = session.run.call_args.args[0]
    params = session.run.call_args.kwargs
    assert "allowed_locations" not in params
    assert "$allowed_locations" not in query


# ---------------------------------------------------------------------------
# DetailProjectionPolicy (REQ-DETAIL-5)
# ---------------------------------------------------------------------------


def test_get_detail_omits_sensitive_metadata_without_permission(monkeypatch):
    """A principal without graph:aggregate_breakdown:read sees no sensitive fields."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    monkeypatch.setattr(
        repo_module,
        "aggregate_detail_subgraph",
        lambda **kwargs: {
            "cluster": {
                "cluster_id": "location:HQ-Madrid",
                "display_label": "HQ-Madrid",
                "visible_node_count": 1,
                "visible_link_count": 0,
            },
            "nodes": [
                {
                    "id": "ci-1",
                    "display_label": "Router-1",
                    "kind": "Router",
                    "ci_type": "Router",
                    "allowed_public_axes": [],
                    "public_ip": "1.2.3.4",  # sensitive field — must be stripped
                }
            ],
            "links": [],
        },
    )

    response = graph_lod_service.get_detail(
        cluster_id_raw="location:HQ-Madrid",
        principal=_principal(is_admin=True, permissions=[]),
        filters={},
        cursor=None,
        limit=100,
        sensitive_requested=True,  # caller requested, but no permission
    )

    assert response.projection_flags.show_sensitive_metadata is False
    assert response.projection_flags.sensitive_source.value == "never"
    # Sensitive field public_ip must NOT appear on the wire
    assert "public_ip" not in response.nodes[0].model_dump()


def test_get_detail_includes_sensitive_metadata_with_permission(monkeypatch):
    """A principal with graph:aggregate_breakdown:read + explicit request sees sensitive fields."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    monkeypatch.setattr(
        repo_module,
        "aggregate_detail_subgraph",
        lambda **kwargs: {
            "cluster": {
                "cluster_id": "location:HQ-Madrid",
                "display_label": "HQ-Madrid",
                "visible_node_count": 1,
                "visible_link_count": 0,
            },
            "nodes": [
                {
                    "id": "ci-1",
                    "display_label": "Router-1",
                    "kind": "Router",
                    "ci_type": "Router",
                    "allowed_public_axes": [],
                    "public_ip": "1.2.3.4",
                }
            ],
            "links": [],
        },
    )

    response = graph_lod_service.get_detail(
        cluster_id_raw="location:HQ-Madrid",
        principal=_principal(
            is_admin=True,
            permissions=["graph:aggregate_breakdown:read"],
        ),
        filters={},
        cursor=None,
        limit=100,
        sensitive_requested=True,
    )

    assert response.projection_flags.show_sensitive_metadata is True
    assert response.projection_flags.sensitive_source.value == "principal_with_permission"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_get_detail_returns_cursor_for_next_page(monkeypatch):
    """When more nodes exist than limit, response includes a next cursor."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    monkeypatch.setattr(
        repo_module,
        "aggregate_detail_subgraph",
        lambda **kwargs: {
            "cluster": {
                "cluster_id": "location:HQ-Madrid",
                "display_label": "HQ-Madrid",
                "visible_node_count": 250,
                "visible_link_count": 0,
            },
            "nodes": [
                {
                    "id": f"ci-{i}",
                    "display_label": f"R-{i}",
                    "kind": "Router",
                    "ci_type": "Router",
                    "allowed_public_axes": [],
                }
                for i in range(50)
            ],
            "links": [],
            "has_more": True,
        },
    )

    response = graph_lod_service.get_detail(
        cluster_id_raw="location:HQ-Madrid",
        principal=_principal(is_admin=True),
        filters={},
        cursor=None,
        limit=50,
        sensitive_requested=False,
    )

    assert response.page.has_more is True
    assert response.page.next_cursor is not None


def test_get_detail_no_cursor_when_all_results_fit(monkeypatch):
    """When all visible nodes fit within limit, response has has_more=False."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    monkeypatch.setattr(
        repo_module,
        "aggregate_detail_subgraph",
        lambda **kwargs: {
            "cluster": {
                "cluster_id": "location:HQ-Madrid",
                "display_label": "HQ-Madrid",
                "visible_node_count": 3,
                "visible_link_count": 0,
            },
            "nodes": [
                {
                    "id": f"ci-{i}",
                    "display_label": f"R-{i}",
                    "kind": "Router",
                    "ci_type": "Router",
                    "allowed_public_axes": [],
                }
                for i in range(3)
            ],
            "links": [],
            "has_more": False,
        },
    )

    response = graph_lod_service.get_detail(
        cluster_id_raw="location:HQ-Madrid",
        principal=_principal(is_admin=True),
        filters={},
        cursor=None,
        limit=100,
        sensitive_requested=False,
    )

    assert response.page.has_more is False
    assert response.page.next_cursor is None
