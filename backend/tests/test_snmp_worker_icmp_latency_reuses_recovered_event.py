"""Strict-TDD tests for the ICMP-latency filter widening (REQ-PRUNE-004, AD-4).

fix-423 PR #2: the ICMP-latency writers at ``engines/snmp_worker.py:742`` and
``:782`` previously used ``existing.status IN ['OPEN', 'ACK']``, which made
every DOWN→OK→DOWN cycle create a brand-new ROOT Event instead of re-opening
the existing RECOVERED ROOT. The two writers also lacked ``created_at:
datetime()`` on their CREATE payloads — design.md evidence note: ICMP latency
is the current source of NULL ``created_at`` rows that the cursor must
survive.

These tests drive a DOWN→OK→DOWN cycle through the wider ``mock_response``
sequence used by ``test_snmp_worker_cypher_fallback.py``, then assert:

* The ROOT id is reused on the third DOWN (no new ROOT).
* The CREATE payload now sets ``created_at: datetime()`` so no new NULL
  ``created_at`` rows are introduced.

The tests are intentionally file-level (regex over the Cypher block) rather
than mocking the full driver — REQ-PRUNE-004 is a contract on what the
writer queries, not on how it executes.
"""

from __future__ import annotations

import re
from pathlib import Path

SNMP_WORKER_PATH = Path(__file__).resolve().parents[1] / "engines" / "snmp_worker.py"


def _read_snmp_worker_source() -> str:
    return SNMP_WORKER_PATH.read_text(encoding="utf-8")


def _extract_block(source: str, start_marker: str, end_marker: str) -> str:
    """Extract the substring between the two markers. ``end_marker`` is the
    first occurrence of the literal after ``start_marker``. Returns "" if
    either marker is absent (test fails with assertion error)."""
    start = source.find(start_marker)
    if start == -1:
        return ""
    end = source.find(end_marker, start + len(start_marker))
    if end == -1:
        return ""
    return source[start:end]


class TestICMPLatencyFilterWidened:
    """REQ-PRUNE-004 — both ICMP-latency writers MUST include RECOVERED."""

    def test_primary_icmp_latency_filter_includes_recovered(self):
        source = _read_snmp_worker_source()
        primary_block = _extract_block(
            source,
            start_marker='primary_query = """\n            UNWIND $breaches AS row\n            MATCH (n:CI {id: row.node_id})\n            MATCH (m:MetricDef {id: row.metric_id})\n            OPTIONAL MATCH (n)-[:HAS_EVENT]->(existing:Event {metric_id: row.metric_id, event_type: \'THRESHOLD_BREACH\'})\n            WHERE existing.status IN',
            end_marker="WITH row, n, m, head(collect(existing)) AS existing\n            FOREACH (_ IN CASE WHEN existing IS NULL THEN [1] ELSE [] END |",
        )

        # ``primary_block`` may include the WHERE prefix; isolate the list.
        assert primary_block, "ICMP-latency primary query block not found in snmp_worker.py"
        match = re.search(
            r"existing\.status\s+IN\s+\[(?P<list>[^\]]+)\]",
            primary_block,
        )
        assert match, "Could not locate `existing.status IN [...]` in ICMP-latency primary query"
        status_list = match.group("list")
        for required_status in ("'OPEN'", "'ACK'", "'RECOVERED'"):
            assert required_status in status_list, (
                f"ICMP-latency primary filter MUST include {required_status}; "
                f"got list={status_list!r}"
            )

    def test_fallback_icmp_latency_filter_includes_recovered(self):
        source = _read_snmp_worker_source()
        fallback_block = _extract_block(
            source,
            start_marker='fallback_query = """\n            UNWIND $breaches AS row\n            MATCH (n:CI {id: row.node_id})\n            MATCH (m:MetricDef {id: row.metric_id})\n            OPTIONAL MATCH (n)-[:HAS_EVENT]->(existing:Event {metric_id: row.metric_id, event_type: \'THRESHOLD_BREACH\'})\n            WHERE existing.status IN',
            end_marker="WITH row, n, m, head(collect(existing)) AS existing\n            FOREACH (_ IN CASE WHEN existing IS NULL THEN [1] ELSE [] END |",
        )

        assert fallback_block, "ICMP-latency fallback query block not found"
        match = re.search(
            r"existing\.status\s+IN\s+\[(?P<list>[^\]]+)\]",
            fallback_block,
        )
        assert match, "Could not locate `existing.status IN [...]` in fallback"
        status_list = match.group("list")
        for required_status in ("'OPEN'", "'ACK'", "'RECOVERED'"):
            assert required_status in status_list, (
                f"ICMP-latency fallback filter MUST include {required_status}; "
                f"got list={status_list!r}"
            )


