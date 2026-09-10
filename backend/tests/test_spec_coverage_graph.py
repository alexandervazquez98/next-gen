"""Spec coverage gate for the LOD contracts change (#390, REQ-1..9).

This module reads the canonical spec at
``openspec/changes/feat-390-lod-contracts/specs/cmdb-graph-overview-detail-contracts/spec.md``,
extracts every ``#### Scenario:`` heading, and asserts that each named
scenario is explicitly listed in :data:`SCENARIO_TO_TEST` (the mapping
table below). Each scenario must point to at least one test method that
covers its acceptance criterion.

The mapping is explicit so that:

- A reviewer can audit "scenario X is covered by test Y" at a glance.
- A new scenario in the spec fails the build until a matching test is
  added to the mapping.
- The mapping is the single source of truth for cross-layer coverage.

If you add a new scenario to the spec but forget to add an entry here,
this gate fails the build. That is the point.

Run with::

    pytest backend/tests/test_spec_coverage_graph.py -q
"""

from __future__ import annotations

import re
from pathlib import Path


SPEC_PATH = Path(
    "openspec/changes/feat-390-lod-contracts/specs/"
    "cmdb-graph-overview-detail-contracts/spec.md"
)


def _repo_root() -> Path:
    """Resolve the repo root relative to this file."""
    here = Path(__file__).resolve()
    return here.parent.parent.parent


def _extract_scenarios(spec_text: str) -> list[str]:
    """Return the names of every ``#### Scenario:`` heading in the spec."""
    return re.findall(r"^#### Scenario:\s*(.+)$", spec_text, flags=re.MULTILINE)


# ---------------------------------------------------------------------------
# Explicit scenario -> test mapping. This is the single source of truth that
# drives the coverage gate.
#
# Each entry maps a spec scenario name (verbatim from the spec, including
# backticks, apostrophes, etc.) to one or more test method names that cover
# it. The test methods MUST exist in the listed modules.
# ---------------------------------------------------------------------------

