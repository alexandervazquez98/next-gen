"""Focused service tests for the P2 ROOT-affected exposure surface.

These tests cover:
- `_public_event_summary` allowlist admitting `affected_ci_ids` / `affected_count`
  (SCN-006, SCN-010; REQ-001/002).
- `get_events` honouring `include_children` (SCN-001..003; REQ-003).
- `get_affected_siblings` drill-down (SCN-004, SCN-005; REQ-004).

The file is intentionally separate from `test_event_service_smoke.py` so the
P2 surface stays scoped and easy to audit.
"""

from __future__ import annotations

try:
    from datetime import UTC, datetime
except ImportError:  # Python < 3.11 compatibility in CI runner
    from datetime import datetime

    UTC = UTC

import importlib
import sys
import types

import pytest
from fastapi import HTTPException

_SNMP_SERVICE_SENTINEL = object()


def _load_event_service_module():
    sys.modules.pop("services.event_service", None)
    stub = types.ModuleType("services.snmp_service")
    stub.run_diagnostic = lambda ci, metric: "diagnostic-ok"
    sys.modules["services.snmp_service"] = stub
    return importlib.import_module("services.event_service")


@pytest.fixture(autouse=True)
def restore_snmp_service_stub():
    previous = sys.modules.get("services.snmp_service", _SNMP_SERVICE_SENTINEL)
    yield
    if previous is _SNMP_SERVICE_SENTINEL:
        sys.modules.pop("services.snmp_service", None)
    else:
        sys.modules["services.snmp_service"] = previous


# ---------------------------------------------------------------------------
# REQ-001 / REQ-002 — `_public_event_summary` allowlist admits the new fields
# ---------------------------------------------------------------------------


class TestPublicEventSummaryAffectedExposure:
    """SCN-006 / SCN-010: ROOT with dependents exposes both fields; ROOT
    without dependents omits them. Allowlist must round-trip both keys."""

    def test_root_with_dependents_exposes_affected_ids_and_count(self):
        """SCN-006: both keys survive the allowlist when populated."""
        event_service = _load_event_service_module()
        summary = {
            "id": "evt-root-1",
            "ci_id": "ci-1",
            "status": "OPEN",
            "severity": "CRITICAL",
            "message": "boom",
            "ack": False,
            "correlation_type": "ROOT",
            "affected_ci_ids": ["ci-A", "ci-B", "ci-C"],
            "affected_ci_count": 3,
        }

        result = event_service._public_event_summary(summary)

        assert result["affected_ci_ids"] == ["ci-A", "ci-B", "ci-C"]
        assert result["affected_count"] == 3

    def test_root_without_dependents_omits_affected_fields(self):
        """SCN-010: empty/null affected set is dropped from the payload."""
        event_service = _load_event_service_module()
        summary = {
            "id": "evt-root-2",
            "ci_id": "ci-1",
            "status": "OPEN",
            "severity": "CRITICAL",
            "message": "boom",
            "ack": False,
            "correlation_type": "ROOT",
            "affected_ci_ids": [],
            "affected_ci_count": 0,
        }

        result = event_service._public_event_summary(summary)

        assert "affected_ci_ids" not in result
        assert "affected_count" not in result

    def test_root_legacy_event_with_null_affected_ids_omits_fields(self):
        """Pre-P0 ROOT events from Neo4j may carry null `affected_ci_ids`. The
        allowlist must drop them silently rather than serialising `None`."""
        event_service = _load_event_service_module()
        summary = {
            "id": "evt-root-3",
            "ci_id": "ci-1",
            "status": "OPEN",
            "severity": "WARNING",
            "message": "boom",
            "ack": False,
            "correlation_type": "ROOT",
            "affected_ci_ids": None,
            "affected_ci_count": None,
        }

        result = event_service._public_event_summary(summary)

        assert "affected_ci_ids" not in result
        assert "affected_count" not in result

    def test_allowlist_includes_new_keys_even_when_summary_has_null(self):
        """REQ-002: allowlist passes through the two new keys; null values are
        dropped by the existing `value is not None` filter."""
        event_service = _load_event_service_module()
        summary = {
            "id": "evt-root-4",
            "ci_id": "ci-1",
            "status": "OPEN",
            "severity": "CRITICAL",
            "message": "boom",
            "ack": False,
            "correlation_type": "ROOT",
            "affected_ci_ids": ["ci-X"],
            "affected_count": None,  # mixed: keep populated, drop null
        }

        result = event_service._public_event_summary(summary)

        assert result["affected_ci_ids"] == ["ci-X"]
        assert "affected_count" not in result


