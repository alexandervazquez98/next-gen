
import pytest
import json
from unittest.mock import patch, MagicMock
from services import metric_service

@pytest.fixture
def mock_db():
    with patch("services.metric_service.get_db") as mock:
        yield mock

def test_evaluate_rule_match_cisco_and_l3(mock_db):
    """
    Scenario: User wants to link a metric only to Cisco L3 devices.
    """
    node = {"brand": "Cisco", "layer": "L3", "id": "router-01"}
    # Our rule engine should support nested criteria or specific fields
    criteria = {
        "brands": ["Cisco"],
        "layers": ["L3"]
    }
    
    # We will test the internal evaluator if we extract it, 
    # or the get_applicable_metrics logic.
    # For TDD, let's assume we want a more flexible check.
    
    # Mocking DB to return a single metric with these criteria
    session = mock_db.return_value.session.return_value.__enter__.return_value
    mock_metric = MagicMock()
    
    def metric_get(k, d=None):
        vals = {
            "applicable_to": json.dumps(criteria),
            "id": "METRIC-01",
            "description": "Test Metric",
            "unit": "%"
        }
        return vals.get(k, d)

    mock_metric.get.side_effect = metric_get
    mock_metric.__getitem__.side_effect = lambda k: "METRIC-01" if k == "id" else None
    
    mock_node = MagicMock()
    mock_node.get.side_effect = lambda k, d=None: node.get(k, d)
    
    # Setup session.run to return node first, then metrics
    session.run.side_effect = [
        MagicMock(single=lambda: {"n": mock_node}), # Node fetch
        [{"m": mock_metric}] # Metrics fetch
    ]
    
    applicable = metric_service.get_applicable_metrics("router-01")
    
    assert len(applicable) == 1
    assert applicable[0]["id"] == "METRIC-01"

def test_evaluate_rule_no_match_wrong_brand(mock_db):
    """
    Scenario: Cisco rule should NOT match a Juniper device.
    """
    node = {"brand": "Juniper", "layer": "L3", "id": "router-02"}
    criteria = {"brands": ["Cisco"]}
    
    session = mock_db.return_value.session.return_value.__enter__.return_value
    mock_metric = MagicMock()
    mock_metric.get.side_effect = lambda k, d=None: json.dumps(criteria) if k == "applicable_to" else d
    
    session.run.return_value = [{"m": mock_metric}]
    
    # We need to make sure get_applicable_metrics fetches the node from DB
    # Based on exploration, it does: session.run("MATCH (n:CI {id: $id}) RETURN n", id=node_id)
    mock_node = MagicMock()
    mock_node.get.side_effect = lambda k, d=None: node.get(k, d)
    
    # Setup session.run to return node first, then metrics
    session.run.side_effect = [
        MagicMock(single=lambda: {"n": mock_node}), # Node fetch
        [{"m": mock_metric}] # Metrics fetch
    ]
    
    applicable = metric_service.get_applicable_metrics("router-02")
    assert len(applicable) == 0
