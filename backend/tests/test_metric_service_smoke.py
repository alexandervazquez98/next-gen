"""Smoke tests for metric_service — verify the import path and basic structure.

These are intentionally minimal to confirm the test infrastructure works.
Full metric reconciliation tests should go in test_metric_reconciliation.py.
"""

import pytest
from unittest.mock import patch, MagicMock

from models.core import MetricDef


class TestMetricServiceImports:
    """Verify that metric_service can be imported and its functions exist."""

    def test_metric_service_imports(self):
        """The module should import without errors."""
        from services import metric_service

        assert hasattr(metric_service, "get_metrics")
        assert hasattr(metric_service, "create_metric")
        assert hasattr(metric_service, "delete_metric")
        assert hasattr(metric_service, "get_metric_usage")
        assert hasattr(metric_service, "promote_metric_node")
        assert hasattr(metric_service, "get_applicable_metrics")
        assert hasattr(metric_service, "reconcile_node_metrics")

    def test_metricdef_model_valid(self, sample_metric_def):
        """MetricDef Pydantic model should accept a standard payload."""
        metric = MetricDef(**sample_metric_def)
        assert metric.id == "cpu-load"
        assert metric.protocol == "SNMP"
        assert metric.warning == 80.0
        assert metric.critical == 95.0
        assert metric.applicable_to["brands"] == ["cisco"]


class TestMetricServiceSmoke:
    """Minimal smoke tests with mocked DB to verify the mocking infrastructure."""

    def test_get_metrics_returns_empty_with_mock(self, mock_neo4j_session):
        """get_metrics should return empty list when no metrics exist."""
        mock_neo4j_session.set_response("metricdef", [])

        from services.metric_service import get_metrics

        result = get_metrics()

        assert result == []

    def test_get_metrics_returns_data_with_mock(self, mock_neo4j_session):
        """get_metrics should parse Neo4j records correctly."""
        mock_neo4j_session.set_response(
            "metricdef",
            [
                {
                    "m": {
                        "id": "cpu-load",
                        "protocol": "SNMP",
                        "warning": 80.0,
                        "critical": 95.0,
                        "oid": "1.2.3",
                        "dataType": "INTEGER",
                        "unit": "%",
                        "description": "CPU",
                        "criticality": 2,
                        "applicable_to": '{"brands": ["cisco"]}',
                    }
                }
            ],
        )

        from services.metric_service import get_metrics

        result = get_metrics()

        assert len(result) == 1
        assert result[0]["id"] == "cpu-load"
        assert result[0]["protocol"] == "SNMP"

    def test_create_metric_calls_merge(self, mock_neo4j_session):
        """create_metric should execute a MERGE query."""
        from services.metric_service import create_metric
        from models.core import MetricDef

        metric = MetricDef(id="test-metric", protocol="SNMP")
        with patch("services.metric_service._reconcile_metric_assignments") as mock_reconcile:
            create_metric(metric)

        # Verify a query was executed
        assert len(mock_neo4j_session.queries) >= 1
        assert "merge" in mock_neo4j_session.queries[0]["query"].lower()
        mock_reconcile.assert_called_once_with("test-metric", None)

    def test_delete_metric_calls_detach_delete(self, mock_neo4j_session):
        """delete_metric should execute a DETACH DELETE query."""
        from services.metric_service import delete_metric

        delete_metric("test-metric")

        assert len(mock_neo4j_session.queries) >= 1
        assert "detach delete" in mock_neo4j_session.queries[0]["query"].lower()


class TestMetricMatching:
    def test_metric_matches_ci_requires_all_populated_filters(self):
        from services.metric_service import metric_matches_ci

        criteria = {
            "brands": ["Cambium Networks"],
            "models": ["450i"],
            "layers": [],
            "names": [],
            "excluded_names": [],
        }

        assert metric_matches_ci(criteria, {"brand": "Cambium Networks", "model": "450i"}) is True
        assert metric_matches_ci(criteria, {"brand": "Cambium Networks", "model": "45700"}) is False
        assert metric_matches_ci(criteria, {"brand": "Other", "model": "450i"}) is False

    def test_metric_matches_ci_allows_name_plus_category_filters(self):
        from services.metric_service import metric_matches_ci

        criteria = {
            "brands": ["Cisco"],
            "models": [],
            "layers": [],
            "names": ["Router-01"],
            "excluded_names": [],
        }

        assert metric_matches_ci(criteria, {"id": "ci-1", "name": "Router-01", "brand": "Cisco"}) is True
        assert metric_matches_ci(criteria, {"id": "ci-1", "name": "Router-01", "brand": "Juniper"}) is False

    def test_metric_matches_ci_applies_exclusions_last(self):
        from services.metric_service import metric_matches_ci

        criteria = {
            "brands": ["Cisco"],
            "models": [],
            "layers": [],
            "names": [],
            "excluded_names": ["Router-01"],
        }

        assert metric_matches_ci(criteria, {"id": "ci-1", "name": "Router-01", "brand": "Cisco"}) is False


class TestMetricUsageQuery:
    def test_get_metric_usage_returns_consistent_union_columns(self):
        from services.metric_service import get_metric_usage

        seen_queries = []

        class SingleResult:
            def single(self):
                return {"apt": '{"brands": ["Cambium Networks"], "models": ["450i"], "excluded_names": []}'}

        class ListResult(list):
            pass

        class FakeSession:
            def run(self, query, **params):
                return side_effect(query, **params)

        class FakeDriver:
            def session(self):
                return self

            def __enter__(self):
                return FakeSession()

            def __exit__(self, exc_type, exc, tb):
                return False

        def side_effect(query, **params):
            seen_queries.append(query)
            if "RETURN m.applicable_to as apt" in query:
                return SingleResult()

            return ListResult([])

        with patch("services.metric_service.get_db", return_value=FakeDriver()):
            get_metric_usage("cmb450i-cpu-util")

        metric_query = next(query for query in seen_queries if "MATCH (n:CI)-[:HAS_METRIC]" in query)
        assert metric_query.count("RETURN n.id as id, n.name as name, n.ip as ip, n.model as model, n.brand as brand, n.layer as layer") == 2
