import pytest
from repositories import topology_repo
from services.tunnel_health import LinkIdentity, TunnelHealthResponse


def test_get_tunnel_health_link_reads_only_eligible_tunnel_media(mock_neo4j_driver):
    identity = LinkIdentity(
        source="hub-a", relationship="CONNECTS_TO", target="edge-b", medium="vpn"
    )
    mock_neo4j_driver.mock_session.set_default_response(
        [
            {
                "source_id": "hub-a",
                "source_public_ip": "198.51.100.10",
                "target_id": "edge-b",
                "target_public_ip": "203.0.113.20",
                "relationship": "CONNECTS_TO",
                "medium": "vpn",
                "tunnel_health_status": "UP",
                "tunnel_authority_state": "UP",
                "tunnel_authority_source": "SNMP",
                "tunnel_authority_observed_at": "2026-07-04T10:00:00Z",
                "tunnel_icmp_available": True,
                "tunnel_icmp_latency_ms": 11.5,
                "tunnel_icmp_error": None,
                "tunnel_icmp_reason": "sample",
                "tunnel_observed_at": "2026-07-04T10:00:01Z",
            }
        ]
    )

    health = topology_repo.get_tunnel_health_link(identity, allowed_locations=[], is_admin=True)

    query = mock_neo4j_driver.mock_session.queries[-1]["query"]
    params = mock_neo4j_driver.mock_session.queries[-1]["params"]
    assert "MATCH (a:CI {id: $source})-[r:CONNECTS_TO]->(b:CI {id: $target})" in query
    assert "r.medium = $medium" in query
    assert "vpn" in params["eligible_media"]
    assert "microwave" not in params["eligible_media"]
    assert health.status == "UP"
    assert health.icmp.latency_ms == 11.5


@pytest.mark.parametrize(
    ("persisted_reason", "persisted_available", "persisted_latency", "persisted_error"),
    [
        ("no_sample", False, None, None),
        ("failed", False, None, "timeout"),
    ],
)
def test_get_tunnel_health_link_preserves_persisted_icmp_reason_from_read_path(
    mock_neo4j_driver,
    persisted_reason,
    persisted_available,
    persisted_latency,
    persisted_error,
):
    identity = LinkIdentity(
        source="hub-a", relationship="CONNECTS_TO", target="edge-b", medium="vpn"
    )
    mock_neo4j_driver.mock_session.set_default_response(
        [
            {
                "source_id": "hub-a",
                "source_public_ip": "198.51.100.10",
                "target_id": "edge-b",
                "target_public_ip": "203.0.113.20",
                "relationship": "CONNECTS_TO",
                "medium": "vpn",
                "tunnel_health_status": "UNKNOWN",
                "tunnel_authority_state": None,
                "tunnel_authority_source": None,
                "tunnel_authority_observed_at": None,
                "tunnel_icmp_available": persisted_available,
                "tunnel_icmp_latency_ms": persisted_latency,
                "tunnel_icmp_error": persisted_error,
                "tunnel_icmp_reason": persisted_reason,
                "tunnel_observed_at": "2026-07-04T10:00:01Z",
            }
        ]
    )

    health = topology_repo.get_tunnel_health_link(identity, allowed_locations=[], is_admin=True)

    assert health.status == "UNKNOWN"
    assert health.icmp.available is persisted_available
    assert health.icmp.latency_ms == persisted_latency
    assert health.icmp.error == persisted_error
    assert health.icmp.reason == persisted_reason


def test_get_tunnel_health_link_returns_no_sample_for_eligible_row_without_health_properties(
    mock_neo4j_driver,
):
    identity = LinkIdentity(
        source="hub-a", relationship="CONNECTS_TO", target="edge-b", medium="vpn"
    )
    mock_neo4j_driver.mock_session.set_default_response(
        [
            {
                "source_id": "hub-a",
                "source_public_ip": "198.51.100.10",
                "target_id": "edge-b",
                "target_public_ip": "203.0.113.20",
                "relationship": "CONNECTS_TO",
                "medium": "vpn",
            }
        ]
    )

    health = topology_repo.get_tunnel_health_link(identity, allowed_locations=[], is_admin=True)

    assert health.status == "UNKNOWN"
    assert health.authority.state is None
    assert health.authority.reason == "no_sample"
    assert health.icmp.available is False
    assert health.icmp.latency_ms is None
    assert health.icmp.reason == "no_sample"
    assert health.observed_at is None


def test_get_tunnel_health_link_returns_none_for_non_admin_without_scope(mock_neo4j_driver):
    identity = LinkIdentity(
        source="hub-a", relationship="CONNECTS_TO", target="edge-b", medium="vpn"
    )

    result = topology_repo.get_tunnel_health_link(identity, allowed_locations=[], is_admin=False)

    assert result is None
    assert mock_neo4j_driver.mock_session.queries == []


def test_get_tunnel_health_link_applies_non_admin_location_scope(mock_neo4j_driver):
    identity = LinkIdentity(
        source="hub-a", relationship="CONNECTS_TO", target="edge-b", medium="vpn"
    )
    mock_neo4j_driver.mock_session.set_default_response([])

    result = topology_repo.get_tunnel_health_link(
        identity,
        allowed_locations=["HQ-Madrid"],
        is_admin=False,
    )

    query_call = mock_neo4j_driver.mock_session.queries[-1]
    assert result is None
    assert (
        "(a.location_name IN $allowed_locations OR b.location_name IN $allowed_locations)"
        in query_call["query"]
    )
    assert query_call["params"]["allowed_locations"] == ["HQ-Madrid"]


def test_get_tunnel_health_link_validates_relationship_before_cypher(mock_neo4j_driver):
    identity = LinkIdentity(
        source="hub-a", relationship="HAS_METRIC", target="edge-b", medium="vpn"
    )

    with pytest.raises(ValueError):
        topology_repo.get_tunnel_health_link(identity, allowed_locations=[], is_admin=True)

    assert mock_neo4j_driver.mock_session.queries == []


def test_save_latest_tunnel_health_writes_scalar_relationship_properties_only(mock_neo4j_driver):
    identity = LinkIdentity(
        source="hub-a", relationship="CONNECTS_TO", target="edge-b", medium="vpn"
    )
    health = TunnelHealthResponse.model_validate(
        {
            "link_id": "encoded",
            "source": "hub-a",
            "target": "edge-b",
            "relationship": "CONNECTS_TO",
            "medium": "vpn",
            "status": "UP",
            "authority": {
                "state": "UP",
                "source": "SNMP",
                "observed_at": "2026-07-04T10:00:00Z",
                "reason": "sample",
            },
            "icmp": {
                "available": False,
                "latency_ms": None,
                "error": "timeout",
                "reason": "failed",
            },
            "observed_at": "2026-07-04T10:00:01Z",
        }
    )

    topology_repo.save_latest_tunnel_health(identity, health)

    query = mock_neo4j_driver.mock_session.queries[-1]["query"]
    params = mock_neo4j_driver.mock_session.queries[-1]["params"]
    assert "SET r.tunnel_health_status = $status" in query
    assert "r.status" not in query
    assert "n.status" not in query
    assert "HAS_METRIC" not in query
    assert "Event" not in query
    assert params["status"] == "UP"
    assert params["authority_state"] == "UP"
    assert params["icmp_error"] == "timeout"
