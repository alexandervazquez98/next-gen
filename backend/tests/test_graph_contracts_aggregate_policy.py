"""aggregate_policy + safe_geo_precision tests (#390).

Split out of test_graph_contracts.py so each contract module ships with
its own focused test file (work-unit commits).
"""

from __future__ import annotations

import pytest


class TestAggregatePolicy:
    """Aggregate disclosure rules and tiered safe_geo_precision (REQ-9).

    - ``minimum_count`` default 5.
    - ``permission_required`` defaults to ``graph:aggregate_breakdown:read``
      (this string is the agreed name; adding it to ``UserPermission`` is a
      prerequisite for #391).
    - ``derive_safe_geo_precision(visible_count, minimum_count)``:
        * ``< minimum``          -> ``"none"``
        * ``< minimum * 4``      -> ``"region"``
        * otherwise              -> ``"city"``
    """

    def test_policy_default_constants(self):
        from contracts.aggregate_policy import (
            DEFAULT_MINIMUM_COUNT,
            PERMISSION_REQUIRED,
            AggregatePolicy,
        )

        assert DEFAULT_MINIMUM_COUNT == 5
        assert PERMISSION_REQUIRED == "graph:aggregate_breakdown:read"

        policy = AggregatePolicy()
        assert policy.minimum_count == DEFAULT_MINIMUM_COUNT
        assert policy.permission_required == PERMISSION_REQUIRED

    def test_policy_custom_minimum(self):
        from contracts.aggregate_policy import AggregatePolicy

        policy = AggregatePolicy(minimum_count=10)
        assert policy.minimum_count == 10

    def test_policy_rejects_invalid_minimum(self):
        from contracts.aggregate_policy import AggregatePolicy

        with pytest.raises(ValueError):
            AggregatePolicy(minimum_count=0)
        with pytest.raises(ValueError):
            AggregatePolicy(minimum_count=-1)

    @pytest.mark.parametrize(
        "visible,expected",
        [
            # below minimum -> none
            (0, "none"),
            (1, "none"),
            (4, "none"),
            # at minimum (still below minimum*4) -> region
            (5, "region"),
            (6, "region"),
            (19, "region"),
            # at minimum*4 or above -> city
            (20, "city"),
            (21, "city"),
            (100, "city"),
        ],
    )
    def test_derive_safe_geo_precision_tiered(self, visible, expected):
        from contracts.aggregate_policy import (
            SafeGeoPrecision,
            derive_safe_geo_precision,
        )

        # Minimum = 5 (default), minimum*4 = 20.
        assert derive_safe_geo_precision(visible, 5) == expected
        assert isinstance(expected, str)
        # Confirm value is one of the allowed enum members.
        assert expected in {m.value for m in SafeGeoPrecision}

    def test_derive_safe_geo_precision_respects_custom_minimum(self):
        from contracts.aggregate_policy import derive_safe_geo_precision

        # minimum=10, minimum*4=40
        assert derive_safe_geo_precision(9, 10) == "none"
        assert derive_safe_geo_precision(10, 10) == "region"
        assert derive_safe_geo_precision(40, 10) == "city"

    def test_safe_geo_precision_enum_members(self):
        from contracts.aggregate_policy import SafeGeoPrecision

        assert SafeGeoPrecision.NONE.value == "none"
        assert SafeGeoPrecision.REGION.value == "region"
        assert SafeGeoPrecision.CITY.value == "city"