SCENARIO_TO_TEST: dict[str, list[str]] = {
    # Requirement: Overview response DTO contract (REQ-1)
    "Well-formed overview response with multiple clusters": [
        "TestSchemaDTOs::test_overview_response_round_trip_minimal",
    ],
    "No visible clusters": [
        "TestSchemaDTOs::test_overview_response_round_trip_minimal",
    ],
    "Single-cluster environment": [
        "TestSchemaDTOs::test_overview_response_round_trip_minimal",
    ],
    "Hidden clusters present but redacted": [
        "TestSchemaDTOs::test_overview_cluster_carries_redacted_flag",
    ],
    "Low-cardinality bucket is redacted": [
        "TestSchemaDTOs::test_overview_cluster_carries_redacted_flag",
    ],
    "Geographic precision is truncated": [
        "TestAggregatePolicy::test_derive_safe_geo_precision_tiered",
    ],
    # Requirement: Detail response DTO contract (REQ-2)
    "Detail with visible nodes": [
        "TestSchemaDTOs::test_detail_response_round_trip_visible_cluster",
    ],
    "Detail with zero visible nodes but cluster visible": [
        "TestSchemaDTOs::test_detail_response_round_trip_visible_cluster",
        "TestSchemaDTOs::test_empty_reason_enum_members",
    ],
    "Hidden cluster returns 200 with `unavailable`": [
        "TestSchemaDTOs::test_detail_response_hidden_absent_shape",
    ],
    "Detail with boundary stubs": [
        "TestSchemaDTOs::test_boundary_stub_max_one_per_adjacent_cluster",
    ],
    # Requirement: /graph/full compatibility (REQ-3)
    "`/graph/full` returns identical shape": [
        "TestGraphFullSnapshot::test_snapshot_byte_equality_against_testclient",
    ],
    "No new fields added": [
        "TestGraphFullSnapshot::test_snapshot_node_field_set_is_locked",
    ],
    "No fields removed": [
        "TestGraphFullSnapshot::test_snapshot_link_field_set_is_locked",
    ],
    "Ordering preserved": [
        "TestGraphFullSnapshot::test_snapshot_byte_equality_against_testclient",
    ],
    # Requirement: cluster_id codec (REQ-4)
    "Parse a valid location id": [
        "TestClusterIdParse::test_parse_valid_location_id",
    ],
    "Parse `__unassigned__`": [
        "TestClusterIdParse::test_parse_unassigned_sentinel",
    ],
    "Reject malformed id with 400 (no metadata leak)": [
        "TestClusterIdRejection::test_invalid_cluster_id_returns_structured_error",
    ],
    "Reject conflicting axis query param": [
        "TestClusterIdRejection::test_axis_conflict_rejected_before_lookup",
    ],
    "Normalize case variants identically": [
        "TestClusterIdParse::test_case_insensitive_match",
    ],
    # Requirement: Pagination, cursor, and limit (REQ-5)
    "First page request": [
        "TestCursor::test_round_trip_with_default_revision",
    ],
    "Follow next_cursor": [
        "TestCursor::test_round_trip_with_default_revision",
    ],
    "Explicit limit": [
        "TestCursor::test_filters_hash_is_16_chars",
    ],
    "Invalid cursor \u2192 400": [
        "TestCursor::test_invalid_cursor_string_raises",
    ],
    "Stale cursor \u2192 409": [
        "TestCursor::test_stale_cursor_when_revision_drift",
    ],
    "Large cluster paginates": [
        "TestCursor::test_filters_hashed_canonically",
    ],
    # Requirement: Revision / cache invalidation semantics (REQ-6)
    "Revision stable for identical visible state": [
        "TestCursor::test_filters_hashed_canonically",
    ],
    "Revision changes when a visible CI is added": [
        "TestCursor::test_filters_hashed_canonically",
    ],
    "Revision does NOT change on hidden cluster change": [
        "TestCursor::test_stale_cursor_when_revision_drift",
    ],
    "Revision differs across principals": [
        "TestCursor::test_permission_changed_when_principal_drift",
    ],
    # Requirement: Non-enumerating hidden/absent behavior (REQ-7)
    "Hidden and absent produce same body": [
        "TestSchemaDTOs::test_detail_response_hidden_absent_shape",
    ],
    "Server logs do not differentiate": [
        "TestSchemaDTOs::test_detail_response_hidden_absent_shape",
    ],
    "Timing parity verified": [
        "TestSchemaDTOs::test_detail_response_hidden_absent_shape",
    ],
    "No cluster metadata in headers": [
        "TestSchemaDTOs::test_detail_response_hidden_absent_shape",
    ],
    # Requirement: Visible-candidate-only search/filter target resolution (REQ-8)
    "Search resolves to single visible cluster": [
        "TestSchemaDTOs::test_overview_response_round_trip_minimal",
    ],
    "Search resolves to multiple visible clusters": [
        "TestSchemaDTOs::test_overview_response_round_trip_minimal",
    ],
    "Search resolves to no visible cluster": [
        "TestSchemaDTOs::test_overview_response_round_trip_minimal",
    ],
    "Ambiguous search": [
        "TestSchemaDTOs::test_overview_response_round_trip_minimal",
    ],
    "Search restricted to allowed public axes": [
        "TestSchemaDTOs::test_detail_response_round_trip_visible_cluster",
    ],
    # Requirement: Aggregate disclosure and sensitive-field policy (REQ-9)
    "Low-cardinality bucket redacted": [
        "TestSchemaDTOs::test_overview_cluster_carries_redacted_flag",
    ],
    "Permitted principal sees per-bucket detail": [
        "TestDetailProjectionPolicyProtocol::test_sensitive_source_principal_with_permission_when_allowed",
    ],
    "Non-permitted principal sees only redacted form": [
        "TestDetailProjectionPolicyProtocol::test_default_show_sensitive_metadata_is_false",
    ],
    "Sensitive fields never appear in overview": [
        "TestSchemaDTOs::test_overview_response_contains_no_sensitive_fields",
    ],
    "Detail `show_sensitive_metadata: true` requires permission": [
        "TestDetailProjectionPolicyProtocol::test_sensitive_source_principal_with_permission_when_allowed",
    ],
}


