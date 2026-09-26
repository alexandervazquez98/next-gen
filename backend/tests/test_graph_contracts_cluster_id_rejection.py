"""cluster_id rejection + axis conflict tests (#390).

Split out of test_graph_contracts.py so each contract module ships with
its own focused test file (work-unit commits).
"""

from __future__ import annotations

import pytest


class TestClusterIdRejection:
    """Malformed inputs and conflicting axis parameter."""

    @pytest.mark.parametrize(
        "bad_id",
        [
            "foo bar",  # contains space, no colon separator
            "",  # empty
            ":",  # empty axis and key
            "location:",  # empty key
            ":dc-1",  # empty axis
            "tenant:dc-1",  # axis not yet accepted
            "location/dc-1",  # contains / inside axis position
            "location:dc/1",  # contains / in key
            "location:" + ("a" * 129),  # key too long
            "location:dc 1",  # internal whitespace not allowed
            "location:dc!1",  # unsafe punctuation
        ],
    )
    def test_invalid_cluster_id_returns_structured_error(self, bad_id):
        """Malformed cluster_id yields InvalidClusterIdError with no metadata leak."""
        from contracts.cluster_id import InvalidClusterIdError, parse_cluster_id

        with pytest.raises(InvalidClusterIdError) as excinfo:
            parse_cluster_id(bad_id)

        err = excinfo.value
        # Body shape: {error, reason, cluster_id} — no label/count/geo.
        body = err.as_error_body()
        assert body["error"] == "invalid_cluster_id"
        assert "label" not in body
        assert "count" not in body
        assert "geo" not in body
        assert "location_name" not in body
        assert body["cluster_id"] == bad_id
        # Mapping to HTTP semantics lives in the route handler (#391); the codec
        # only asserts the body shape — no 4xx here.

    def test_axis_conflict_rejected_before_lookup(self):
        """A conflicting ``?axis=`` must reject BEFORE any cluster existence check.

        The codec exposes a single-purpose guard ``assert_axis_matches`` that
        raises ``AxisConflictError`` when the supplied query axis conflicts with
        the parsed cluster_id axis. The guard MUST NOT depend on whether the
        cluster actually exists.
        """
        from contracts.cluster_id import AxisConflictError, assert_axis_matches, parse_cluster_id

        parsed = parse_cluster_id("location:dc-1")
        with pytest.raises(AxisConflictError) as excinfo:
            assert_axis_matches(parsed, "tenant")
        body = excinfo.value.as_error_body()
        assert body["error"] == "axis_conflict"

    def test_axis_conflict_no_metadata_leak(self):
        """axis_conflict body MUST NOT leak any cluster metadata."""
        from contracts.cluster_id import AxisConflictError, assert_axis_matches, parse_cluster_id

        parsed = parse_cluster_id("location:dc-1")
        with pytest.raises(AxisConflictError) as excinfo:
            assert_axis_matches(parsed, "tenant")
        body = excinfo.value.as_error_body()
        # No cluster label, key, count, geo, location_name in the body.
        for forbidden in ("label", "key", "count", "geo", "location_name"):
            assert forbidden not in body
