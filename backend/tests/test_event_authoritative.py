"""Unit tests for `_is_authoritative_event` helper in services.event_service.

REQ-CORR-4 — Authoritative event helper.

`backend/services/event_service.py` SHALL expose `_is_authoritative_event(event)`
returning `False` only when `correlation_type == 'PROPAGATED'`. The helper MUST
be backward compatible: events with missing/None/unknown `correlation_type`
are treated as authoritative (True).

Strict TDD: these tests must FAIL before T2 lands the helper.
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest


def _load_event_service_module():
    """Reload event_service with a stub for the snmp_service dependency.

    The helper we test is pure and needs no Neo4j, but event_service imports
    `from services.snmp_service import run_diagnostic` at module load time, so
    we have to provide a stub.
    """
    sys.modules.pop("services.event_service", None)
    stub = types.ModuleType("services.snmp_service")
    setattr(stub, "run_diagnostic", lambda ci, metric: "diagnostic-ok")
    sys.modules["services.snmp_service"] = stub
    return importlib.import_module("services.event_service")


class TestIsAuthoritativeEventHelperExists:
    """The helper must be exported from services.event_service."""

    def test_helper_is_importable(self):
        event_service = _load_event_service_module()
        assert hasattr(event_service, "_is_authoritative_event"), (
            "_is_authoritative_event must be defined in services.event_service"
        )

    def test_helper_is_callable(self):
        event_service = _load_event_service_module()
        helper = event_service._is_authoritative_event
        assert callable(helper), "_is_authoritative_event must be callable"


class TestIsAuthoritativeEventSemantics:
    """REQ-CORR-4: returns False only for PROPAGATED; True otherwise."""

    def test_root_event_is_authoritative(self):
        event_service = _load_event_service_module()
        assert event_service._is_authoritative_event({"correlation_type": "ROOT"}) is True

    def test_propagated_event_is_not_authoritative(self):
        event_service = _load_event_service_module()
        assert event_service._is_authoritative_event({"correlation_type": "PROPAGATED"}) is False

    def test_missing_correlation_type_is_backward_compatible(self):
        event_service = _load_event_service_module()
        # Legacy events pre-fix have no correlation_type — must still be authoritative.
        assert event_service._is_authoritative_event({}) is True

    def test_none_correlation_type_is_backward_compatible(self):
        event_service = _load_event_service_module()
        assert event_service._is_authoritative_event({"correlation_type": None}) is True

    def test_unknown_legacy_value_is_authoritative(self):
        event_service = _load_event_service_module()
        # Unknown future value: keep behavior conservative — treat as authoritative.
        assert event_service._is_authoritative_event({"correlation_type": "FOO"}) is True

    def test_mixed_case_propagated_is_not_authoritative(self):
        event_service = _load_event_service_module()
        # The helper normalises case; any case-insensitive 'propagated' is non-authoritative.
        assert event_service._is_authoritative_event({"correlation_type": "propagated"}) is False
        assert event_service._is_authoritative_event({"correlation_type": "Propagated"}) is False
        assert event_service._is_authoritative_event({"correlation_type": "PROPAGATED"}) is False

    def test_empty_string_correlation_type_is_backward_compatible(self):
        event_service = _load_event_service_module()
        # Empty string is treated like missing — must remain authoritative.
        assert event_service._is_authoritative_event({"correlation_type": ""}) is True

    def test_helper_ignores_other_event_fields(self):
        """The helper only consults correlation_type; other fields must not affect result."""
        event_service = _load_event_service_module()
        propagated_event = {
            "correlation_type": "PROPAGATED",
            "severity": "CRITICAL",
            "event_type": "AVAILABILITY",
            "ci_id": "ci-x",
            "propagated_from": "evt-parent",
            "root_cause_ci_id": "ci-y",
        }
        assert event_service._is_authoritative_event(propagated_event) is False
        root_event = {
            "correlation_type": "ROOT",
            "severity": "WARNING",
            "event_type": "AVAILABILITY",
        }
        assert event_service._is_authoritative_event(root_event) is True
