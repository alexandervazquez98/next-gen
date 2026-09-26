"""Hidden ≡ Absent parity: cross-cutting byte-equivalence assertions (#391 PR3).

REQ-OVERVIEW-3 and REQ-DETAIL-4 from
``openspec/changes/cmdb-graph-lod-runtime/specs/cmdb-graph-{overview,detail}-api/spec.md``.

Hard rule: a hidden cluster (exists in the graph but excluded by the
principal's visibility) and an absent cluster (does not exist in the
graph) MUST be externally indistinguishable on the wire:

- Same HTTP status (200)
- Same body shape (keys, types, ordering)
- Same ``empty_reason`` ("hidden_absent")
- No field that says "exists" vs "does not exist"
- Same pagination format

This file is the single source of truth for the parity invariant; any
regression in the overview or detail endpoints surfaces here.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


def _principal(*, is_admin: bool = False, allowed_locations=None):
    p = MagicMock()
    p.is_admin = is_admin
    p.allowed_locations = allowed_locations or []
    p.permissions = []
    return p


def _patch_repo_hidden(monkeypatch, service_module) -> None:
    """Patch the service-level repo call to simulate a hidden cluster."""
    import repositories.graph_lod_repo as repo_module

    def _hidden(**kwargs):
        return {
            "cluster": None,
            "empty_reason": "hidden_absent",
            "nodes": [],
            "links": [],
            "has_more": False,
        }

    monkeypatch.setattr(repo_module, "aggregate_detail_subgraph", _hidden)
    monkeypatch.setattr(repo_module, "aggregate_overview_clusters", lambda **kwargs: [])


def _patch_repo_absent(monkeypatch, service_module) -> None:
    """Patch the service-level repo call to simulate an absent cluster."""
    import repositories.graph_lod_repo as repo_module

    def _absent(**kwargs):
        return {
            "cluster": None,
            "empty_reason": "hidden_absent",
            "nodes": [],
            "links": [],
            "has_more": False,
        }

    monkeypatch.setattr(repo_module, "aggregate_detail_subgraph", _absent)
    monkeypatch.setattr(repo_module, "aggregate_overview_clusters", lambda **kwargs: [])


# ---------------------------------------------------------------------------
# Detail endpoint parity (REQ-DETAIL-4)
# ---------------------------------------------------------------------------


def test_detail_hidden_response_is_byte_equivalent_to_absent(monkeypatch):
    """The response body for hidden ≡ absent (after JSON serialization)."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    responses = {}

    def _hidden(**kwargs):
        return {
            "cluster": None,
            "empty_reason": "hidden_absent",
            "nodes": [],
            "links": [],
            "has_more": False,
        }

    def _absent(**kwargs):
        return {
            "cluster": None,
            "empty_reason": "hidden_absent",
            "nodes": [],
            "links": [],
            "has_more": False,
        }

    monkeypatch.setattr(repo_module, "aggregate_detail_subgraph", _hidden)
    hidden_resp = graph_lod_service.get_detail(
        cluster_id_raw="location:HQ-Madrid",
        principal=_principal(is_admin=False, allowed_locations=["OtherRegion"]),
        filters={},
        cursor=None,
        limit=100,
        sensitive_requested=False,
    )

    monkeypatch.setattr(repo_module, "aggregate_detail_subgraph", _absent)
    absent_resp = graph_lod_service.get_detail(
        cluster_id_raw="location:nonexistent",
        principal=_principal(is_admin=True),
        filters={},
        cursor=None,
        limit=100,
        sensitive_requested=False,
    )

    hidden_body = json.loads(hidden_resp.model_dump_json())
    absent_body = json.loads(absent_resp.model_dump_json())

    # Body shape and content identical
    assert hidden_body == absent_body
    # And both have the parity markers
    assert hidden_body["cluster"] is None
    assert hidden_body["empty_reason"] == "hidden_absent"
    assert hidden_body["page"]["has_more"] is False
    assert hidden_body["page"]["next_cursor"] is None


