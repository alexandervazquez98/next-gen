"""feat-539 / T4 — the degraded PROPAGATED child must reach the operator feed.

Spec S2: "the default operator feed exposes the explicitly degraded child so
the operator can see the WARNING downgrade, while ordinary PROPAGATED children
remain collapsed into their ROOT to preserve the existing no-double-count
behavior."

The modern SNMP path materializes a separate WARNING PROPAGATED child when a
correlation crosses a PhysicalLink whose status is UNKNOWN. The child carries
the markers `severity_degraded`, `degradation_reason`, `physical_link_id` and
`physical_link_status`. This file pins the feed contract for that child:

* the default feed (include_children=False) ADMITS the degraded child;
* the default feed still EXCLUDES an ordinary PROPAGATED child;
* the degradation markers survive the public summary allowlist and the API
  response model.
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest

_SNMP_SERVICE_SENTINEL = object()


def _load_event_service_module():
    sys.modules.pop("services.event_service", None)
    stub = types.ModuleType("services.snmp_service")
    stub.run_diagnostic = lambda ci, metric: "diagnostic-ok"
    sys.modules["services.snmp_service"] = stub
    return importlib.import_module("services.event_service")


@pytest.fixture(autouse=True)
def restore_snmp_service_stub():
    previous = sys.modules.get("services.snmp_service", _SNMP_SERVICE_SENTINEL)
    yield
    if previous is _SNMP_SERVICE_SENTINEL:
        sys.modules.pop("services.snmp_service", None)
    else:
        sys.modules["services.snmp_service"] = previous


def _degraded_child_record():
    return {
        "e": {
            "id": "evt-degraded-1",
            "ci_id": "ci-affected",
            "metric_id": "metric-1",
            "status": "OPEN",
            "severity": "WARNING",
            "message": "Metric Collection Failed (Propagation degraded to WARNING)",
            "event_type": "COLLECTION_FAILURE",
            "correlation_type": "PROPAGATED",
            "propagated_from": "evt-root-1",
            "root_cause_ci_id": "ci-root",
            "severity_degraded": True,
            "degradation_reason": "PHYSICAL_LINK_UNKNOWN",
            "physical_link_id": "pl-1",
            "physical_link_status": "UNKNOWN",
        },
        "ci": {"id": "ci-affected", "name": "Switch-02"},
    }


def _ordinary_child_record():
    return {
        "e": {
            "id": "evt-ordinary-1",
            "ci_id": "ci-affected",
            "metric_id": "metric-1",
            "status": "OPEN",
            "severity": "CRITICAL",
            "message": "Metric Collection Failed",
            "event_type": "COLLECTION_FAILURE",
            "correlation_type": "PROPAGATED",
            "propagated_from": "evt-root-1",
            "root_cause_ci_id": "ci-root",
        },
        "ci": {"id": "ci-affected", "name": "Switch-02"},
    }


class TestDefaultFeedAdmitsTheDegradedChild:
    """S2: the explicitly degraded child is visible to the operator."""

    def test_default_feed_query_admits_the_degraded_propagated_child(self, mock_neo4j_session):
        """The default feed must not filter out a degraded PROPAGATED child."""
        event_service = _load_event_service_module()
        mock_neo4j_session.set_response("match (e:event)", [])

        event_service.get_events("CONSOLE")

        query = mock_neo4j_session.queries[0]["query"]
        assert "coalesce(e.severity_degraded, false) = true" in query

    def test_default_feed_still_excludes_ordinary_propagated_children(self, mock_neo4j_session):
        """The ROOT-only predicate must survive, so ordinary children stay hidden."""
        event_service = _load_event_service_module()
        mock_neo4j_session.set_response("match (e:event)", [])

        event_service.get_events("CONSOLE")

        query = mock_neo4j_session.queries[0]["query"]
        assert "coalesce(e.correlation_type, 'ROOT') = 'ROOT'" in query
        # The degraded clause is an ADDITIONAL branch, not a replacement.
        assert "$include_children" in query
        assert "ORDER BY e.created_at DESC" in query

    def test_degraded_child_reaches_the_feed_payload(self, mock_neo4j_session):
        """The degraded child is returned with its degradation markers intact."""
        event_service = _load_event_service_module()
        mock_neo4j_session.set_response("match (e:event)", [_degraded_child_record()])

        rows = event_service.get_events("CONSOLE")

        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == "evt-degraded-1"
        assert row["severity"] == "WARNING"
        assert row["correlation_type"] == "PROPAGATED"
        assert row["root_cause_ci_id"] == "ci-root"
        assert row["severity_degraded"] is True
        assert row["degradation_reason"] == "PHYSICAL_LINK_UNKNOWN"
        assert row["physical_link_id"] == "pl-1"
        assert row["physical_link_status"] == "UNKNOWN"

    def test_ordinary_propagated_child_carries_no_degradation_markers(self, mock_neo4j_session):
        """A non-degraded PROPAGATED row must not gain the marker fields."""
        event_service = _load_event_service_module()
        mock_neo4j_session.set_response("match (e:event)", [_ordinary_child_record()])

        rows = event_service.get_events("CONSOLE")

        assert len(rows) == 1
        assert "severity_degraded" not in rows[0]
        assert "degradation_reason" not in rows[0]
        assert "physical_link_id" not in rows[0]
        assert "physical_link_status" not in rows[0]


class TestDegradationMarkersArePublic:
    """S2: the degradation is explicit in the API payload, not implicit."""

    def test_public_summary_allowlist_admits_the_degradation_markers(self):
        """`_public_event_summary` must round-trip the four marker keys."""
        event_service = _load_event_service_module()

        summary = event_service._public_event_summary(
            {
                "id": "evt-degraded-1",
                "ci_id": "ci-affected",
                "status": "OPEN",
                "severity": "WARNING",
                "message": "degraded",
                "severity_degraded": True,
                "degradation_reason": "PHYSICAL_LINK_UNKNOWN",
                "physical_link_id": "pl-1",
                "physical_link_status": "UNKNOWN",
            }
        )

        assert summary["severity_degraded"] is True
        assert summary["degradation_reason"] == "PHYSICAL_LINK_UNKNOWN"
        assert summary["physical_link_id"] == "pl-1"
        assert summary["physical_link_status"] == "UNKNOWN"

    def test_feed_summary_model_accepts_the_degradation_markers(self):
        """The API response model must accept a degraded PROPAGATED row."""
        from models.core import EventFeedSummary

        payload = EventFeedSummary(
            id="evt-degraded-1",
            ci_id="ci-affected",
            status="OPEN",
            severity="WARNING",
            message="degraded",
            correlation_type="PROPAGATED",
            root_cause_ci_id="ci-root",
            severity_degraded=True,
            degradation_reason="PHYSICAL_LINK_UNKNOWN",
            physical_link_id="pl-1",
            physical_link_status="UNKNOWN",
        )

        assert payload.correlation_type == "PROPAGATED"
        assert payload.severity_degraded is True
        assert payload.physical_link_id == "pl-1"
