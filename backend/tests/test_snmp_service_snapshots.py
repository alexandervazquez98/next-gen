import importlib
import sys
from unittest.mock import MagicMock, patch


def _load_snmp_service_module():
    sys.modules.pop("services.snmp_service", None)
    return importlib.import_module("services.snmp_service")


def test_resolve_event_snapshot_flattens_business_context(mock_neo4j_session):
    snmp_service = _load_snmp_service_module()
    mock_neo4j_session.set_response(
        "MATCH (ci:CI",
        [
            {
                "site": "Madrid HQ",
                "business_service_id": "svc-001",
                "business_service_name": "Corp-WAN",
                "business_service_tier": "T2",
                "owner_t1": "Mesa N1",
                "owner_t2": "NetOps",
                "owner_t3": "Arquitectura",
                "impacted_users": 350,
                "service_catalog_id": "sla-001",
                "service_category": "NETWORK",
                "service_tier": "Gold",
                "sla_minutes": 60,
            }
        ],
    )

    snapshot = snmp_service.resolve_event_snapshot(mock_neo4j_session, "ci-001")

    assert snapshot["business_service_name"] == "Corp-WAN"
    assert snapshot["business_service_tier"] == "T2"
    assert snapshot["service_catalog_id"] == "sla-001"
    assert snapshot["service_tier"] == "Gold"
    assert snapshot["sla_minutes"] == 60


def test_store_metric_result_writes_snapshot_fields_on_new_event(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()
    session = mock_neo4j_driver.mock_session
    session.set_response(
        "MATCH (existing:Event)",
        [],
    )
    session.set_response(
        "MATCH (ci:CI",
        [
            {
                "site": "Cordoba",
                "business_service_id": "svc-002",
                "business_service_name": "Payments",
                "business_service_tier": "T1",
                "owner_t1": "Service Desk",
                "owner_t2": "AppOps",
                "owner_t3": "SRE",
                "impacted_users": 1200,
                "service_catalog_id": "sla-002",
                "service_category": "APPLICATION",
                "service_tier": "Platinum",
                "sla_minutes": 30,
            }
        ],
    )

    snmp_service.store_metric_result(
        {"id": "ci-002", "ip": "10.0.0.2", "name": "Payments-API"},
        {
            "id": "latency",
            "name": "latency",
            "protocol": "HTTP",
            "criticality": 3,
            "critical": 500,
            "operator": ">=",
        },
        900,
        "OK",
        None,
        mock_neo4j_driver,
    )

    create_event_query = session.queries[-1]
    assert "CREATE (e:Event" in create_event_query["query"]
    assert create_event_query["params"]["business_service_name"] == "Payments"
    assert create_event_query["params"]["business_service_tier"] == "T1"
    assert create_event_query["params"]["service_catalog_id"] == "sla-002"
    assert create_event_query["params"]["service_tier"] == "Platinum"
    assert create_event_query["params"]["sla_minutes"] == 30


def test_store_metric_result_persists_numeric_values_to_timescale(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()

    fake_pg = MagicMock()

    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value") as mock_insert,
    ):
        snmp_service.store_metric_result(
            {"id": "ci-003", "ip": "10.0.0.3", "name": "Core-Router"},
            {
                "id": "cmb450i-cpu-util",
                "name": "cmb450i-cpu-util",
                "protocol": "SNMP",
                "criticality": 3,
                "critical": 95,
                "warning": 80,
                "operator": ">=",
            },
            "17",
            "OK",
            None,
            mock_neo4j_driver,
        )

    mock_insert.assert_called_once_with(fake_pg, "ci-003", "cmb450i-cpu-util", 17.0)
    fake_pg.close.assert_called_once()
