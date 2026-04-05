# backend/tests/test_helpers.py
"""
Lightweight test utilities for NEX-GEN backend testing.

These helpers reduce boilerplate for:
- Building mock Neo4j records with common patterns
- Creating test CI nodes and metrics
- Simulating event lifecycle scenarios
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Neo4j Mock Helpers
# ---------------------------------------------------------------------------


def make_neo4j_node_record(
    node_id: str,
    name: str,
    node_type: str = "router",
    status: str = "OK",
    brand: str = "",
    model: str = "",
    ip: str = "",
    layer: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build a dict that simulates a Neo4j node property map.

    Usage with MockNeo4jSession:
        session.set_response("match (n:ci)", [
            {"node": make_neo4j_node_record("ci-1", "Router-01", brand="Cisco")}
        ])
    """
    record = {
        "id": node_id,
        "name": name,
        "layer": node_type,
        "status": status,
        "ip": ip,
        "brand": brand,
        "model": model,
    }
    if layer:
        record["layer"] = layer
    if extra:
        record.update(extra)
    return record


def make_metric_record(
    metric_id: str,
    protocol: str = "SNMP",
    oid: str = "",
    warning: Optional[float] = None,
    critical: Optional[float] = None,
    applicable_to: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """
    Build a dict simulating a MetricDef node in Neo4j.
    """
    import json

    record = {
        "id": metric_id,
        "protocol": protocol,
        "oid": oid,
        "dataType": "INTEGER",
    }
    if warning is not None:
        record["warning"] = warning
    if critical is not None:
        record["critical"] = critical
    if applicable_to:
        record["applicable_to"] = json.dumps(applicable_to)
    return record


def make_event_record(
    event_id: str,
    ci_id: str,
    metric_id: str,
    severity: str = "CRITICAL",
    status: str = "OPEN",
    value: float = 0.0,
    created_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Build a dict simulating an Event node in Neo4j.
    """
    return {
        "e": {
            "id": event_id,
            "ci_id": ci_id,
            "metric_id": metric_id,
            "severity": severity,
            "status": status,
            "value": value,
            "created_at": created_at or datetime.utcnow(),
            "ack": False,
        },
        "ci_name": f"CI-{ci_id}",
        "metric_name": metric_id,
        "metric_protocol": "SNMP",
    }


# ---------------------------------------------------------------------------
# CI & Metric Factory Helpers
# ---------------------------------------------------------------------------


def make_ci_payload(
    ci_id: str,
    name: str,
    brand: str = "",
    model: str = "",
    layer: str = "router",
    ip: str = "",
    **kwargs,
) -> Dict[str, Any]:
    """
    Build a complete CI dict suitable for service-layer tests.
    """
    payload = {
        "id": ci_id,
        "name": name,
        "brand": brand,
        "model": model,
        "layer": layer,
        "ip": ip,
        "status": "OK",
        "owner": None,
        "locationName": None,
        "pollingInterval": 60,
        "snmp": None,
        "metrics": [],
        "metadata": {},
    }
    payload.update(kwargs)
    return payload


def make_metric_criteria(
    brands: Optional[List[str]] = None,
    models: Optional[List[str]] = None,
    layers: Optional[List[str]] = None,
    names: Optional[List[str]] = None,
    excluded_names: Optional[List[str]] = None,
) -> Dict[str, List[str]]:
    """
    Build the applicable_to criteria dict for a MetricDef.
    """
    return {
        "brands": brands or [],
        "models": models or [],
        "layers": layers or [],
        "names": names or [],
        "excluded_names": excluded_names or [],
    }


# ---------------------------------------------------------------------------
# Query Capture Helper
# ---------------------------------------------------------------------------


def find_query(mock_session, keyword: str) -> Optional[Dict[str, Any]]:
    """
    Find the first captured query containing the given keyword.

    Usage:
        q = find_query(mock_session, "has_metric")
        assert q is not None
        assert q["params"]["nid"] == "ci-001"
    """
    for entry in mock_session.queries:
        if keyword.lower() in entry["query"].lower():
            return entry
    return None


def find_all_queries(mock_session, keyword: str) -> List[Dict[str, Any]]:
    """
    Find all captured queries containing the given keyword.
    """
    return [
        entry
        for entry in mock_session.queries
        if keyword.lower() in entry["query"].lower()
    ]
