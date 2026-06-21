"""Mandatory multi-CI dependency chain RCA integration test (REQ-CORR-1).

This is the centerpiece test for the Path A RCA change. It exercises the
real `poll_snmp()` write path against a `MockNeo4jDriver` to prove that:

  1. Fan-out topology (A ← B, C, D): A is ROOT, B/C/D are PROPAGATED with
     `propagated_from=A's event id` and `root_cause_ci_id='A'`.
  2. 3-hop chain (A → B → C, different severities): A is ROOT WARNING,
     B is PROPAGATED CRITICAL, C is PROPAGATED WARNING with the
     descendant's OWN severity, not the root's.
  3. Mixed severities regression: propagated severity never flattens to
     root severity.

Mock boundary: the SNMP poller is stubbed. `find_open_parent_event` is
NOT mocked — the real Cypher runs against the mock session, with canned
parent records loaded per ci_id by `ChainMockNeo4jSession`.

Strict TDD: this test must FAIL before T6 wires `resolve_correlation_fields`
into Path A — the current code hardcodes `'ROOT'` literals in the CREATE
Event queries. After T6, the queries use `row.correlation_type` /
`row.root_cause_ci_id` params and the assertions pass.
"""

from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

# Ensure backend root is on the import path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.fixtures.rca_chain import build_dependency_chain  # noqa: E402


def _run_poll_cycle(fixture):
    """Run a single poll_snmp() with all required patches in place.

    Pre-populates the ICMP debounce counter to 2 for every CI in the chain
    so the first failure triggers an event (default debounce_count=3).
    """
    from engines import snmp_worker

    # Reset module-level debounce state
    snmp_worker._consecutive_failures.clear()
    for ci in fixture["ci_ids"]:
        snmp_worker._consecutive_failures[ci] = 2  # one more failure triggers event

    with patch("engines.snmp_worker.driver", fixture["driver"]), \
         patch("engines.snmp_worker.SessionLocal", return_value=fixture["db"]), \
         patch("engines.snmp_worker.bulk_insert_metrics") as mock_bulk_insert, \
         patch("engines.snmp_worker.fetch_icmp_ping", return_value=fixture["ping_measurement"]):
        snmp_worker.poll_snmp()

    return mock_bulk_insert


def _get_event_row_for(fixture, ci_id):
    """Pull the (node_id, correlation_type, root_cause_ci_id, propagated_from, severity)
    tuple from the captured CREATE Event queries for `ci_id`.

    Returns a dict of captured fields, or None if no event was captured.
    """
    captured = fixture["session"].created_events.get(ci_id)
    if not captured:
        return None
    # The first captured query is the AVAILABILITY one for this ci.
    for entry in captured:
        params = entry["params"]
        for key in ("availability_events", "failures", "breaches"):
            if key in params and isinstance(params[key], list) and params[key]:
                row = params[key][0]
                return {
                    "node_id": row.get("node_id"),
                    "metric_id": row.get("metric_id"),
                    "severity": row.get("severity"),
                    "correlation_type": row.get("correlation_type"),
                    "root_cause_ci_id": row.get("root_cause_ci_id"),
                    "propagated_from": row.get("propagated_from"),
                    "source_query_text": entry["query"],
                }
    return None


def _query_text_uses_row_correlation_param(fixture, ci_id):
    """Inspect the captured query text: does the CREATE Event use `row.correlation_type`
    instead of a hardcoded 'ROOT' literal?

    Returns True if the query text contains the row-param form, False if it
    contains a hardcoded 'ROOT' literal (RED state), None if no event captured.
    """
    captured = fixture["session"].created_events.get(ci_id)
    if not captured:
        return None
    query_text = captured[0]["query"]
    if "correlation_type: row.correlation_type" in query_text:
        return True
    if "correlation_type: 'ROOT'" in query_text or 'correlation_type: "ROOT"' in query_text:
        return False
    # Hardcoded form might not include the literal if query text was reformatted
    return "'ROOT'" in query_text


# ---------------------------------------------------------------------------
# Scenario 1: fan-out — A CRITICAL → A ROOT, B/C/D PROPAGATED with own severities
# ---------------------------------------------------------------------------