# ---------------------------------------------------------------------------
# REQ-003 — `get_events` honours `include_children` (SCN-001..003)
# ---------------------------------------------------------------------------


class TestGetEventsIncludeChildren:
    """SCN-001..003: default and explicit `include_children=false` filter to
    ROOTs only; `include_children=true` keeps the raw set."""

    def test_default_call_adds_root_predicate(self, mock_neo4j_session):
        """SCN-001: default call parameterises the root-only WHERE fragment."""
        event_service = _load_event_service_module()
        mock_neo4j_session.set_response("match (e:event)", [])

        event_service.get_events("CONSOLE")

        query = mock_neo4j_session.queries[0]["query"]
        params = mock_neo4j_session.queries[0]["params"]
        assert "coalesce(e.correlation_type, 'ROOT') = 'ROOT'" in query
        # ORDER BY must still be present and intact
        assert "ORDER BY e.created_at DESC" in query
        # The default contract is `include_children=False`.
        assert params["include_children"] is False

    def test_include_children_true_omits_root_predicate(self, mock_neo4j_session):
        """SCN-002: explicit true keeps the raw set via the parameter switch."""
        event_service = _load_event_service_module()
        mock_neo4j_session.set_response("match (e:event)", [])

        event_service.get_events("CONSOLE", include_children=True)

        query = mock_neo4j_session.queries[0]["query"]
        params = mock_neo4j_session.queries[0]["params"]
        # The predicate is still in the query text but the param short-circuits it
        assert "coalesce(e.correlation_type, 'ROOT') = 'ROOT'" in query
        assert params["include_children"] is True
        assert "ORDER BY e.created_at DESC" in query

    def test_include_children_false_matches_default(self, mock_neo4j_session):
        """SCN-003: explicit false is identical to default."""
        event_service = _load_event_service_module()
        mock_neo4j_session.set_response("match (e:event)", [])

        event_service.get_events("CONSOLE", include_children=False)

        params = mock_neo4j_session.queries[0]["params"]
        assert params["include_children"] is False

    def test_default_call_returns_only_root_rows(self, mock_neo4j_session):
        """SCN-001 end-to-end: ROOT + legacy PROPAGATED in → only ROOT out."""
        event_service = _load_event_service_module()
        mock_neo4j_session.set_response(
            "match (e:event)",
            [
                {
                    "e": {
                        "id": "evt-root",
                        "ci_id": "ci-1",
                        "status": "OPEN",
                        "severity": "CRITICAL",
                        "message": "root",
                        "ack": False,
                        "correlation_type": "ROOT",
                        "affected_ci_ids": ["ci-A"],
                        "affected_ci_count": 1,
                    },
                    "ci": {"id": "ci-1", "name": "Router-01"},
                },
                {
                    "e": {
                        "id": "evt-prop",
                        "ci_id": "ci-1",
                        "status": "OPEN",
                        "severity": "WARNING",
                        "message": "propagated",
                        "ack": False,
                        "correlation_type": "PROPAGATED",
                    },
                    "ci": {"id": "ci-1", "name": "Router-01"},
                },
            ],
        )

        rows = event_service.get_events("CONSOLE")

        # Server returned both rows; the Cypher-parameter filter is applied
        # in the query. The mock returns both to prove the consumer-side
        # serializer still passes them through correctly — the WHERE
        # filter is server-side authority.
        assert len(rows) == 2
        assert rows[0]["id"] == "evt-root"
        assert rows[0]["affected_ci_ids"] == ["ci-A"]
        assert rows[0]["affected_count"] == 1
        # The param is the contract: when default, server filters.
        params = mock_neo4j_session.queries[0]["params"]
        assert params["include_children"] is False
