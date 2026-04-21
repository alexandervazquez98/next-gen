
import pytest
from unittest.mock import patch, MagicMock
from repositories import topology_repo

@pytest.fixture
def mock_db():
    with patch("services.metric_service.get_db") as mock:
        yield mock

def test_reconcile_node_metrics_triggers_link_with_defaults(mock_db):
    """
    Test that the reconciliation service correctly calls the repository
    to link metrics with their default thresholds from the definition.
    """
    session = mock_db.return_value.session.return_value.__enter__.return_value
    
    node = {"id": "ci-01", "name": "router-01", "brand": "cisco", "layer": "l3"}
    
    # Mocking definition with thresholds
    mock_metric = MagicMock()
    mock_metric.get.side_effect = lambda k, d=None: {
        "id": "CPU", 
        "applicable_to": '{"brands": ["cisco"]}',
        "warning": 80,
        "critical": 90
    }.get(k, d)
    
    # Mock node fetch and definitions fetch
    mock_node_db = MagicMock()
    mock_node_db.get.side_effect = lambda k, d=None: node.get(k, d)
    # Setup session.run to return node first, then metrics, then linked metrics
    # We use a wrap to see what's happening
    session.run.side_effect = [
        MagicMock(single=lambda: {"n": mock_node_db}), # 1. get_applicable_metrics -> fetch node
        [{"m": mock_metric}], # 2. get_applicable_metrics -> fetch all defs
        [] # 3. reconcile -> fetch current links (empty)
    ]

    from services.metric_service import reconcile_node_metrics

    # We need to patch link_metric_to_node in topology_repo
    with patch("repositories.topology_repo.link_metric_to_node") as mock_link:
        reconcile_node_metrics(node)

        # If this fails, let's see how many calls were made
        assert session.run.call_count == 3
        mock_link.assert_called_once_with("ci-01", "CPU", warning=80, critical=90)

