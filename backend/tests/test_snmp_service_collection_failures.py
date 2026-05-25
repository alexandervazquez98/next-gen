import importlib
import sys
from unittest.mock import MagicMock, patch


def _load_snmp_service_module():
    sys.modules.pop("services.snmp_service", None)
    return importlib.import_module("services.snmp_service")


def test_snmp_collection_failure_on_critical_metric_is_warning_with_discriminators(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()
    session = mock_neo4j_driver.mock_session
    session.set_response("MATCH (existing:Event)", [])
    session.set_response("MATCH (ci:CI", [])

    snmp_service.store_metric_result(
        {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
        {"id": "ifInOctets", "name": "ifInOctets", "protocol": "SNMP", "criticality": 3},
        None,
        "TIMEOUT",
        "No SNMP response received before timeout",
        mock_neo4j_driver,
    )

    create_event = next(q for q in session.queries if "CREATE (e:Event" in q["query"])
    assert create_event["params"]["sev"] == "WARNING"
    assert create_event["params"]["event_type"] == "COLLECTION_FAILURE"
    assert create_event["params"]["failure_family"] == "SNMP_NO_RESPONSE"
    assert create_event["params"]["source_protocol"] == "SNMP"


def test_snmp_generic_error_is_not_labeled_no_response(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()
    session = mock_neo4j_driver.mock_session
    session.set_response("MATCH (existing:Event)", [])
    session.set_response("MATCH (ci:CI", [])

    snmp_service.store_metric_result(
        {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
        {"id": "ifInOctets", "name": "ifInOctets", "protocol": "SNMP", "criticality": 3},
        None,
        "ERROR",
        "could not convert string to float",
        mock_neo4j_driver,
    )

    create_event = next(q for q in session.queries if "CREATE (e:Event" in q["query"])
    assert create_event["params"]["sev"] == "CRITICAL"
    assert create_event["params"]["event_type"] == "COLLECTION_FAILURE"
    assert create_event["params"]["failure_family"] is None


def test_snmp_valid_value_recovers_only_collection_failure(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()
    fake_pg = MagicMock()

    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value"),
    ):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {"id": "cpu", "name": "cpu", "protocol": "SNMP", "criticality": 3},
            "42",
            "OK",
            None,
            mock_neo4j_driver,
        )

    queries = "\n".join(q["query"] for q in mock_neo4j_driver.mock_session.queries)
    assert "COLLECTION_FAILURE" in queries
    assert "Metric Collection Failed:" in queries
    assert "THRESHOLD_BREACH" not in queries


def test_snmp_threshold_breach_uses_threshold_event_type_not_collection_failure(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()
    session = mock_neo4j_driver.mock_session
    session.set_response("MATCH (existing:Event)", [])
    session.set_response("MATCH (ci:CI", [])
    fake_pg = MagicMock()

    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value"),
    ):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {"id": "cpu", "name": "cpu", "protocol": "SNMP", "criticality": 3, "critical": 90, "operator": ">="},
            "97",
            "OK",
            None,
            mock_neo4j_driver,
        )

    create_event = next(q for q in session.queries if "CREATE (e:Event" in q["query"])
    assert create_event["params"]["sev"] == "CRITICAL"
    assert create_event["params"]["event_type"] == "THRESHOLD_BREACH"
    assert create_event["params"]["failure_family"] is None


def test_snmp_threshold_breach_still_recovers_existing_collection_failure(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()
    session = mock_neo4j_driver.mock_session
    session.set_response("MATCH (existing:Event)", [])
    session.set_response("MATCH (ci:CI", [])
    fake_pg = MagicMock()

    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value"),
    ):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {"id": "cpu", "name": "cpu", "protocol": "snmp", "criticality": 3, "critical": 90, "operator": ">="},
            "97",
            "OK",
            None,
            mock_neo4j_driver,
        )

    recovery_queries = [
        q for q in session.queries
        if "SET e.status = 'RECOVERED'" in q["query"] and "COLLECTION_FAILURE" in q["query"]
    ]
    assert recovery_queries, "valid SNMP values must recover collection failures before threshold handling"
    assert "coalesce(m.can_propagate, true) = true" in recovery_queries[0]["query"]
    create_event = next(q for q in session.queries if "CREATE (e:Event" in q["query"])
    assert create_event["params"]["event_type"] == "THRESHOLD_BREACH"


def test_repeated_collection_failure_updates_exact_matched_event(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()
    session = mock_neo4j_driver.mock_session
    session.set_response("MATCH (existing:Event)", [{"existing_status": "OPEN", "existing_element_id": "element-collection"}])

    snmp_service.store_metric_result(
        {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
        {"id": "ifInOctets", "name": "ifInOctets", "protocol": "SNMP", "criticality": 3},
        None,
        "TIMEOUT",
        "No SNMP response received before timeout",
        mock_neo4j_driver,
    )

    lookup_event = next(q for q in session.queries if "MATCH (existing:Event)" in q["query"])
    assert "$failure_family IS NULL OR existing.failure_family = $failure_family" not in lookup_event["query"]
    assert "$failure_family IS NULL AND existing.failure_family IS NULL" in lookup_event["query"]
    assert "$failure_family IS NOT NULL" in lookup_event["query"]
    update_event = next(q for q in session.queries if "elementId(existing) = $existing_element_id" in q["query"])
    assert update_event["params"]["existing_element_id"] == "element-collection"
    assert "existing.status = $old_status" not in update_event["query"]


def test_non_breach_value_recovers_non_collection_events(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()
    fake_pg = MagicMock()

    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value"),
    ):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {"id": "cpu", "name": "cpu", "protocol": "SNMP", "criticality": 3, "critical": 90},
            "42",
            "OK",
            None,
            mock_neo4j_driver,
        )

    queries = "\n".join(q["query"] for q in mock_neo4j_driver.mock_session.queries)
    assert "e.event_type <> 'COLLECTION_FAILURE'" in queries
    assert "NOT (e.event_type IS NULL AND e.message STARTS WITH 'Metric Collection Failed:')" in queries


def test_valid_non_snmp_threshold_breach_recovers_collection_failures(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()
    session = mock_neo4j_driver.mock_session
    session.set_response("MATCH (existing:Event)", [])
    session.set_response("MATCH (ci:CI", [])
    fake_pg = MagicMock()

    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value"),
    ):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {"id": "cli-health", "name": "cli-health", "protocol": "CLI", "criticality": 3, "critical": 90},
            "97",
            "OK",
            None,
            mock_neo4j_driver,
        )

    recovery_queries = [
        q for q in session.queries
        if "SET e.status = 'RECOVERED'" in q["query"] and "Metric Collection Failed:" in q["query"]
    ]
    assert recovery_queries, "valid non-SNMP samples must recover collection failures even when breaching"
    assert "toUpper(e.source_protocol) = $source_protocol" in recovery_queries[0]["query"]
    assert "e.event_type IS NULL AND e.message STARTS WITH 'Metric Collection Failed:'" in recovery_queries[0]["query"]


def test_poll_metric_non_timeout_error_indication_returns_error_not_timeout():
    snmp_service = _load_snmp_service_module()

    with patch("services.snmp_service.getCmd", return_value=iter([("authorization failure", None, None, [])])):
        value, status, error = snmp_service.poll_metric(
            {"id": "ci-1", "ip": "10.0.0.1"},
            {"id": "ifInOctets", "protocol": "SNMP", "oid": "1.2.3"},
            {"readCommunity": "public", "port": 161},
        )

    assert value is None
    assert status == "ERROR"
    assert error == "authorization failure"


def test_poll_metric_timeout_error_indication_returns_timeout():
    snmp_service = _load_snmp_service_module()

    with patch("services.snmp_service.getCmd", return_value=iter([("No SNMP response received before timeout", None, None, [])])):
        value, status, error = snmp_service.poll_metric(
            {"id": "ci-1", "ip": "10.0.0.1"},
            {"id": "ifInOctets", "protocol": "SNMP", "oid": "1.2.3"},
            {"readCommunity": "public", "port": 161},
        )

    assert value is None
    assert status == "TIMEOUT"
    assert error == "No SNMP response received before timeout"
