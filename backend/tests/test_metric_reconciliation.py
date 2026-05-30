"""
Tests for reconcile_node_metrics with AppliedDictionary overlay.

Task 5.5: Unit tests for reconcile_node_metrics with AppliedDictionary
Task 5.6: Unit test: deleting AppliedDictionary restores criteria-based metrics
Task 5.7: Run existing metric reconcile test suite — verify no regression
"""

import pytest
from unittest.mock import MagicMock, patch, call


class FakeRecord(dict):
    """Fake Neo4j record that supports both .get() and dict-like access."""
    def __init__(self, data):
        super().__init__(data)
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __getitem__(self, key):
        return self._data[key]


class FakeResult:
    """Fake Neo4j result set that can be iterated and called .single()."""
    def __init__(self, records):
        self._records = records
        self._index = 0

    def __iter__(self):
        self._index = 0
        return iter(self._records)

    def single(self):
        if self._records:
            return self._records[0]
        return None


class TestReconcileNodeMetricsWithAppliedDictionary:
    """Verify effective metric set computation: (applicable ∪ dict) - excluded + extra."""

    def _build_run_side_effect(self, responses_by_keyword):
        """
        Build a session.run side_effect from a dict of keyword -> FakeResult.
        responses_by_keyword: dict mapping query substring -> FakeResult
        """
        def run_side_effect(query, **params):
            q = query.lower()
            for keyword, result in responses_by_keyword.items():
                if keyword.lower() in q:
                    return result
            return FakeResult([])

        return run_side_effect

    @patch("services.metric_service.get_db")
    @patch("services.metric_service.get_applicable_metrics")
    def test_no_applied_dictionary_behavior_unchanged(
        self, mock_get_applicable, mock_get_db
    ):
        """
        When CI has no AppliedDictionary, reconcile uses applicable_metrics only.
        This is the baseline regression test.
        """
        from services.metric_service import reconcile_node_metrics

        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_get_db.return_value = mock_driver

        # Provide enough responses for all session.run() calls:
        # 1. HAS_DICTIONARY lookup → None
        # 2. linked metrics query → []
        # 3+. MERGE calls for each applicable metric (2 in this case)
        responses = {
            "has_dictionary": FakeResult([]),
            "has_metric": FakeResult([]),
        }
        mock_session.run.side_effect = self._build_run_side_effect(responses)

        mock_get_applicable.return_value = [
            {"id": "cpu-load", "name": "cpu-load", "description": "CPU", "unit": "%"},
            {"id": "mem-used", "name": "mem-used", "description": "Memory", "unit": "%"},
        ]

        reconcile_node_metrics({"id": "ci-001", "name": "Router-01"})

        mock_get_applicable.assert_called_once_with("ci-001")

    @patch("services.metric_service.get_db")
    @patch("services.metric_service.get_applicable_metrics")
    def test_applied_dictionary_adds_dictionary_metrics(
        self, mock_get_applicable, mock_get_db
    ):
        """
        effective = (applicable ∪ dict_metrics) - excluded + extra
        When AppliedDictionary exists with a dictionary, dictionary metrics are included.
        """
        from services.metric_service import reconcile_node_metrics

        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_get_db.return_value = mock_driver

        ad_record = FakeRecord({
            "dictionary_id": "dict-001",
            "excluded_metrics": [],
            "extra_metrics": [],
            "md_id": "dict-001",
        })

        responses = {
            "has_dictionary": FakeResult([ad_record]),
            "has_metric": FakeResult([]),   # no currently-linked metrics
        }
        mock_session.run.side_effect = self._build_run_side_effect(responses)

        mock_get_applicable.return_value = [
            {"id": "cpu-load", "name": "cpu-load", "description": "CPU", "unit": "%"},
        ]

        with patch("services.dictionary_service.get_metrics_from_dictionary") as mock_dict_metrics:
            mock_dict_metrics.return_value = ["cpu-load", "mem-used", "disk-used"]

            reconcile_node_metrics({"id": "ci-001", "name": "Router-01"})

            mock_dict_metrics.assert_called_once_with("dict-001")

            # Verify metrics were added via MERGE
            merge_calls = [
                c for c in mock_session.run.call_args_list
                if "MERGE" in c[0][0]
            ]
            assert len(merge_calls) >= 2  # mem-used and disk-used

    @patch("services.metric_service.get_db")
    @patch("services.metric_service.get_applicable_metrics")
    def test_applied_dictionary_excluded_metrics_removed(
        self, mock_get_applicable, mock_get_db
    ):
        """
        effective = (applicable ∪ dict) - excluded + extra
        Metrics in excluded_metrics are NOT added even if in applicable or dict.
        """
        from services.metric_service import reconcile_node_metrics

        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_get_db.return_value = mock_driver

        ad_record = FakeRecord({
            "dictionary_id": "dict-001",
            "excluded_metrics": ["cpu-load"],  # cpu-load excluded
            "extra_metrics": [],
            "md_id": "dict-001",
        })

        responses = {
            "has_dictionary": FakeResult([ad_record]),
            "has_metric": FakeResult([]),
        }
        mock_session.run.side_effect = self._build_run_side_effect(responses)

        mock_get_applicable.return_value = [
            {"id": "cpu-load", "name": "cpu-load", "description": "CPU", "unit": "%"},
        ]

        with patch("services.dictionary_service.get_metrics_from_dictionary") as mock_dict_metrics:
            mock_dict_metrics.return_value = ["cpu-load", "mem-used"]

            reconcile_node_metrics({"id": "ci-001", "name": "Router-01"})

            # cpu-load should NOT be added (it's excluded)
            merge_calls = [
                c for c in mock_session.run.call_args_list
                if "MERGE" in c[0][0]
            ]
            added_mids = [c[1].get("mid") for c in merge_calls if c[1].get("mid")]
            assert "cpu-load" not in added_mids
            assert "mem-used" in added_mids

    @patch("services.metric_service.get_db")
    @patch("services.metric_service.get_applicable_metrics")
    def test_applied_dictionary_extra_metrics_added(
        self, mock_get_applicable, mock_get_db
    ):
        """
        effective = (applicable ∪ dict) - excluded + extra
        Extra metrics are added even if they don't match criteria or dictionary.
        """
        from services.metric_service import reconcile_node_metrics

        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_get_db.return_value = mock_driver

        ad_record = FakeRecord({
            "dictionary_id": "dict-001",
            "excluded_metrics": [],
            "extra_metrics": ["custom-metric"],
            "md_id": "dict-001",
        })

        responses = {
            "has_dictionary": FakeResult([ad_record]),
            "has_metric": FakeResult([]),
        }
        mock_session.run.side_effect = self._build_run_side_effect(responses)

        mock_get_applicable.return_value = []

        with patch("services.dictionary_service.get_metrics_from_dictionary") as mock_dict_metrics:
            mock_dict_metrics.return_value = []

            reconcile_node_metrics({"id": "ci-001", "name": "Router-01"})

            merge_calls = [c for c in mock_session.run.call_args_list if "MERGE" in c[0][0]]
            added_mids = [c[1].get("mid") for c in merge_calls if c[1].get("mid")]
            assert "custom-metric" in added_mids

    @patch("services.metric_service.get_db")
    @patch("services.metric_service.get_applicable_metrics")
    def test_dictionary_deleted_graceful_fallback(
        self, mock_get_applicable, mock_get_db
    ):
        """
        Edge case: AppliedDictionary exists but dictionary no longer exists.
        Should skip dictionary metrics and use applicable only.
        """
        from services.metric_service import reconcile_node_metrics

        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_get_db.return_value = mock_driver

        ad_record = FakeRecord({
            "dictionary_id": "deleted-dict",
            "excluded_metrics": [],
            "extra_metrics": [],
            "md_id": None,  # dictionary deleted
        })

        responses = {
            "has_dictionary": FakeResult([ad_record]),
            "has_metric": FakeResult([]),
        }
        mock_session.run.side_effect = self._build_run_side_effect(responses)

        mock_get_applicable.return_value = [
            {"id": "cpu-load", "name": "cpu-load", "description": "CPU", "unit": "%"},
        ]

        with patch("services.dictionary_service.get_metrics_from_dictionary") as mock_dict_metrics:
            mock_dict_metrics.side_effect = Exception("Dictionary not found")

            reconcile_node_metrics({"id": "ci-001", "name": "Router-01"})

            merge_calls = [c for c in mock_session.run.call_args_list if "MERGE" in c[0][0]]
            added_mids = [c[1].get("mid") for c in merge_calls if c[1].get("mid")]
            assert "cpu-load" in added_mids

    @patch("services.metric_service.get_db")
    @patch("services.metric_service.get_applicable_metrics")
    def test_preserves_icmp_latency_and_jitter_sidecars_when_not_applicable(
        self, mock_get_applicable, mock_get_db
    ):
        """
        ICMP latency/jitter are derived sidecars linked by ping provisioning.
        Generic reconciliation must not remove them just because they do not
        match brand/model/dictionary criteria.
        """
        from services.metric_service import reconcile_node_metrics

        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_get_db.return_value = mock_driver

        linked_records = [
            FakeRecord({"mid": "icmp_latency_ms", "apt": None}),
            FakeRecord({"mid": "icmp_jitter_ms", "apt": None}),
            FakeRecord({"mid": "old-metric", "apt": "{}"}),
        ]

        responses = {
            "has_dictionary": FakeResult([]),
            "return m.id as mid": FakeResult(linked_records),
            "delete": FakeResult([]),
        }
        mock_session.run.side_effect = self._build_run_side_effect(responses)
        mock_get_applicable.return_value = []

        reconcile_node_metrics({"id": "ci-001", "name": "Router-01", "ip": "10.0.0.1"})

        delete_mids = [
            c[1].get("mid")
            for c in mock_session.run.call_args_list
            if "delete r" in c[0][0].lower()
        ]
        assert "old-metric" in delete_mids
        assert "icmp_latency_ms" not in delete_mids
        assert "icmp_jitter_ms" not in delete_mids

    @patch("services.metric_service.get_db")
    @patch("services.metric_service.get_applicable_metrics")
    def test_removes_icmp_sidecars_when_ci_no_longer_has_ip(
        self, mock_get_applicable, mock_get_db
    ):
        """Removing a CI IP should deprovision ICMP sidecars during reconcile."""
        from services.metric_service import reconcile_node_metrics

        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_get_db.return_value = mock_driver

        linked_records = [
            FakeRecord({"mid": "icmp_latency_ms", "apt": None}),
            FakeRecord({"mid": "icmp_jitter_ms", "apt": None}),
        ]
        responses = {
            "has_dictionary": FakeResult([]),
            "return m.id as mid": FakeResult(linked_records),
            "delete": FakeResult([]),
        }
        mock_session.run.side_effect = self._build_run_side_effect(responses)
        mock_get_applicable.return_value = []

        reconcile_node_metrics({"id": "ci-001", "name": "Router-01", "ip": None})

        delete_mids = [
            c[1].get("mid")
            for c in mock_session.run.call_args_list
            if "delete r" in c[0][0].lower()
        ]
        assert "icmp_latency_ms" in delete_mids
        assert "icmp_jitter_ms" in delete_mids

    @patch("services.metric_service.get_db")
    @patch("services.metric_service.get_applicable_metrics")
    def test_removes_obsolete_metrics_from_previous_dictionary(
        self, mock_get_applicable, mock_get_db
    ):
        """
        If a metric was linked before but is no longer in effective set,
        it should be removed.
        """
        from services.metric_service import reconcile_node_metrics

        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_get_db.return_value = mock_driver

        ad_record = FakeRecord({
            "dictionary_id": "dict-001",
            "excluded_metrics": [],
            "extra_metrics": [],
            "md_id": "dict-001",
        })

        # Currently linked: old-metric (no longer applicable)
        linked_record = FakeRecord({"mid": "old-metric", "apt": "{}"})

        responses = {
            "has_dictionary": FakeResult([ad_record]),
            "has_metric": FakeResult([linked_record]),
            "delete": FakeResult([]),
        }
        mock_session.run.side_effect = self._build_run_side_effect(responses)

        mock_get_applicable.return_value = []

        with patch("services.dictionary_service.get_metrics_from_dictionary") as mock_dict_metrics:
            mock_dict_metrics.return_value = []

            reconcile_node_metrics({"id": "ci-001", "name": "Router-01"})

            # old-metric should be deleted
            delete_calls = [
                c for c in mock_session.run.call_args_list
                if "delete" in c[0][0].lower()
            ]
            assert len(delete_calls) >= 1