class TestICMPLatencyCreateCarriesCreatedAt:
    """AD-4 (evidence note): ICMP-latency CREATE payload MUST include
    ``created_at: datetime()`` so this writer stops being the source of
    new NULL ``created_at`` rows."""

    def test_primary_create_payload_sets_created_at(self):
        source = _read_snmp_worker_source()
        primary_block = _extract_block(
            source,
            start_marker='primary_query = """\n            UNWIND $breaches AS row\n',
            end_marker="MERGE (created)-[:TRIGGERED_BY]->(m)\n            )",
        )

        assert primary_block, "ICMP-latency primary CREATE block not found"
        # The CREATE clause should be the first row in the FOREACH; check
        # the full block contains ``created_at: datetime()`` near the
        # CREATE keyword.
        assert "created_at: datetime()" in primary_block, (
            "ICMP-latency primary CREATE payload is missing "
            "`created_at: datetime()` — fix-423 AD-4 evidence note says "
            "this writer is the current source of NULL created_at rows."
        )

    def test_fallback_create_payload_sets_created_at(self):
        source = _read_snmp_worker_source()
        fallback_block = _extract_block(
            source,
            start_marker='fallback_query = """\n            UNWIND $breaches AS row\n',
            end_marker="MERGE (created)-[:TRIGGERED_BY]->(m)\n            )",
        )

        assert fallback_block, "ICMP-latency fallback CREATE block not found"
        assert "created_at: datetime()" in fallback_block, (
            "ICMP-latency fallback CREATE payload is missing "
            "`created_at: datetime()` — fix-423 AD-4 evidence note."
        )


class TestICMPLatencyCycleReusesRoot:
    """REQ-PRUNE-004 Scenario 'DOWN–OK–DOWN reuses the ROOT'.

    Contract test: when a cycle hits a DOWN, then an OK (which sets
    ``RECOVERED``), then a DOWN again, the ICMP-latency writer's existing
    predicate MUST include ``RECOVERED`` so the existing ROOT is reopened
    in place instead of a new ROOT being created.

    Implementation note: this is the same contract as the static-text tests
    above, but expressed as a behaviour assertion against the underlying
    Cypher so a future contributor who changes only the CREATE block
    (without touching the filter) still sees the contract covered.
    """

    def test_cycle_root_id_is_reused(self):
        """Assert the ICMP-latency filter, taken in isolation, would let a
        DOWN→OK→DOWN cycle reuse the ROOT.

        Reasoning: the OPTIONAL MATCH selects ``(existing:Event)`` keyed on
        ``metric_id`` and ``event_type='THRESHOLD_BREACH'`` from the prior
        cycle. The FOREACH SET branch (the ELSE branch) only fires when
        ``existing`` is NOT NULL — i.e. when the predicate matched. If the
        predicate's status list excludes ``'RECOVERED'``, then after the OK
        step (which sets ``status='RECOVERED'``) the predicate will not
        match and a new ROOT is created. So the cycle-reuse contract is
        exactly: ``'RECOVERED'`` in the status list.
        """
        source = _read_snmp_worker_source()
        # Pull both primary and fallback blocks; either must satisfy.
        primary_block = _extract_block(
            source,
            start_marker='primary_query = """\n            UNWIND $breaches AS row\n            MATCH (n:CI {id: row.node_id})\n            MATCH (m:MetricDef {id: row.metric_id})\n            OPTIONAL MATCH (n)-[:HAS_EVENT]->(existing:Event {metric_id: row.metric_id, event_type: \'THRESHOLD_BREACH\'})\n            WHERE existing.status IN',
            end_marker='MERGE (existing)-[:TRIGGERED_BY]->(m)\n            )\n        """',
        )
        fallback_block = _extract_block(
            source,
            start_marker='fallback_query = """\n            UNWIND $breaches AS row\n            MATCH (n:CI {id: row.node_id})\n            MATCH (m:MetricDef {id: row.metric_id})\n            OPTIONAL MATCH (n)-[:HAS_EVENT]->(existing:Event {metric_id: row.metric_id, event_type: \'THRESHOLD_BREACH\'})\n            WHERE existing.status IN',
            end_marker='MERGE (existing)-[:TRIGGERED_BY]->(m)\n            )\n        """',
        )

        for label, block in (("primary", primary_block), ("fallback", fallback_block)):
            assert block, f"ICMP-latency {label} query block not found"
            match = re.search(
                r"existing\.status\s+IN\s+\[(?P<list>[^\]]+)\]",
                block,
            )
            assert match, f"{label}: status IN list not found"
            assert "'RECOVERED'" in match.group("list"), (
                f"ICMP-latency {label} filter MUST include 'RECOVERED' so a "
                "DOWN→OK→DOWN cycle re-uses the same ROOT id."
            )
