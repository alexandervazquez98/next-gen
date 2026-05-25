from datetime import datetime, timezone

from tests.conftest import MockNeo4jDriver


def _event_row(value=97.0, status="OK", metadata=None):
    return {
        "idempotency_key": "idem-1",
        "ci_id": "ci-1",
        "metric_id": "cpu",
        "protocol": "SNMP",
        "source": "10.0.0.1:161/1.2.3",
        "observed_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "status": status,
        "value": {"numeric": value, "raw": value},
        "error": {"message": None},
        "metadata": metadata or {"critical": 90, "warning": 80, "criticality": 3, "operator": ">="},
    }


def test_event_writer_derives_threshold_breach_and_availability_recovery_rows():
    from polling.event_writer import build_event_rows

    rows = build_event_rows([
        _event_row(97.0),
        {**_event_row(1.0), "protocol": "ICMP", "metric_id": "PING-CHECK"},
        {**_event_row(0.0), "protocol": "ICMP", "metric_id": "PING-CHECK"},
    ])

    assert rows[0]["is_breach"] is True
    assert rows[0]["severity"] == "CRITICAL"
    assert rows[0]["correlation_type"] == "ROOT"
    assert rows[0]["root_cause_ci_id"] == "ci-1"
    assert "Critical Threshold Breached" in rows[0]["message"]
    assert rows[1]["is_breach"] is False
    assert rows[2]["is_breach"] is True
    assert "Service/Host Down" in rows[2]["message"]


def test_event_writer_uses_unwind_for_latest_breach_and_recovery_updates():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(driver, [_event_row(95.0), {**_event_row(1.0), "idempotency_key": "idem-2"}])

    queries = "\n".join(q["query"] for q in driver.mock_session.queries)
    assert queries.count("UNWIND $rows AS row") >= 3
    assert "MERGE (n)-[r:HAS_METRIC]->(m)" in queries
    assert "CREATE (res:MetricResult" in queries
    assert "status: 'OPEN'" in queries
    assert "RECOVERED" in queries
    assert "correlation_type" in queries
    assert "root_cause_ci_id" in queries
    assert "PROPAGATED" in queries


def test_event_writer_preserves_propagated_correlation_metadata():
    from polling.event_writer import build_event_rows

    rows = build_event_rows([
        _event_row(
            95.0,
            metadata={
                "critical": 90,
                "criticality": 3,
                "operator": ">=",
                "correlation_type": "PROPAGATED",
                "propagated_from": "event-root",
                "root_cause_ci_id": "ci-root",
                "business_service_id": "bs-1",
            },
        )
    ])

    assert rows[0]["correlation_type"] == "PROPAGATED"
    assert rows[0]["propagated_from"] == "event-root"
    assert rows[0]["root_cause_ci_id"] == "ci-root"
    assert rows[0]["business_service_id"] == "bs-1"
