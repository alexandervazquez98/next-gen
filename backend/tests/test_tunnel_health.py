import base64
import json

import pytest
from services.tunnel_health import (
    LinkIdentity,
    TunnelAuthoritySample,
    TunnelIcmpSample,
    decode_link_id,
    encode_link_id,
    normalize_tunnel_health,
)


def test_authority_up_keeps_status_up_when_icmp_failed():
    health = normalize_tunnel_health(
        link_id="link-1",
        source="hub-a",
        target="edge-b",
        relationship="CONNECTS_TO",
        medium="vpn",
        authority=TunnelAuthoritySample(
            state="UP", source="SNMP", observed_at="2026-07-04T10:00:00Z"
        ),
        icmp=TunnelIcmpSample(available=False, latency_ms=900.0, error="timeout"),
        missing_public_ip=False,
        observed_at="2026-07-04T10:00:01Z",
    )

    assert health.status == "UP"
    assert health.authority.state == "UP"
    assert health.authority.reason == "sample"
    assert health.icmp.available is False
    assert health.icmp.reason == "failed"
    assert health.icmp.error == "timeout"


def test_authority_down_keeps_status_down_even_when_icmp_available():
    health = normalize_tunnel_health(
        link_id="link-2",
        source="hub-a",
        target="edge-b",
        relationship="CONNECTS_TO",
        medium="sd_wan",
        authority=TunnelAuthoritySample(
            state="DOWN", source="CLI", observed_at="2026-07-04T10:00:00Z"
        ),
        icmp=TunnelIcmpSample(available=True, latency_ms=12.5),
        observed_at="2026-07-04T10:00:01Z",
    )

    assert health.status == "DOWN"
    assert health.authority.state == "DOWN"
    assert health.icmp.available is True
    assert health.icmp.latency_ms == 12.5
    assert health.icmp.reason == "sample"


def test_missing_authority_returns_unknown_with_no_sample_context():
    health = normalize_tunnel_health(
        link_id="link-3",
        source="hub-a",
        target="edge-b",
        relationship="CONNECTS_TO",
        medium="satellite",
        authority=None,
        icmp=None,
        observed_at=None,
    )

    assert health.status == "UNKNOWN"
    assert health.authority.state is None
    assert health.authority.source is None
    assert health.authority.reason == "no_sample"
    assert health.icmp.available is False
    assert health.icmp.latency_ms is None
    assert health.icmp.reason == "no_sample"
    assert health.observed_at is None


def test_missing_public_ip_returns_deterministic_unavailable_icmp_context():
    health = normalize_tunnel_health(
        link_id="link-4",
        source="hub-a",
        target="edge-b",
        relationship="CONNECTS_TO",
        medium="vpn",
        authority=TunnelAuthoritySample(state="UP", source="SNMP"),
        icmp=TunnelIcmpSample(available=True, latency_ms=8.0),
        missing_public_ip=True,
        observed_at="2026-07-04T10:00:01Z",
    )

    assert health.status == "UP"
    assert health.icmp.available is False
    assert health.icmp.latency_ms is None
    assert health.icmp.error is None
    assert health.icmp.reason == "missing_public_ip"


def test_status_domain_never_contains_degraded_from_icmp_context():
    health = normalize_tunnel_health(
        link_id="link-5",
        source="hub-a",
        target="edge-b",
        relationship="CONNECTS_TO",
        medium="vpn",
        authority=None,
        icmp=TunnelIcmpSample(available=False, latency_ms=5000.0, error="high latency"),
        observed_at="2026-07-04T10:00:01Z",
    )

    assert health.status == "UNKNOWN"
    assert health.status in {"UP", "DOWN", "UNKNOWN"}


def test_link_id_encodes_canonical_unpadded_base64url_json():
    identity = LinkIdentity(
        source="hub-a",
        relationship="CONNECTS_TO",
        target="edge-b",
        medium="vpn",
    )

    link_id = encode_link_id(identity)
    decoded_json = base64.urlsafe_b64decode(link_id + "==").decode("utf-8")

    assert "=" not in link_id
    assert (
        decoded_json
        == '{"source":"hub-a","relationship":"CONNECTS_TO","target":"edge-b","medium":"vpn"}'
    )
    assert decode_link_id(link_id) == identity


def test_decode_link_id_rejects_padded_payload():
    identity = LinkIdentity(
        source="hub-a",
        relationship="CONNECTS_TO",
        target="edge-b",
        medium="vpn",
    )

    with pytest.raises(ValueError, match="unpadded"):
        decode_link_id(encode_link_id(identity) + "=")


def test_decode_link_id_rejects_non_canonical_field_order():
    payload = {
        "relationship": "CONNECTS_TO",
        "source": "hub-a",
        "target": "edge-b",
        "medium": "vpn",
    }
    link_id = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )

    with pytest.raises(ValueError, match="canonical fields"):
        decode_link_id(link_id)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "source": "hub-a",
            "relationship": "CONNECTS_TO",
            "target": "edge-b",
            "medium": "microwave",
        },
        {"source": "hub-a", "relationship": "CONNECTS_TO", "target": "edge-b"},
        {
            "source": "hub-a",
            "relationship": "CONNECTS_TO",
            "target": "edge-b",
            "medium": "vpn",
            "extra": "x",
        },
        {"source": "hub-a", "relationship": "HAS_METRIC", "target": "edge-b", "medium": "vpn"},
    ],
)
def test_decode_link_id_rejects_invalid_payloads(payload):
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    link_id = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    with pytest.raises(ValueError):
        decode_link_id(link_id)


def test_decode_link_id_rejects_oversized_payload_before_validation():
    oversized = (
        base64.urlsafe_b64encode(b'{"source":"' + (b"a" * 513) + b'"}').decode("ascii").rstrip("=")
    )

    with pytest.raises(ValueError, match="too large"):
        decode_link_id(oversized)