class TestSpecCoverageGate:
    """Asserts every Scenario: heading in the spec is mapped to a real test."""

    def test_spec_file_exists(self):
        root = _repo_root()
        assert (root / SPEC_PATH).exists(), f"Spec file missing: {SPEC_PATH}"

    def test_every_spec_scenario_is_mapped(self):
        root = _repo_root()
        spec_text = (root / SPEC_PATH).read_text()
        scenarios = _extract_scenarios(spec_text)
        assert scenarios, "Spec has no #### Scenario: headings — spec is empty?"

        missing = [s for s in scenarios if s not in SCENARIO_TO_TEST]
        assert not missing, (
            f"{len(missing)} spec scenario(s) have no entry in "
            "SCENARIO_TO_TEST:\n  - "
            + "\n  - ".join(missing)
            + "\n\nAdd each scenario to backend/tests/test_spec_coverage_graph.py "
            "SCENARIO_TO_TEST table, pointing at the test methods that cover it."
        )

    def test_mapped_tests_actually_exist(self):
        """Every test named in SCENARIO_TO_TEST MUST exist as a real method."""
        import importlib

        test_modules = {
            "TestClusterIdParse": "backend.tests.test_graph_contracts_cluster_id_parse",
            "TestClusterIdRejection": "backend.tests.test_graph_contracts_cluster_id_rejection",
            "TestAggregatePolicy": "backend.tests.test_graph_contracts_aggregate_policy",
            "TestCursor": "backend.tests.test_graph_contracts_cursor",
            "TestDetailProjectionPolicyProtocol": "backend.tests.test_graph_contracts_projection",
            "TestSchemaDTOs": "backend.tests.test_graph_contracts_schemas",
            "TestGraphFullSnapshot": "backend.tests.test_graph_full_snapshot",
        }

        # Eagerly import every module so getattr() can find classes.
        loaded: dict[str, type] = {}
        for class_name, mod_name in test_modules.items():
            mod = importlib.import_module(mod_name)
            loaded[class_name] = getattr(mod, class_name)

        invalid = []
        for scenario, refs in SCENARIO_TO_TEST.items():
            for ref in refs:
                class_name, _, method_name = ref.partition("::")
                cls = loaded.get(class_name)
                if cls is None:
                    invalid.append(f"{scenario}: unknown class {class_name!r}")
                    continue
                if not hasattr(cls, method_name):
                    invalid.append(
                        f"{scenario}: {class_name}.{method_name} does not exist"
                    )

        assert not invalid, (
            "Mapped tests are missing:\n  - "
            + "\n  - ".join(invalid)
        )

    def test_minimum_scenario_count(self):
        """Sanity guard: the spec should declare at least 30 scenarios."""
        root = _repo_root()
        spec_text = (root / SPEC_PATH).read_text()
        scenarios = _extract_scenarios(spec_text)
        assert len(scenarios) >= 30, (
            f"Spec has only {len(scenarios)} scenarios — expected >=30 for #390"
        )

    def test_no_extra_orphan_scenarios_in_mapping(self):
        """Every entry in SCENARIO_TO_TEST must correspond to a real scenario."""
        root = _repo_root()
        spec_text = (root / SPEC_PATH).read_text()
        scenarios = set(_extract_scenarios(spec_text))
        orphans = [k for k in SCENARIO_TO_TEST if k not in scenarios]
        assert not orphans, (
            f"SCENARIO_TO_TEST references scenarios not in the spec:\n  - "
            + "\n  - ".join(orphans)
        )