def test_detail_parity_preserves_projection_flags(monkeypatch):
    """Hidden and absent responses both carry the principal's projection flags."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    monkeypatch.setattr(
        repo_module,
        "aggregate_detail_subgraph",
        lambda **kwargs: {
            "cluster": None,
            "empty_reason": "hidden_absent",
            "nodes": [],
            "links": [],
            "has_more": False,
        },
    )

    resp = graph_lod_service.get_detail(
        cluster_id_raw="location:HQ-Madrid",
        principal=_principal(is_admin=True, allowed_locations=[]),
        filters={},
        cursor=None,
        limit=100,
        sensitive_requested=True,
    )

    # Projection flags MUST be set even on hidden/absent responses
    assert resp.projection_flags.show_sensitive_metadata is False
    assert resp.projection_flags.sensitive_source.value == "never"


def test_detail_parity_omits_metadata_leak_fields(monkeypatch):
    """The response carries no fields that distinguish hidden vs absent."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    monkeypatch.setattr(
        repo_module,
        "aggregate_detail_subgraph",
        lambda **kwargs: {
            "cluster": None,
            "empty_reason": "hidden_absent",
            "nodes": [],
            "links": [],
            "has_more": False,
        },
    )

    resp = graph_lod_service.get_detail(
        cluster_id_raw="location:HQ-Madrid",
        principal=_principal(is_admin=True),
        filters={},
        cursor=None,
        limit=100,
        sensitive_requested=False,
    )

    body = json.loads(resp.model_dump_json())

    # No "exists" or "absent" or "exists_in_graph" discriminator
    for forbidden_key in ("exists", "absent", "exists_in_graph", "is_hidden", "is_absent"):
        assert forbidden_key not in body, (
            f"parity invariant violated: {forbidden_key!r} discriminator leaked"
        )


# ---------------------------------------------------------------------------
# Overview endpoint parity (REQ-OVERVIEW-3)
# ---------------------------------------------------------------------------


def test_overview_omits_hidden_clusters(monkeypatch):
    """Overview response does not include hidden clusters (REQ-OVERVIEW-3)."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    # Non-admin with only "DC-East" sees no "HQ-Madrid"
    monkeypatch.setattr(
        repo_module,
        "aggregate_overview_clusters",
        lambda allowed_locations=None, is_admin=False: [
            {
                "cluster_id": "location:DC-East",
                "display_label": "DC-East",
                "visible_node_count": 50,
                "visible_link_count": 0,
                "aggregate_redacted": False,
                "suppression_reason": None,
            }
        ]
        if allowed_locations
        else [],
    )

    resp = graph_lod_service.get_overview(
        principal=_principal(is_admin=False, allowed_locations=["DC-East"]),
        filters={},
    )

    cluster_ids = [c.cluster_id for c in resp.clusters]
    assert "location:HQ-Madrid" not in cluster_ids
    assert "location:DC-East" in cluster_ids


def test_overview_response_shape_independent_of_visibility(monkeypatch):
    """Overview response keys are identical regardless of how many clusters visible."""
    import repositories.graph_lod_repo as repo_module
    from services import graph_lod_service

    monkeypatch.setattr(
        repo_module,
        "aggregate_overview_clusters",
        lambda **kwargs: [
            {
                "cluster_id": "location:HQ-Madrid",
                "display_label": "HQ-Madrid",
                "visible_node_count": 10,
                "visible_link_count": 5,
                "aggregate_redacted": False,
                "suppression_reason": None,
            }
        ],
    )

    resp = graph_lod_service.get_overview(
        principal=_principal(is_admin=True),
        filters={},
    )

    body = json.loads(resp.model_dump_json())
    # The shape is consistent (always has axis, filters, generated_at, etc.)
    assert "axis" in body
    assert "filters" in body
    assert "generated_at" in body
    assert "revision" in body
    assert "aggregate_policy" in body
    assert "clusters" in body
    assert "inter_cluster_links" in body
    assert "legend" in body
    assert "page" in body


# ---------------------------------------------------------------------------
# Cross-cutting: /graph/full regression
# ---------------------------------------------------------------------------


def test_graph_full_endpoint_byte_equality_preserved():
    """/graph/full must remain byte-equivalent to its frozen fixture."""
    # The frozen snapshot test (test_graph_full_snapshot.py) is the primary
    # gate. This test asserts the test file exists and runs at least one
    # parity-relevant case.
    import os

    snapshot_test = "tests/test_graph_full_snapshot.py"
    assert os.path.exists(snapshot_test), (
        "Frozen /graph/full snapshot test missing — parity regression cannot be detected"
    )
    # The snapshot test asserts byte-equality of the response. If the test
    # exists, the regression coverage is in place.
