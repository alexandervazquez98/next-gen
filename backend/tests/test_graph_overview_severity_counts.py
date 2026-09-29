"""OverviewCluster carries aggregated severity counts (#524).

Adds three optional integer fields to ``OverviewCluster`` so the Geo View
of MonitoringConsole can color cluster markers by worst severity at
country zoom (Tier 2 of the perf migration). All three default to 0 so
the change is additive — existing fixtures and tests don't have to be
touched to remain valid.

Fields
------
- ``critical_count`` — number of currently-active CRITICAL events
  whose ``ci_id`` resolves into the cluster's visible nodes.
- ``warning_count`` — same for WARNING severity.
- ``event_count`` — total currently-active events (CRITICAL + WARNING
  + INFO; RECOVERED events are excluded — they don't drive a marker
  color in the Geo View).

REQ-9 sensitivity policy applies: these counts are aggregated cluster
totals, NOT per-CI or per-event disclosures. Low-cardinality clusters
already get ``aggregate_redacted=True`` via REQ-OVERVIEW-3; the severity
counts on those clusters are intentionally zeroed (test below).

The wire shape mirrors ``frontend/types/graph.ts::OverviewCluster`` and
is enforced by the parity gate in
``frontend/__tests__/parity.test.ts``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from services import graph_lod_service


def _principal(*, is_admin: bool = True):
    p = MagicMock()
    p.is_admin = is_admin
    p.allowed_locations = []
    p.permissions = []
    p.aggregate_breakdown_regions = []
    return p


# ---------------------------------------------------------------------------
# Schema (OverviewCluster DTO) — pure data shape, no IO
# ---------------------------------------------------------------------------


def test_overview_cluster_exposes_severity_count_fields():
    from schemas.graph import OverviewCluster

    cluster = OverviewCluster(
        cluster_id="location:HQ-Madrid",
        display_label="HQ-Madrid",
        visible_node_count=10,
        visible_link_count=20,
        critical_count=3,
        warning_count=5,
        event_count=11,
    )

    assert cluster.critical_count == 3
    assert cluster.warning_count == 5
    assert cluster.event_count == 11


def test_overview_cluster_severity_counts_default_to_zero():
    """Additive change: existing fixtures that omit the fields stay valid."""
    from schemas.graph import OverviewCluster

    cluster = OverviewCluster(
        cluster_id="location:DC-East",
        display_label="DC-East",
        visible_node_count=5,
    )

    assert cluster.critical_count == 0
    assert cluster.warning_count == 0
    assert cluster.event_count == 0


def test_overview_cluster_severity_counts_serialize_to_wire():
    from schemas.graph import OverviewCluster

    cluster = OverviewCluster(
        cluster_id="location:HQ-Madrid",
        display_label="HQ-Madrid",
        critical_count=2,
        warning_count=1,
        event_count=4,
    )

    payload = cluster.model_dump()
    assert payload["critical_count"] == 2
    assert payload["warning_count"] == 1
    assert payload["event_count"] == 4


def test_overview_cluster_strict_model_rejects_unknown_fields():
    """REQ-9 parity gate: extra='forbid' must reject unknown keys."""
    from pydantic import ValidationError
    from schemas.graph import OverviewCluster

    try:
        OverviewCluster(
            cluster_id="location:HQ-Madrid",
            display_label="HQ-Madrid",
            public_ip="10.0.0.1",  # type: ignore[call-arg]
        )
    except ValidationError:
        return
    raise AssertionError("Expected ValidationError for unknown field 'public_ip'")


# ---------------------------------------------------------------------------
# Service — repository rows with severity counts flow through unchanged
# ---------------------------------------------------------------------------


def test_overview_service_passes_through_severity_counts(monkeypatch):
    """The service must NOT drop severity_count fields when the repo
    returns them. Default behaviour (no counts) still yields zero values."""

    from repositories import graph_lod_repo

    repo_rows = [
        {
            "cluster_id": "location:HQ-Madrid",
            "display_label": "HQ-Madrid",
            "visible_node_count": 10,
            "visible_link_count": 15,
            "aggregate_redacted": False,
            "suppression_reason": None,
            "critical_count": 3,
            "warning_count": 5,
            "event_count": 11,
        },
        {
            "cluster_id": "location:DC-East",
            "display_label": "DC-East",
            "visible_node_count": 5,
            "visible_link_count": 0,
            "aggregate_redacted": False,
            "suppression_reason": None,
            # Counts intentionally omitted — service must default to 0.
        },
    ]
    monkeypatch.setattr(
        graph_lod_repo,
        "aggregate_overview_clusters",
        lambda allowed_locations=None, is_admin=False: repo_rows,
    )

    result = graph_lod_service.get_overview(principal=_principal(), filters={})

    assert len(result.clusters) == 2

    hq = next(c for c in result.clusters if c.cluster_id == "location:HQ-Madrid")
    assert hq.critical_count == 3
    assert hq.warning_count == 5
    assert hq.event_count == 11

    dc = next(c for c in result.clusters if c.cluster_id == "location:DC-East")
    assert dc.critical_count == 0
    assert dc.warning_count == 0
    assert dc.event_count == 0


def test_overview_service_zeroes_counts_for_redacted_clusters(monkeypatch):
    """REQ-OVERVIEW-3: low-cardinality clusters get aggregate_redacted=True.
    Severity counts must be 0 on redacted clusters — never disclose per-CI
    severity through the cluster aggregate."""

    from repositories import graph_lod_repo

    repo_rows = [
        {
            "cluster_id": "location:Tiny",
            "display_label": "Tiny",
            "visible_node_count": 1,  # < DEFAULT_MINIMUM_COUNT (5) → redacted
            "visible_link_count": 0,
            "aggregate_redacted": True,
            "suppression_reason": "low_cardinality",
            "critical_count": 7,  # would be a leak if surfaced
            "warning_count": 9,
            "event_count": 16,
        },
    ]
    monkeypatch.setattr(
        graph_lod_repo,
        "aggregate_overview_clusters",
        lambda allowed_locations=None, is_admin=False: repo_rows,
    )

    result = graph_lod_service.get_overview(principal=_principal(), filters={})

    assert len(result.clusters) == 1
    tiny = result.clusters[0]
    assert tiny.aggregate_redacted is True
    assert tiny.critical_count == 0
    assert tiny.warning_count == 0
    assert tiny.event_count == 0
