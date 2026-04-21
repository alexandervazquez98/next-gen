
import pytest
from unittest.mock import patch, MagicMock
from services import snmp_service

@pytest.fixture
def mock_db():
    with patch("services.snmp_service.get_db") as mock:
        yield mock

def test_polling_uses_individual_threshold_from_relationship(mock_db):
    """
    Scenario: Global threshold for CPU is 90. 
    But for this specific CI, the relationship has a 80 threshold.
    Value polled is 85.
    Result should be CRITICAL based on individual override.
    """
    session = mock_db.return_value.session.return_value.__enter__.return_value
    
    # Mock relationship properties (the individual overrides)
    mock_rel = MagicMock()
    mock_rel.get.side_effect = lambda k, d=None: {
        "warning_threshold": 70.0,
        "critical_threshold": 80.0
    }.get(k, d)
    
    # Mock global definition
    mock_def = MagicMock()
    mock_def.get.side_effect = lambda k, d=None: {
        "warning": 80.0,
        "critical": 90.0,
        "operator": ">="
    }.get(k, d)
    
    # Mock query result for get_node_metric_config (hypothetical function name)
    # We need to see how the service actually fetches config
    session.run.return_value = [
        MagicMock(data=lambda: {
            "m": {"warning": 80.0, "critical": 90.0, "operator": ">="},
            "r": {"warning_threshold": 70.0, "critical_threshold": 80.0}
        })
    ]
    
    # We'll test the internal status resolution logic
    # Assume we extract or update a 'resolve_status' function
    status = snmp_service.evaluate_status(
        value=85.0,
        warn_global=80.0,
        crit_global=90.0,
        warn_custom=70.0,
        crit_custom=80.0,
        operator=">="
    )
    
    assert status == "CRITICAL"
