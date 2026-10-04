"""Parametrized contract tests for #539 propagation decisions.

These tests assert that the constants in
``services.correlation_propagation_contract`` match the values recorded in
``docs/correlation-topology-guide.md`` (the "Locked propagation decisions"
section). They are GREEN now (the contract is correct by construction) and
remain GREEN forever as long as the contract matches the doc.

If a future maintainer needs to change one of the four decisions, the change
must:

1. Update the doc.
2. Update the constant in the contract module.
3. Update the corresponding assertion below.
4. File a follow-up decision record explaining the change.

The chained implementation PRs (PR2 / PR3 / PR4) rely on the helper
functions as the documented public API; those helpers are also pinned here.
"""
from __future__ import annotations

import pytest

from services.correlation_propagation_contract import (
    CURRENT_TRAVERSAL_RELATIONSHIP_TYPES,
    FEATURE_FLAG_CONNECTS_TO_MEDIUM_FILTER,
    FEATURE_FLAG_MANAGES_USES_PROVIDES_CORRELATION,
    FEATURE_FLAG_PHYSICAL_LINK_CORRELATION,
    MANAGES_USES_PROVIDES_DEFAULT,
    PHYSICAL_LINK_DOWN_BEHAVIOR,
    PHYSICAL_LINK_STATUS_FRESHNESS,
    PHYSICAL_LINK_UNKNOWN_PROPAGATION,
    SUPPORTED_TRAVERSAL_RELATIONSHIP_TYPES,
    all_locked_values,
    should_default_propagate_manages_uses_provides,
    should_generate_descendant_event_on_down,
    should_propagate_unknown_severity_degrade,
    should_re_query_status_per_correlation,
)
from services.relationship_types import SUPPORTED_CI_RELATIONSHIP_TYPES

# ---------------------------------------------------------------------------
# Locked values (one test per decision)
# ---------------------------------------------------------------------------


class TestLockedValuesMatchDoc:
    """Each constant matches the value recorded in the design doc."""

    def test_decision_1_unknown_propagation(self):
        assert PHYSICAL_LINK_UNKNOWN_PROPAGATION == "degrade_severity_and_propagate"

    def test_decision_2_status_freshness(self):
        assert PHYSICAL_LINK_STATUS_FRESHNESS == "re_query_per_correlation"

    def test_decision_3_down_behavior(self):
        assert PHYSICAL_LINK_DOWN_BEHAVIOR == "generate_descendant_event"

    def test_decision_4_manages_uses_provides(self):
        assert MANAGES_USES_PROVIDES_DEFAULT == "all_propagate"


# ---------------------------------------------------------------------------
# All four decisions are present in the snapshot helper
# ---------------------------------------------------------------------------


class TestAllLockedValuesSnapshot:
    def test_snapshot_has_exactly_four_keys(self):
        snapshot = all_locked_values()
        assert set(snapshot.keys()) == {
            "physical_link_unknown_propagation",
            "physical_link_status_freshness",
            "physical_link_down_behavior",
            "manages_uses_provides_default",
        }

    def test_snapshot_values_match_constants(self):
        snapshot = all_locked_values()
        assert snapshot["physical_link_unknown_propagation"] == PHYSICAL_LINK_UNKNOWN_PROPAGATION
        assert snapshot["physical_link_status_freshness"] == PHYSICAL_LINK_STATUS_FRESHNESS
        assert snapshot["physical_link_down_behavior"] == PHYSICAL_LINK_DOWN_BEHAVIOR
        assert snapshot["manages_uses_provides_default"] == MANAGES_USES_PROVIDES_DEFAULT


# ---------------------------------------------------------------------------
# Helpers return the documented boolean for the locked values
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_unknown_severity_degrade_helper_returns_true(self):
        assert should_propagate_unknown_severity_degrade() is True

    def test_re_query_status_helper_returns_true(self):
        assert should_re_query_status_per_correlation() is True

    def test_descendant_event_helper_returns_true(self):
        assert should_generate_descendant_event_on_down() is True

    def test_default_propagate_helper_returns_true(self):
        assert should_default_propagate_manages_uses_provides() is True


# ---------------------------------------------------------------------------
# Relationship set registry
# ---------------------------------------------------------------------------