class TestFanOutChain:
    """Fan-out topology: A is root, B/C/D depend on A. Mixed severities."""

    def _build(self):
        return build_dependency_chain(
            topology="fan_out",
            root_count=1,
            dependent_count=3,
            severities={"ci-A": "CRITICAL", "ci-B": "CRITICAL", "ci-C": "WARNING", "ci-D": "WARNING"},
        )

    def test_root_A_event_is_ROOT(self):
        fixture = self._build()
        _run_poll_cycle(fixture)

        a_event = _get_event_row_for(fixture, "ci-A")
        assert a_event is not None, "expected A's event to be captured"
        # Severity follows the metric — A is CRITICAL.
        assert a_event["severity"] == "CRITICAL"
        # ROOT: A is its own root cause.
        assert a_event["correlation_type"] == "ROOT", (
            f"expected ROOT for A, got {a_event['correlation_type']!r}"
        )
        assert a_event["root_cause_ci_id"] == "ci-A", (
            f"expected root_cause_ci_id='ci-A' for A, got {a_event['root_cause_ci_id']!r}"
        )
        assert a_event["propagated_from"] is None, (
            f"expected propagated_from=None for A, got {a_event['propagated_from']!r}"
        )

    @pytest.mark.parametrize("dependent", ["ci-B", "ci-C", "ci-D"])
    def test_dependent_is_PROPAGATED_with_own_severity(self, dependent):
        fixture = self._build()
        _run_poll_cycle(fixture)

        dep_event = _get_event_row_for(fixture, dependent)
        assert dep_event is not None, f"expected {dependent}'s event to be captured"

        expected_severity = fixture["severities"][dependent]
        assert dep_event["severity"] == expected_severity, (
            f"expected severity {expected_severity} for {dependent}, got {dep_event['severity']!r}"
        )

        assert dep_event["correlation_type"] == "PROPAGATED", (
            f"expected PROPAGATED for {dependent}, got ROOT — Path A is hardcoding ROOT. "
            f"Query text: {dep_event['source_query_text'][:200]!r}"
        )
        assert dep_event["root_cause_ci_id"] == "ci-A", (
            f"expected root_cause_ci_id='ci-A' for {dependent}, got {dep_event['root_cause_ci_id']!r}"
        )
        assert dep_event["propagated_from"] == fixture["root_event_id"], (
            f"expected propagated_from={fixture['root_event_id']!r} for {dependent}, "
            f"got {dep_event['propagated_from']!r}"
        )

    def test_query_text_uses_row_correlation_param(self):
        """After T6, the CREATE Event query must use `row.correlation_type` / `row.root_cause_ci_id`
        instead of hardcoded `'ROOT'` / `row.node_id` literals."""
        fixture = self._build()
        _run_poll_cycle(fixture)

        for ci in fixture["ci_ids"]:
            uses_row_param = _query_text_uses_row_correlation_param(fixture, ci)
            assert uses_row_param is True, (
                f"{ci}: query text still hardcodes 'ROOT' instead of using row.correlation_type. "
                f"Path A wire-in (T6) is required."
            )


# ---------------------------------------------------------------------------
# Scenario 2: 3-hop chain — A WARNING, B CRITICAL, C WARNING
# ---------------------------------------------------------------------------


