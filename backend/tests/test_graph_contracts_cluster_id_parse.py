"""cluster_id parse tests (#390).

Split out of test_graph_contracts.py so each contract module ships with
its own focused test file (work-unit commits).
"""


class TestClusterIdParse:
    """Valid parse scenarios."""

    def test_parse_valid_location_id(self):
        from contracts.cluster_id import parse_cluster_id

        parsed = parse_cluster_id("location:dc-1")
        assert parsed.axis == "location"
        assert parsed.key == "dc-1"
        assert parsed.display_label == "dc-1"

    def test_parse_unassigned_sentinel(self):
        from contracts.cluster_id import parse_cluster_id

        parsed = parse_cluster_id("location:__unassigned__")
        assert parsed.axis == "location"
        assert parsed.key == "__unassigned__"
        assert parsed.display_label == "Unassigned"

    def test_case_insensitive_match(self):
        """``location:DC-1`` and ``location:dc-1`` must resolve to the same cluster."""
        from contracts.cluster_id import cluster_ids_equal, parse_cluster_id

        upper = parse_cluster_id("location:DC-1")
        lower = parse_cluster_id("location:dc-1")
        assert cluster_ids_equal(upper, lower)
        # Canonical display preserves the original case from the first occurrence.
        assert upper.display_label == "DC-1"

    def test_parse_idempotent(self):
        """Parsing the same id twice returns equal ClusterId values."""
        from contracts.cluster_id import cluster_ids_equal, parse_cluster_id

        a = parse_cluster_id("location:dc-1")
        b = parse_cluster_id("location:dc-1")
        assert cluster_ids_equal(a, b)