class TestTraversalRelationshipSet:
    def test_supported_set_has_seven_types(self):
        # 3 from the pre-#539 traversal + 1 PhysicalLink (CONNECTED_VIA)
        # + 3 M/U/P (MANAGES / USES / PROVIDES) = 7
        assert len(SUPPORTED_TRAVERSAL_RELATIONSHIP_TYPES) == 7

    def test_supported_set_contains_all_expected_types(self):
        assert frozenset({
            "DEPENDS_ON",
            "HOSTED_ON",
            "CONNECTS_TO",
            "CONNECTED_VIA",
            "MANAGES",
            "USES",
            "PROVIDES",
        }) == SUPPORTED_TRAVERSAL_RELATIONSHIP_TYPES

    def test_current_set_matches_pre_539_behavior(self):
        # Pre-#539: only 3 of 6 supported types are walked.
        assert frozenset({
            "DEPENDS_ON",
            "HOSTED_ON",
            "CONNECTS_TO",
        }) == CURRENT_TRAVERSAL_RELATIONSHIP_TYPES

    def test_current_set_is_strict_subset_of_supported(self):
        assert CURRENT_TRAVERSAL_RELATIONSHIP_TYPES < SUPPORTED_TRAVERSAL_RELATIONSHIP_TYPES
        assert len(CURRENT_TRAVERSAL_RELATIONSHIP_TYPES) == 3
        assert len(SUPPORTED_TRAVERSAL_RELATIONSHIP_TYPES) - len(CURRENT_TRAVERSAL_RELATIONSHIP_TYPES) == 4

    def test_supported_set_intersects_relationship_types_module(self):
        # The 6 types in SUPPORTED_CI_RELATIONSHIP_TYPES are all in the
        # supported traversal set; CONNECTED_VIA is the only traversal type
        # NOT in SUPPORTED_CI_RELATIONSHIP_TYPES (it is the PhysicalLink
        # relationship, not a CI-CI relationship).
        assert SUPPORTED_CI_RELATIONSHIP_TYPES <= SUPPORTED_TRAVERSAL_RELATIONSHIP_TYPES
        assert "CONNECTED_VIA" in SUPPORTED_TRAVERSAL_RELATIONSHIP_TYPES
        assert "CONNECTED_VIA" not in SUPPORTED_CI_RELATIONSHIP_TYPES

    def test_supported_ci_relationship_types_unchanged_in_pr1(self):
        # PR1 must not modify relationship_types.py; the supported CI
        # relationship types stay at 6 (the 4 new traversal types
        # CONNECTED_VIA / MANAGES / USES / PROVIDES do not change this set
        # because MANAGES / USES / PROVIDES were already there; only
        # CONNECTED_VIA is new and it's a PhysicalLink rel, not a CI rel).
        assert frozenset({
            "CONNECTS_TO",
            "DEPENDS_ON",
            "HOSTED_ON",
            "MANAGES",
            "USES",
            "PROVIDES",
        }) == SUPPORTED_CI_RELATIONSHIP_TYPES


# ---------------------------------------------------------------------------
# Feature flag names
# ---------------------------------------------------------------------------


class TestFeatureFlagNames:
    def test_physical_link_flag_name(self):
        assert (
            FEATURE_FLAG_PHYSICAL_LINK_CORRELATION
            == "FEATURE_CMDB_CORRELATION_PHYSICAL_LINK_PROPAGATION_ENABLED"
        )

    def test_manages_uses_provides_flag_name(self):
        assert (
            FEATURE_FLAG_MANAGES_USES_PROVIDES_CORRELATION
            == "FEATURE_CMDB_CORRELATION_MANAGES_USES_PROVIDES_ENABLED"
        )

    def test_connects_to_medium_filter_flag_name(self):
        assert (
            FEATURE_FLAG_CONNECTS_TO_MEDIUM_FILTER
            == "FEATURE_CMDB_CORRELATION_CONNECTS_TO_MEDIUM_FILTER_ENABLED"
        )

    @pytest.mark.parametrize("flag", [
        FEATURE_FLAG_PHYSICAL_LINK_CORRELATION,
        FEATURE_FLAG_MANAGES_USES_PROVIDES_CORRELATION,
        FEATURE_FLAG_CONNECTS_TO_MEDIUM_FILTER,
    ])
    def test_flag_name_starts_with_feature_cmdb_correlation_prefix(self, flag):
        assert flag.startswith("FEATURE_CMDB_CORRELATION_")

    @pytest.mark.parametrize("flag", [
        FEATURE_FLAG_PHYSICAL_LINK_CORRELATION,
        FEATURE_FLAG_MANAGES_USES_PROVIDES_CORRELATION,
        FEATURE_FLAG_CONNECTS_TO_MEDIUM_FILTER,
    ])
    def test_flag_name_ends_with_enabled(self, flag):
        assert flag.endswith("_ENABLED")


# ---------------------------------------------------------------------------
# Parametrized: every locked value is a non-empty string
# ---------------------------------------------------------------------------


class TestLockedValuesAreValid:
    @pytest.mark.parametrize("name,value", [
        ("physical_link_unknown_propagation", PHYSICAL_LINK_UNKNOWN_PROPAGATION),
        ("physical_link_status_freshness", PHYSICAL_LINK_STATUS_FRESHNESS),
        ("physical_link_down_behavior", PHYSICAL_LINK_DOWN_BEHAVIOR),
        ("manages_uses_provides_default", MANAGES_USES_PROVIDES_DEFAULT),
    ])
    def test_value_is_non_empty_string(self, name, value):
        assert isinstance(value, str)
        assert value, f"{name} must be a non-empty string"

    @pytest.mark.parametrize("name,value", [
        ("physical_link_unknown_propagation", PHYSICAL_LINK_UNKNOWN_PROPAGATION),
        ("physical_link_status_freshness", PHYSICAL_LINK_STATUS_FRESHNESS),
        ("physical_link_down_behavior", PHYSICAL_LINK_DOWN_BEHAVIOR),
        ("manages_uses_provides_default", MANAGES_USES_PROVIDES_DEFAULT),
    ])
    def test_value_is_snake_case(self, name, value):
        # No spaces, no uppercase, no leading underscore.
        assert " " not in value, f"{name}={value!r} must not contain spaces"
        assert value == value.lower(), f"{name}={value!r} must be lowercase"
        assert not value.startswith("_"), f"{name}={value!r} must not start with underscore"
