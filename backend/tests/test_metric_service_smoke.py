"""Smoke tests for metric_service — verify the import path and basic structure.

These are intentionally minimal to confirm the test infrastructure works.
Full metric reconciliation tests should go in test_metric_reconciliation.py.
"""

import pytest
from unittest.mock import patch, MagicMock

from models.core import MetricDef


class SequentialResult:
    def __init__(self, record):
        self.record = record

    def single(self):
        return self.record


class SequentialMetricDeleteSession:
    """Purpose-built fake for metric deletion orchestration tests."""

    def __init__(self, *, events_recovered=0, metric_exists=True, relationship_batches=None, node_deleted=1):
        self.events_recovered = events_recovered
        self.metric_exists = metric_exists
        self.relationship_batches = list(relationship_batches or [])
        self.node_deleted = node_deleted
        self.queries = []

    def run(self, query, **params):
        self.queries.append({"query": query, "params": params})
        query_lower = query.lower()

        if "events_recovered" in query_lower:
            return SequentialResult({"events_recovered": self.events_recovered})
        if "metric_exists" in query_lower:
            return SequentialResult({"metric_exists": self.metric_exists})
        if "relationships_deleted" in query_lower:
            deleted = self.relationship_batches.pop(0)
            return SequentialResult({"relationships_deleted": deleted})
        if "node_deleted" in query_lower:
            return SequentialResult({"node_deleted": self.node_deleted})

        return SequentialResult({})

    def begin_transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class SequentialDriver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session


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

    def test_delete_metric_recovers_events_then_deletes_relationships_in_batches(self):
        """delete_metric should avoid DETACH DELETE and clean large fan-out in bounded batches."""
        from services.metric_service import delete_metric

        session = SequentialMetricDeleteSession(
            events_recovered=3,
            metric_exists=True,
            relationship_batches=[50000, 43575, 0],
            node_deleted=1,
        )

        with patch("services.metric_service.get_db", return_value=SequentialDriver(session)):
            result = delete_metric("test-metric")

        assert result == {
            "message": "Metric deleted",
            "metric_id": "test-metric",
            "deleted": True,
            "events_recovered": 3,
            "relationships_deleted": 93575,
            "relationship_batches": [50000, 43575],
            "history_retained": True,
        }

        queries = [entry["query"].lower() for entry in session.queries]
        assert len(queries) >= 5
        assert "match (e:event)" in queries[0]
        assert "collection_failure" in queries[0]
        assert "recovered" in queries[0]
        assert all("detach delete" not in query for query in queries)

        relationship_delete_queries = [query for query in queries if "relationships_deleted" in query]
        assert len(relationship_delete_queries) == 3
        assert all("limit $batch_size" in query for query in relationship_delete_queries)
        assert queries.index(relationship_delete_queries[-1]) < next(
            index for index, query in enumerate(queries) if "node_deleted" in query
        )

    def test_delete_metric_is_idempotent_when_definition_missing(self):
        """delete_metric should return a deterministic response when the MetricDef is absent."""
        from services.metric_service import delete_metric

        session = SequentialMetricDeleteSession(events_recovered=0, metric_exists=False)

        with patch("services.metric_service.get_db", return_value=SequentialDriver(session)):
            result = delete_metric("missing-metric")

        assert result == {
            "message": "Metric not found",
            "metric_id": "missing-metric",
            "deleted": False,
            "events_recovered": 0,
            "relationships_deleted": 0,
            "relationship_batches": [],
            "history_retained": True,
        }
        queries = [entry["query"].lower() for entry in session.queries]
        assert any("metric_exists" in query for query in queries)
        assert all("relationships_deleted" not in query for query in queries)
        assert all("detach delete" not in query for query in queries)

    def test_delete_metric_deletes_existing_metric_with_no_relationships(self):
        """An existing bare MetricDef should still be deleted after a zero cleanup batch."""
        from services.metric_service import delete_metric

        session = SequentialMetricDeleteSession(
            events_recovered=0,
            metric_exists=True,
            relationship_batches=[0],
            node_deleted=1,
        )

        with patch("services.metric_service.get_db", return_value=SequentialDriver(session)):
            result = delete_metric("bare-metric")

        assert result["deleted"] is True
        assert result["relationships_deleted"] == 0
        assert result["relationship_batches"] == []
        queries = [entry["query"].lower() for entry in session.queries]
        assert any("relationships_deleted" in query for query in queries)
        assert any("node_deleted" in query for query in queries)
        assert all("detach delete" not in query for query in queries)

    def test_delete_metric_propagates_relationship_cleanup_failure_without_detach_delete(self):
        """Cleanup failures should surface while keeping the deletion path free of DETACH DELETE."""
        from services.metric_service import delete_metric

        class FailingRelationshipCleanupSession(SequentialMetricDeleteSession):
            def run(self, query, **params):
                if "relationships_deleted" in query.lower():
                    self.queries.append({"query": query, "params": params})
                    raise RuntimeError("relationship cleanup failed")
                return super().run(query, **params)

        session = FailingRelationshipCleanupSession(events_recovered=2, metric_exists=True)

        with patch("services.metric_service.get_db", return_value=SequentialDriver(session)):
            with pytest.raises(RuntimeError, match="relationship cleanup failed"):
                delete_metric("test-metric")

        assert all("detach delete" not in entry["query"].lower() for entry in session.queries)


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
