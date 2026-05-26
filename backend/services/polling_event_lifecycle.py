"""Shared polling event discriminator constants and helpers."""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

EVENT_TYPE_COLLECTION_FAILURE = "COLLECTION_FAILURE"
EVENT_TYPE_THRESHOLD_BREACH = "THRESHOLD_BREACH"
EVENT_TYPE_AVAILABILITY = "AVAILABILITY"
FAILURE_FAMILY_SNMP_NO_RESPONSE = "SNMP_NO_RESPONSE"
SOURCE_PROTOCOL_SNMP = "SNMP"
SOURCE_PROTOCOL_ICMP = "ICMP"
COLLECTION_FAILURE_PREFIX = "Metric Collection Failed:"

_NO_RESPONSE_STATUSES = {"NO_DATA", "TIMEOUT"}
_NO_RESPONSE_ERROR_CODES = {"NO_DATA", "NO_RESPONSE", "TIMEOUT", "TIMED_OUT", "REQUEST_TIMEOUT"}
_NO_RESPONSE_MESSAGE_MARKERS = (
    "no snmp response",
    "no response",
    "timed out",
    "timeout",
    "returned no data",
    "no data",
)


def enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def normalized_protocol(value: Any) -> str:
    return str(enum_value(value) or "").upper()


def is_snmp_no_response_failure(protocol: Any, status: Any, error: Mapping[str, Any] | None = None) -> bool:
    if normalized_protocol(protocol) != SOURCE_PROTOCOL_SNMP:
        return False
    normalized_status = str(enum_value(status) or "").upper()
    if normalized_status in _NO_RESPONSE_STATUSES:
        return True
    if normalized_status != "ERROR":
        return False
    error = error or {}
    code = str(enum_value(error.get("code")) or "").upper()
    if code in _NO_RESPONSE_ERROR_CODES:
        return True
    message = str(error.get("message") or "").lower()
    return any(marker in message for marker in _NO_RESPONSE_MESSAGE_MARKERS)


def collection_failure_message(error: Mapping[str, Any] | None = None, status: Any = None) -> str:
    reason = None
    if error:
        reason = error.get("message")
    reason = reason or str(enum_value(status) or "No SNMP response received before timeout")
    return f"{COLLECTION_FAILURE_PREFIX} {reason}"