class TestThreeHopChain:
    """3-hop chain: A → B → C, severities A=WARNING, B=CRITICAL, C=WARNING."""

    def _build(self):
        return build_dependency_chain(
            topology="chain",
            root_count=1,
            dependent_count=3,
            severities={"ci-A": "WARNING", "ci-B": "CRITICAL", "ci-C": "WARNING"},
        )

    def test_A_is_ROOT_WARNING(self):
        fixture = self._build()
        _run_poll_cycle(fixture)

        a_event = _get_event_row_for(fixture, "ci-A")
        assert a_event is not None, "expected A's event to be captured"
        assert a_event["severity"] == "WARNING"
        assert a_event["correlation_type"] == "ROOT"
        assert a_event["root_cause_ci_id"] == "ci-A"
        assert a_event["propagated_from"] is None

    def test_B_is_PROPAGATED_CRITICAL_with_own_severity(self):
        fixture = self._build()
        _run_poll_cycle(fixture)

        b_event = _get_event_row_for(fixture, "ci-B")
        assert b_event is not None, "expected B's event to be captured"
        assert b_event["severity"] == "CRITICAL", (
            f"B must keep its own CRITICAL severity, not flatten to A's WARNING. "
            f"Got: {b_event['severity']!r}"
        )
        assert b_event["correlation_type"] == "PROPAGATED", (
            f"expected PROPAGATED for B, got {b_event['correlation_type']!r}"
        )
        assert b_event["root_cause_ci_id"] == "ci-A", (
            f"B inherits A's root_cause_ci_id. Got: {b_event['root_cause_ci_id']!r}"
        )

    def test_C_is_PROPAGATED_WARNING_with_own_severity(self):
        fixture = self._build()
        _run_poll_cycle(fixture)

        c_event = _get_event_row_for(fixture, "ci-C")
        assert c_event is not None, "expected C's event to be captured"
        assert c_event["severity"] == "WARNING", (
            f"C must keep its own WARNING severity. Got: {c_event['severity']!r}"
        )
        assert c_event["correlation_type"] == "PROPAGATED", (
            f"expected PROPAGATED for C, got {c_event['correlation_type']!r}"
        )
        # C's root cause inherits through B (which inherited from A) — should be 'ci-A'.
        assert c_event["root_cause_ci_id"] == "ci-A", (
            f"C's root_cause_ci_id must be the original root 'ci-A' (inherited through B). "
            f"Got: {c_event['root_cause_ci_id']!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 3: mixed-severity regression — propagated severity must NEVER flatten
# ---------------------------------------------------------------------------


class TestMixedSeveritiesRegression:
    """Mixed severities regression: each descendant's severity must be its own."""

    def test_fan_out_with_all_distinct_severities(self):
        fixture = build_dependency_chain(
            topology="fan_out",
            root_count=1,
            dependent_count=3,
            severities={
                "ci-A": "CRITICAL",
                "ci-B": "WARNING",
                "ci-C": "INFO",       # Edge case: low severity, must still propagate
                "ci-D": "CRITICAL",   # Another CRITICAL descendant — distinct from A
            },
        )
        _run_poll_cycle(fixture)

        # A: ROOT CRITICAL
        a_event = _get_event_row_for(fixture, "ci-A")
        assert a_event["correlation_type"] == "ROOT"
        assert a_event["severity"] == "CRITICAL"

        # B/C/D: each PROPAGATED with their own severity
        for ci, expected_sev in [("ci-B", "WARNING"), ("ci-C", "INFO"), ("ci-D", "CRITICAL")]:
            ev = _get_event_row_for(fixture, ci)
            assert ev is not None, f"{ci} event not captured"
            assert ev["correlation_type"] == "PROPAGATED", (
                f"{ci}: expected PROPAGATED, got ROOT — Path A is hardcoding ROOT"
            )
            assert ev["severity"] == expected_sev, (
                f"{ci}: severity flattened to {ev['severity']!r} "
                f"(expected {expected_sev!r}). Propagated events must retain own severity."
            )
            assert ev["root_cause_ci_id"] == "ci-A"

    def test_chain_with_warning_root_does_not_propagate_severity(self):
        """Even when root is WARNING, descendants' CRITICAL severity must NOT be flattened."""
        fixture = build_dependency_chain(
            topology="chain",
            root_count=1,
            dependent_count=3,
            severities={"ci-A": "WARNING", "ci-B": "CRITICAL", "ci-C": "WARNING"},
        )
        _run_poll_cycle(fixture)

        a_ev = _get_event_row_for(fixture, "ci-A")
        b_ev = _get_event_row_for(fixture, "ci-B")

        # A is WARNING, B is CRITICAL. B must remain CRITICAL (own severity).
        assert a_ev["severity"] == "WARNING"
        assert b_ev["severity"] == "CRITICAL", (
            f"B's severity flattened to root's WARNING; got {b_ev['severity']!r}"
        )
        assert b_ev["correlation_type"] == "PROPAGATED"
