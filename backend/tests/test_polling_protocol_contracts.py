import pytest


def test_build_snmp_and_icmp_payloads_from_metric_records():
    from polling.protocol_contracts import build_protocol_payload

    snmp = build_protocol_payload({
        "protocol": "SNMP",
        "ip": "10.0.0.10",
        "oid": "1.3.6.1.2.1.1.3.0",
        "community": "private",
        "port": 1161,
    })
    icmp = build_protocol_payload({"protocol": "ICMP", "ip": "10.0.0.11"})

    assert snmp == {
        "kind": "snmp_get",
        "target": "10.0.0.10",
        "oid": "1.3.6.1.2.1.1.3.0",
        "community": "private",
        "port": 1161,
        "timeout_seconds": 2.0,
        "retries": 1,
    }
    assert icmp["kind"] == "icmp_ping"
    assert icmp["target"] == "10.0.0.11"


def test_cli_and_rest_payload_contracts_validate_required_fields():
    from polling.protocol_contracts import build_protocol_payload

    cli = build_protocol_payload({
        "protocol": "CLI",
        "ip": "10.0.0.20",
        "cli_command": "show cpu",
        "cli_target": "shell",
        "cli_credential_ref": "cred-router",
        "cli_value_extractor": "regex:(\\d+)",
        "cli_protocol": "SSH",
        "cli_timeout": 20,
    })
    rest = build_protocol_payload({
        "protocol": "REST",
        "endpoint": "https://device/api/health",
        "method": "get",
        "credential_ref": "rest-token",
        "expected_status": 200,
    })

    assert cli["kind"] == "cli_command"
    assert cli["transport"] == "SSH"
    assert cli["timeout_seconds"] == 20
    assert rest["kind"] == "rest_request"
    assert rest["method"] == "GET"
    assert rest["endpoint"] == "https://device/api/health"

    with pytest.raises(ValueError, match="cli_command"):
        build_protocol_payload({"protocol": "CLI", "ip": "10.0.0.20"})
    with pytest.raises(ValueError, match="endpoint"):
        build_protocol_payload({"protocol": "REST", "method": "GET"})


def test_mqtt_stub_is_extension_point_only_and_production_mqtt_is_rejected():
    from polling.protocol_contracts import build_protocol_payload

    stub = build_protocol_payload({"protocol": "MQTT_STUB", "source": "future-topic"})

    assert stub == {"kind": "mqtt_stub", "source": "future-topic"}
    with pytest.raises(ValueError, match="MQTT_STUB"):
        build_protocol_payload({"protocol": "MQTT", "source": "real-topic"})