class TestReconcileNodeMetricsSmoke:
    """Smoke tests: reconcile_node_metrics still imports and runs without error."""

    def test_reconcile_node_metrics_importable(self):
        """reconcile_node_metrics should be importable from metric_service."""
        from services.metric_service import reconcile_node_metrics
        assert callable(reconcile_node_metrics)

    @patch("services.metric_service.get_db")
    def test_reconcile_node_metrics_runs_without_error(self, mock_get_db):
        """reconcile_node_metrics should not raise when called with valid node."""
        from services.metric_service import reconcile_node_metrics

        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_get_db.return_value = mock_driver

        def run_side_effect(query, **params):
            q = query.lower()
            if "has_dictionary" in q:
                return FakeResult([])
            elif "has_metric" in q:
                return FakeResult([])
            return FakeResult([])

        mock_session.run.side_effect = run_side_effect

        with patch("services.metric_service.get_applicable_metrics", return_value=[]):
            reconcile_node_metrics({"id": "ci-test", "name": "TestNode"})

    @patch("services.metric_service.get_db")
    def test_reconcile_node_metrics_returns_early_on_missing_id(self, mock_get_db):
        """reconcile_node_metrics should return early if node has no id."""
        from services.metric_service import reconcile_node_metrics

        reconcile_node_metrics({})


