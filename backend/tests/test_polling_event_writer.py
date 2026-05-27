from datetime import datetime, timezone

from tests.conftest import MockNeo4jDriver


def _event_row(value: float | None = 97.0, status="OK", metadata=None):
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


def test_event_writer_ignores_icmp_latency_and_jitter_as_availability_events():
    from polling.event_writer import build_event_rows

    rows = build_event_rows([
        {**_event_row(0.0), "protocol": "ICMP", "metric_id": "PING-CHECK", "metadata": {"name": "PING-CHECK", "criticality": 3}},
        {**_event_row(0.0), "protocol": "ICMP", "metric_id": "PING-router", "metadata": {"name": "PING-router", "criticality": 3}},
        {**_event_row(0.0), "protocol": "ICMP", "metric_id": "icmp_latency_ms", "metadata": {"name": "ICMP Latency", "criticality": 3}},
        {**_event_row(0.0), "protocol": "ICMP", "metric_id": "icmp_jitter_ms", "metadata": {"name": "ICMP Jitter", "criticality": 3}},
        {**_event_row(0.0), "protocol": "ICMP", "metric_id": "icmp_latency_ms", "metadata": {"name": "ICMP Latency", "criticality": 3, "metric_kind": "availability"}},
        {**_event_row(0.0), "protocol": "ICMP", "metric_id": "icmp_jitter_ms", "metadata": {"name": "ICMP Jitter", "criticality": 3, "metric_kind": "availability"}},
    ])

    assert rows[0]["event_type"] == "AVAILABILITY"
    assert rows[1]["event_type"] == "AVAILABILITY"
    for row in rows[2:]:
        assert row["event_type"] is None
        assert row["is_breach"] is False


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
    assert rows[1]["recover_non_collection_event"] is True
    assert rows[2]["is_breach"] is True
    assert rows[2]["event_type"] == "AVAILABILITY"
    assert rows[2]["source_protocol"] == "ICMP"
    assert rows[2]["severity"] == "CRITICAL"
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
    assert "e.id = coalesce(e.id, randomUUID())" in queries
    assert "RECOVERED" in queries
    assert "correlation_type" in queries
    assert "root_cause_ci_id" in queries
    assert "PROPAGATED" in queries


def test_event_writer_icmp_success_recovers_only_icmp_availability_events():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(driver, [{**_event_row(1.0), "protocol": "ICMP", "metric_id": "PING-CHECK"}])

    recovery_queries = [
        q["query"]
        for q in driver.mock_session.queries
        if "WITH row WHERE row.recover_non_collection_event" in q["query"]
    ]
    assert recovery_queries
    recovery_query = recovery_queries[0]
    assert "row.source_protocol = 'ICMP'" in recovery_query
    assert "e.event_type = 'AVAILABILITY'" in recovery_query
    assert "toUpper(e.source_protocol) = row.source_protocol" in recovery_query
    assert "pe.propagated_from = e.id" in recovery_query


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


def test_event_writer_derives_snmp_no_data_as_warning_collection_failure():
    from polling.event_writer import build_event_rows

    rows = build_event_rows([
        _event_row(
            None,
            status="NO_DATA",
            metadata={"name": "ifInOctets", "criticality": 1},
        )
    ])

    assert rows[0]["is_breach"] is True
    assert rows[0]["severity"] == "WARNING"
    assert rows[0]["event_type"] == "COLLECTION_FAILURE"
    assert rows[0]["failure_family"] == "SNMP_NO_RESPONSE"
    assert rows[0]["source_protocol"] == "SNMP"
    assert rows[0]["message"].startswith("Metric Collection Failed:")


def test_event_writer_does_not_label_generic_snmp_error_as_no_response():
    from polling.event_writer import build_event_rows

    rows = build_event_rows([
        {
            **_event_row(
                None,
                status="ERROR",
                metadata={"name": "ifInOctets", "criticality": 3},
            ),
            "error": {"code": "value_error", "message": "could not convert string to float"},
        }
    ])

    assert rows[0]["is_breach"] is True
    assert rows[0]["severity"] == "CRITICAL"
    assert rows[0]["event_type"] == "COLLECTION_FAILURE"
    assert rows[0]["failure_family"] is None
    assert "SNMP_NO_RESPONSE" not in rows[0]["message"]


def test_event_writer_labels_explicit_snmp_timeout_error_as_no_response_warning():
    from polling.event_writer import build_event_rows

    rows = build_event_rows([
        {
            **_event_row(None, status="ERROR", metadata={"name": "ifInOctets", "criticality": 3}),
            "error": {"code": "timeout", "message": "No SNMP response received before timeout"},
        }
    ])

    assert rows[0]["severity"] == "WARNING"
    assert rows[0]["event_type"] == "COLLECTION_FAILURE"
    assert rows[0]["failure_family"] == "SNMP_NO_RESPONSE"


