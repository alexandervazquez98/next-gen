"""Protocol payload contracts for future leased polling workers.

These builders validate the task payload shape only; they do not execute any
network operation and do not write databases.
"""

from __future__ import annotations

from typing import Any, Mapping

from polling.contracts import PollingProtocol


def _required(record: Mapping[str, Any], key: str) -> Any:
    value = record.get(key)
    if value is None or value == "":
        raise ValueError(f"Missing required protocol payload field: {key}")
    return value


def _protocol(record: Mapping[str, Any]) -> PollingProtocol:
    value = _required(record, "protocol")
    if isinstance(value, PollingProtocol):
        protocol = value
    else:
        raw = str(value).strip().upper()
        if raw == "MQTT":
            raise ValueError("Production MQTT is out of scope; use MQTT_STUB for roadmap sizing")
        try:
            protocol = PollingProtocol(raw)
        except ValueError as exc:
            raise ValueError(f"Unsupported polling protocol: {raw}") from exc
    if protocol.value == "MQTT":
        raise ValueError("Production MQTT is out of scope; use MQTT_STUB for roadmap sizing")
    return protocol


def build_protocol_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    """Build a normalized protocol payload from a CI/metric definition record."""
    protocol = _protocol(record)
    if protocol == PollingProtocol.ICMP:
        return {
            "kind": "icmp_ping",
            "target": _required(record, "ip"),
            "timeout_ms": int(record.get("timeout_ms") or record.get("icmp_timeout_ms") or 3000),
            "retries": int(record.get("retries") or record.get("icmp_retries") or 2),
        }
    if protocol == PollingProtocol.SNMP:
        return {
            "kind": "snmp_get",
            "target": _required(record, "ip"),
            "oid": _required(record, "oid"),
            "community": record.get("community") or record.get("snmp_community") or "public",
            "port": int(record.get("port") or record.get("snmp_port") or 161),
            "timeout_seconds": float(record.get("timeout_seconds") or record.get("snmp_timeout_seconds") or 2.0),
            "retries": int(record.get("retries") or record.get("snmp_retries") or 1),
        }
    if protocol == PollingProtocol.CLI:
        transport = str(record.get("cli_protocol") or "SSH").upper()
        if transport not in {"SSH", "TELNET"}:
            raise ValueError("cli_protocol must be SSH or Telnet")
        return {
            "kind": "cli_command",
            "target": record.get("cli_target") or _required(record, "ip"),
            "command": _required(record, "cli_command"),
            "credential_ref": _required(record, "cli_credential_ref"),
            "value_extractor": record.get("cli_value_extractor") or "regex:(.*)",
            "transport": "Telnet" if transport == "TELNET" else "SSH",
            "timeout_seconds": int(record.get("cli_timeout") or 30),
            "escalation_script": record.get("cli_escalation_script"),
        }
    if protocol == PollingProtocol.REST:
        return {
            "kind": "rest_request",
            "method": str(record.get("method") or "GET").upper(),
            "endpoint": _required(record, "endpoint"),
            "credential_ref": record.get("credential_ref") or record.get("rest_credential_ref"),
            "expected_status": int(record.get("expected_status") or 200),
            "timeout_seconds": int(record.get("timeout_seconds") or record.get("rest_timeout") or 30),
            "parser": record.get("parser") or record.get("rest_parser"),
            "rate_limit_bucket": record.get("rate_limit_bucket"),
        }
    if protocol == PollingProtocol.MQTT_STUB:
        return {"kind": "mqtt_stub", "source": record.get("source") or record.get("topic") or "mqtt_stub"}
    raise ValueError(f"Unsupported polling protocol: {protocol}")