class TestReconcileMetricAssignments:
    @patch("services.metric_service.get_db")
    @patch("services.metric_service.reconcile_node_metrics")
    def test_reconcile_metric_assignments_includes_matching_and_linked_nodes(
        self, mock_reconcile_node_metrics, mock_get_db
    ):
        from services.metric_service import _reconcile_metric_assignments

        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_get_db.return_value = mock_driver

        mock_session.run.return_value = FakeResult(
            [
                FakeRecord(
                    {
                        "node": {"id": "ci-match", "name": "AP-1", "brand": "Cambium Networs", "model": "450i"},
                        "currently_linked": False,
                    }
                ),
                FakeRecord(
                    {
                        "node": {"id": "ci-linked", "name": "Router-1", "brand": "Other", "model": "Other"},
                        "currently_linked": True,
                    }
                ),
                FakeRecord(
                    {
                        "node": {"id": "ci-skip", "name": "Router-2", "brand": "Other", "model": "Other"},
                        "currently_linked": False,
                    }
                ),
            ]
        )

        _reconcile_metric_assignments(
            "cmb450i-cpu-util",
            {"brands": ["Cambium Networs"], "models": ["450i"], "layers": [], "names": [], "excluded_names": []},
        )

        assert mock_reconcile_node_metrics.call_count == 2
        mock_reconcile_node_metrics.assert_any_call(
            {"id": "ci-match", "name": "AP-1", "brand": "Cambium Networs", "model": "450i"}
        )
        mock_reconcile_node_metrics.assert_any_call(
            {"id": "ci-linked", "name": "Router-1", "brand": "Other", "model": "Other"}
        )
        mock_get_db.return_value.session.return_value.__enter__.return_value.session \
            .assert_not_called()