def test_event_writer_marks_valid_rows_for_collection_failure_recovery_even_on_breach():
    from polling.event_writer import build_event_rows

    rows = build_event_rows([
        _event_row(42.0, metadata={"name": "cpu", "criticality": 3, "critical": 90}),
        _event_row(97.0, metadata={"name": "cpu", "criticality": 3, "critical": 90, "operator": ">="}),
        {
            **_event_row(97.0, metadata={"name": "cli-health", "criticality": 3, "critical": 90, "operator": ">="}),
            "protocol": "CLI",
            "metric_id": "cli-health",
        },
    ])

    assert rows[0]["is_breach"] is False
    assert rows[0]["recover_collection_failure"] is True
    assert rows[0]["event_type"] is None
    assert rows[1]["is_breach"] is True
    assert rows[1]["recover_collection_failure"] is True
    assert rows[1]["event_type"] == "THRESHOLD_BREACH"
    assert rows[2]["is_breach"] is True
    assert rows[2]["recover_collection_failure"] is True
    assert rows[2]["event_type"] == "THRESHOLD_BREACH"


def test_event_writer_uses_discriminator_aware_event_queries():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(driver, [_event_row(None, status="NO_DATA"), _event_row(42.0)])

    queries = "\n".join(q["query"] for q in driver.mock_session.queries)
    assert "event_type" in queries
    assert "failure_family" in queries
    assert "Metric Collection Failed:" in queries
    assert "MERGE (e:Event {ci_id: row.ci_id, metric_id: row.metric_id, status: 'OPEN'})" not in queries
    assert "COLLECTION_FAILURE" in queries
    assert "SNMP_NO_RESPONSE" in queries


def test_event_writer_collection_failure_matching_does_not_treat_null_family_as_wildcard():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(driver, [
        {
            **_event_row(
                None,
                status="ERROR",
                metadata={"name": "ifInOctets", "criticality": 3},
            ),
            "error": {"code": "value_error", "message": "could not convert string to float"},
        }
    ])

    collection_query = next(
        q for q in driver.mock_session.queries
        if "row.event_type = 'COLLECTION_FAILURE'" in q["query"]
    )["query"]
    assert "row.failure_family IS NULL OR existing.failure_family = row.failure_family" not in collection_query
    assert "row.failure_family IS NULL AND existing.failure_family IS NULL" in collection_query
    assert "row.failure_family IS NOT NULL" in collection_query


def test_event_writer_recovers_non_collection_events_on_normal_rows():
    from polling.event_writer import batch_update_events, build_event_rows

    rows = build_event_rows([_event_row(42.0, metadata={"name": "cpu", "criticality": 3, "critical": 90})])
    assert rows[0]["recover_collection_failure"] is True
    assert rows[0]["recover_non_collection_event"] is True

    driver = MockNeo4jDriver()
    batch_update_events(driver, [_event_row(42.0, metadata={"name": "cpu", "criticality": 3, "critical": 90})])

    queries = "\n".join(q["query"] for q in driver.mock_session.queries)
    assert "row.recover_non_collection_event" in queries
    assert "e.event_type <> 'COLLECTION_FAILURE'" in queries
    assert "NOT (e.event_type IS NULL AND e.message STARTS WITH 'Metric Collection Failed:')" in queries


def test_event_writer_recovers_non_snmp_collection_failures_on_valid_rows_even_when_breaching():
    from polling.event_writer import batch_update_events, build_event_rows

    envelope = {
        **_event_row(97.0, metadata={"name": "cli-health", "criticality": 3, "critical": 90, "operator": ">="}),
        "protocol": "CLI",
        "metric_id": "cli-health",
    }
    rows = build_event_rows([envelope])
    assert rows[0]["is_breach"] is True
    assert rows[0]["recover_collection_failure"] is True

    driver = MockNeo4jDriver()
    batch_update_events(driver, [envelope])

    recovery_query = next(q for q in driver.mock_session.queries if "row.recover_collection_failure" in q["query"])
    assert "e.event_type = 'COLLECTION_FAILURE'" in recovery_query["query"]
    assert "e.event_type IS NULL AND e.message STARTS WITH 'Metric Collection Failed:'" in recovery_query["query"]
    assert "toUpper(e.source_protocol) = row.source_protocol" in recovery_query["query"]


def test_event_writer_deduplicates_collection_failure_rows_before_event_write():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(driver, [
        _event_row(None, status="NO_DATA"),
        {**_event_row(None, status="NO_DATA"), "idempotency_key": "idem-2"},
    ])

    collection_query = next(
        q for q in driver.mock_session.queries
        if "row.event_type = 'COLLECTION_FAILURE'" in q["query"]
    )
    assert len(collection_query["params"]["rows"]) == 1


def test_event_writer_uses_collection_recovery_message_for_threshold_breach_recovery():
    from polling.event_writer import batch_update_events, build_event_rows

    rows = build_event_rows([_event_row(97.0, metadata={"name": "cpu", "criticality": 3, "critical": 90})])
    assert rows[0]["is_breach"] is True
    assert rows[0]["message"].startswith("Critical Threshold Breached")
    assert rows[0]["collection_recovery_message"].startswith("Metric collection recovered")

    driver = MockNeo4jDriver()
    batch_update_events(driver, [_event_row(97.0, metadata={"name": "cpu", "criticality": 3, "critical": 90})])

    recovery_query = next(q for q in driver.mock_session.queries if "row.recover_collection_failure" in q["query"])
    assert "row.collection_recovery_message" in recovery_query["query"]
