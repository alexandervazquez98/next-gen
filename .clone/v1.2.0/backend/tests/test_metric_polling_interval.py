import pytest
from unittest.mock import MagicMock, patch
from models.core import MetricDef
from services import metric_service

def test_metric_def_includes_polling_interval():
    # GIVEN a metric definition with custom interval
    metric = MetricDef(
        id="cpu_load",
        protocol="SNMP",
        polling_interval=30
    )
    
    # THEN
    assert metric.polling_interval == 30

def test_metric_def_defaults_to_60():
    # GIVEN a metric definition without interval
    metric = MetricDef(
        id="mem_usage",
        protocol="SNMP"
    )
    
    # THEN
    assert metric.polling_interval == 60

@patch("services.metric_service.get_db")
def test_create_metric_persists_interval(mock_get_db):
    # GIVEN
    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_get_db.return_value = mock_driver
    
    metric = MetricDef(
        id="temp_sensor",
        protocol="SNMP",
        polling_interval=15
    )
    
    # WHEN
    metric_service.create_metric(metric)
    
    # THEN
    args, kwargs = mock_session.run.call_args
    assert "polling_interval" in kwargs
    assert kwargs["polling_interval"] == 15
    assert "m.polling_interval = $polling_interval" in args[0]

@patch("services.metric_service.get_db")
def test_get_metrics_includes_interval(mock_get_db):
    # GIVEN
    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_get_db.return_value = mock_driver
    
    # Mock Neo4j Record
    mock_record = MagicMock()
    mock_node = {
        "id": "ping",
        "protocol": "ICMP",
        "polling_interval": 10
    }
    mock_record.__getitem__.return_value = mock_node
    mock_session.run.return_value = [mock_record]
    
    # WHEN
    metrics = metric_service.get_metrics()
    
    # THEN
    assert len(metrics) == 1
    assert metrics[0]["polling_interval"] == 10
