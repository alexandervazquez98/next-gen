"""Pydantic v2 DTO round-trip + sensitive-field omission tests (#390).

Split out of test_graph_contracts.py so each contract module ships with
its own focused test file (work-unit commits).
"""

from __future__ import annotations


class TestSchemaDTOs:
    """Pydantic v2 DTO round-trip + sensitive-field omission (REQ-1, REQ-2).

    These tests assert that:

    - OverviewResponse / DetailResponse serialize to the exact field shape
      pinned in the spec.
    - The five sensitive fields (``public_ip``, raw ``metadata``, exact geo,
      serial numbers, provider account identifiers) are NEVER emitted in
      overview responses.
    - Hidden and absent clusters are externally indistinguishable on detail:
      same body shape with ``cluster: null`` and ``empty_reason: "unavailable"``.
    """

    def test_overview_response_round_trip_minimal(self):
        from schemas.graph import (
            AggregatePolicy,
            Legend,
            OverviewResponse,
            Page,
        )

        response = OverviewResponse(
            axis="location",
            filters={},
            generated_at="2026-01-01T00:00:00Z",
            revision="test-revision-0001",
            aggregate_policy=AggregatePolicy(minimum_count=5),
            clusters=[],
            inter_cluster_links=[],
            legend=Legend(),
            page=Page(has_more=False),
        )
        dumped = response.model_dump(mode="json", exclude_none=False)
        assert dumped["axis"] == "location"
        assert dumped["revision"] == "test-revision-0001"
        assert dumped["clusters"] == []
        assert dumped["inter_cluster_links"] == []
        assert dumped["page"]["has_more"] is False
        assert dumped["page"].get("next_cursor") is None

    def test_overview_response_contains_no_sensitive_fields(self):
        """The 5 sensitive fields MUST NEVER appear in overview responses."""
        from schemas.graph import OverviewResponse

        response = OverviewResponse(
            axis="location",
            filters={},
            generated_at="2026-01-01T00:00:00Z",
            revision="test-revision-0001",
        )
        dumped = response.model_dump(mode="json")
        forbidden = {
            "public_ip",
            "metadata",
            "geo_coordinates",
            "serial_number",
            "provider_account_id",
        }
        leaked = forbidden.intersection(dumped.keys())
        assert not leaked, f"overview leaked sensitive fields: {leaked}"

    def test_overview_cluster_carries_redacted_flag(self):
        from schemas.graph import OverviewCluster

        cluster = OverviewCluster(
            cluster_id="location:dc-1",
            display_label="dc-1",
            visible_node_count=3,
            visible_link_count=2,
            aggregate_redacted=True,
            suppression_reason="low_cardinality",
        )
        dumped = cluster.model_dump(mode="json")
        assert dumped["aggregate_redacted"] is True
        assert dumped["suppression_reason"] == "low_cardinality"

    def test_inter_cluster_link_carries_visible_link_count(self):
        from schemas.graph import InterClusterLink

        link = InterClusterLink(
            from_cluster_id="location:dc-1",
            to_cluster_id="location:dc-2",
            visible_link_count=7,
            redacted=False,
        )
        assert link.visible_link_count == 7
        assert link.redacted is False

    def test_detail_response_round_trip_visible_cluster(self):
        from schemas.graph import (
            DetailCluster,
            DetailLink,
            DetailNode,
            DetailResponse,
            EmptyReason,
            Page,
            ProjectionFlags,
            SensitiveSource,
        )

        response = DetailResponse(
            cluster=DetailCluster(
                cluster_id="location:dc-1",
                axis="location",
                display_label="dc-1",
                visible_node_count=3,
                visible_link_count=2,
            ),
            filters={},
            generated_at="2026-01-01T00:00:00Z",
            revision="test-revision-0001",
            nodes=[
                DetailNode(
                    id="ci-1",
                    display_label="ci-1",
                    kind="CI",
                    ci_type="router",
                    allowed_public_axes=["ci_type"],
                )
            ],
            links=[
                DetailLink(source_node_id="ci-1", target_node_id="ci-2", relationship="CONNECTS_TO")
            ],
            boundary_stubs=[],
            projection_flags=ProjectionFlags(
                show_sensitive_metadata=False,
                sensitive_source=SensitiveSource.NEVER,
            ),
            empty_reason=EmptyReason.NONE,
            page=Page(has_more=False),
        )
        dumped = response.model_dump(mode="json")
        assert dumped["cluster"]["cluster_id"] == "location:dc-1"
        assert dumped["empty_reason"] == "none"
        assert len(dumped["nodes"]) == 1
        assert dumped["nodes"][0]["ci_type"] == "router"
        # Detail MUST NOT emit public_ip on a node.
        assert "public_ip" not in dumped["nodes"][0]
        # Detail MUST NOT emit a raw metadata object on a node.
        assert "metadata" not in dumped["nodes"][0]

    def test_detail_response_hidden_absent_shape(self):
        """Hidden and absent clusters produce the same body shape (REQ-7).

        cluster=None, nodes/links/boundary_stubs=[], empty_reason="unavailable".
        """
        from schemas.graph import (
            DetailResponse,
            EmptyReason,
            Page,
            ProjectionFlags,
            SensitiveSource,
        )

        response = DetailResponse(
            cluster=None,
            filters={},
            generated_at="2026-01-01T00:00:00Z",
            revision="test-revision-0001",
            nodes=[],
            links=[],
            boundary_stubs=[],
            projection_flags=ProjectionFlags(
                show_sensitive_metadata=False,
                sensitive_source=SensitiveSource.NEVER,
            ),
            empty_reason=EmptyReason.UNAVAILABLE,
            page=Page(has_more=False),
        )
        dumped = response.model_dump(mode="json")
        assert dumped["cluster"] is None
        assert dumped["nodes"] == []
        assert dumped["links"] == []
        assert dumped["boundary_stubs"] == []
        assert dumped["empty_reason"] == "unavailable"

    def test_empty_reason_enum_members(self):
        from schemas.graph import EmptyReason

        assert EmptyReason.NONE == "none"
        assert EmptyReason.NO_VISIBLE_MEMBERS == "no_visible_members"
        assert EmptyReason.HIDDEN_ABSENT == "hidden_absent"
        assert EmptyReason.UNAVAILABLE == "unavailable"

    def test_safe_geo_precision_in_aggregate_policy(self):
        from contracts.aggregate_policy import SafeGeoPrecision
        from schemas.graph import AggregatePolicy

        policy = AggregatePolicy(
            minimum_count=5,
            safe_geo_precision=SafeGeoPrecision.REGION,
        )
        dumped = policy.model_dump(mode="json")
        assert dumped["minimum_count"] == 5
        assert dumped["safe_geo_precision"] == "region"
        assert dumped["permission_required"] == "graph:aggregate_breakdown:read"

    def test_boundary_stub_max_one_per_adjacent_cluster(self):
        """A stub is a single tuple (cluster_id, visible_link_count).

        The optional ``redacted`` / ``redaction_reason`` fields are emitted
        only when a stub's visible_link_count is below the aggregate
        minimum_count. The shape MUST allow them as optional fields.
        """
        from schemas.graph import BoundaryStub

        stub = BoundaryStub(
            cluster_id="location:dc-2",
            visible_link_count=3,
        )
        assert stub.cluster_id == "location:dc-2"
        assert stub.visible_link_count == 3
        assert stub.redacted is False
        assert stub.redaction_reason is None

        redacted = BoundaryStub(
            cluster_id="location:dc-3",
            visible_link_count=2,
            redacted=True,
            redaction_reason="low_cardinality",
        )
        dumped = redacted.model_dump(mode="json", exclude_none=True)
        assert dumped["redacted"] is True
        assert dumped["redaction_reason"] == "low_cardinality"

    def test_projection_flags_default_show_sensitive_metadata_is_false(self):
        """The default for ``show_sensitive_metadata`` is ALWAYS False (REQ-9)."""
        from schemas.graph import ProjectionFlags

        flags = ProjectionFlags()
        assert flags.show_sensitive_metadata is False
