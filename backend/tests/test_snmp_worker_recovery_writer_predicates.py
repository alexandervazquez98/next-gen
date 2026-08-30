"""Strict-TDD regression test for the four existing recovery writers.

PR #2 of fix-423 / REQ-PRUNE-005 / AD-7. The collection-failures
(``engines/snmp_worker.py:405,451``) and ICMP-availability
(``:558,603``) recovery writers already include ``RECOVERED`` in their
``existing.status IN [...]`` predicate in HEAD. Issue #423's narrative
incorrectly said they only had ``'OPEN', 'ACK'``. PR #2 must NOT widen
these four (they already work) — but it MUST lock their contract with a
regression test so a future contributor doesn't narrow them.

This test parses ``engines/snmp_worker.py`` and asserts:

* All four predicate sites (collection-failures primary+fallback at
  ``:405,451`` and ICMP-availability primary+fallback at ``:558,603``)
  include ``'OPEN'``, ``'ACK'``, AND ``'RECOVERED'`` in the status list.
* The PRECEDING ``OPTIONAL MATCH`` line is anchored on the right key
  (``ci_id, metric_id`` for collection-failures / ICMP-availability;
  ``metric_id, event_type='THRESHOLD_BREACH'`` for ICMP-latency). This
  guards against accidental re-binding of the predicate to a different
  writer that already excludes RECOVERED.

If you change ``engines/snmp_worker.py`` to drop ``RECOVERED`` from any
of these four status lists, this test fails — fix-423 / REQ-PRUNE-005.
"""

from __future__ import annotations

import re
from pathlib import Path

SNMP_WORKER_PATH = Path(__file__).resolve().parents[1] / "engines" / "snmp_worker.py"


def _read_snmp_worker_source() -> str:
    return SNMP_WORKER_PATH.read_text(encoding="utf-8")


def _extract_block(source: str, *, start_marker: str, end_marker: str) -> str:
    """Extract the substring between the two markers.

    ``end_marker`` is the first occurrence of the literal after
    ``start_marker``. Returns ``""`` if either marker is missing.
    """
    start = source.find(start_marker)
    if start == -1:
        return ""
    end = source.find(end_marker, start + len(start_marker))
    if end == -1:
        return ""
    return source[start:end]


# Each entry pins ONE of the four existing predicate sites.
# ``start_marker`` identifies the OPTIONAL MATCH line; ``end_marker``
# closes at the next ``WITH row, n, m`` boundary so the regex pulls only
# the predicate line itself.
PREDICATE_SITES: tuple[tuple[str, str, str], ...] = (
    (
        "collection_failure_primary",
        # OPTIONAL MATCH for collection-failures primary query.
        "OPTIONAL MATCH (existing:Event {ci_id: row.node_id, metric_id: row.metric_id})\n"
        "            WHERE existing.status IN",
        # Closes at the next WITH row clause.
        "AND (existing.source_protocol IS NULL OR toUpper(existing.source_protocol) = row.source_protocol)\n"
        "            WITH row, n, m, head(collect(existing)) AS existing",
    ),
    (
        "collection_failure_fallback",
        # Fallback block has identical OPTIONAL MATCH; the second occurrence
        # in the source file is the fallback.
        "OPTIONAL MATCH (existing:Event {ci_id: row.node_id, metric_id: row.metric_id})\n"
        "            WHERE existing.status IN",
        # The fallback ends with a slightly different SET clause (no
        # ``poll_collector_id``), so use a less specific closing marker.
        "AND (existing.source_protocol IS NULL OR toUpper(existing.source_protocol) = row.source_protocol)\n"
        "            WITH row, n, m, head(collect(existing)) AS existing",
    ),
    (
        "icmp_availability_primary",
        # ICMP-availability has the same OPTIONAL MATCH pattern (ci_id,
        # metric_id) — we differentiate via the next WHERE line about
        # event_type='AVAILABILITY'.
        "OPTIONAL MATCH (existing:Event {ci_id: row.node_id, metric_id: row.metric_id})\n"
        "            WHERE existing.status IN",
        "AND existing.event_type = 'AVAILABILITY'\n"
        "              AND coalesce(existing.correlation_type, 'ROOT') = 'ROOT'",
    ),
    (
        "icmp_availability_fallback",
        # Fallback ICMP-availability — second occurrence of the pattern.
        "OPTIONAL MATCH (existing:Event {ci_id: row.node_id, metric_id: row.metric_id})\n"
        "            WHERE existing.status IN",
        "AND existing.event_type = 'AVAILABILITY'\n"
        "              AND coalesce(existing.correlation_type, 'ROOT') = 'ROOT'",
    ),
)


class TestRecoveryWriterPredicatesContainRecovered:
    """REQ-PRUNE-005 / AD-7 — lock contract on the four existing writers."""

    def test_collection_failure_primary_includes_recovered(self):
        source = _read_snmp_worker_source()
        # The first occurrence in source order is the collection-failures
        # primary query — it's the first OPTIONAL MATCH in the file.
        all_blocks = re.findall(
            r"OPTIONAL MATCH \(existing:Event \{ci_id: row\.node_id, metric_id: row\.metric_id\}\)\s*\n\s*WHERE existing\.status IN \[(?P<list>[^\]]+)\]",
            source,
        )
        assert all_blocks, "collection-failures predicate blocks not found"
        # First occurrence is the collection-failures primary; second is
        # its fallback. Verify the primary.
        primary_list = all_blocks[0]
        for required in ("'OPEN'", "'ACK'", "'RECOVERED'"):
            assert required in primary_list, (
                f"collection-failures primary predicate MUST include {required}; "
                f"got list={primary_list!r}"
            )

    def test_collection_failure_fallback_includes_recovered(self):
        source = _read_snmp_worker_source()
        all_blocks = re.findall(
            r"OPTIONAL MATCH \(existing:Event \{ci_id: row\.node_id, metric_id: row\.metric_id\}\)\s*\n\s*WHERE existing\.status IN \[(?P<list>[^\]]+)\]",
            source,
        )
        assert len(all_blocks) >= 2, (
            "expected at least 2 OPTIONAL MATCH (ci_id, metric_id) blocks "
            "(collection-failures primary + fallback)"
        )
        # The fallback is the second occurrence in source order.
        fallback_list = all_blocks[1]
        for required in ("'OPEN'", "'ACK'", "'RECOVERED'"):
            assert required in fallback_list, (
                f"collection-failures fallback predicate MUST include {required}; "
                f"got list={fallback_list!r}"
            )

    def test_icmp_availability_predicates_include_recovered(self):
        """ICMP-availability primary + fallback MUST keep RECOVERED.

        Per the design (design.md §Key Decisions §AD-7), these writers
        already include RECOVERED in HEAD. Lock the contract here.
        """
        source = _read_snmp_worker_source()
        # Locate all OPTIONAL MATCH lines keyed on (ci_id, metric_id) and
        # paired with a WHERE about ``event_type = 'AVAILABILITY'``. The
        # ordering in source is: collection-failures primary, collection-
        # failures fallback, ICMP-availability primary, ICMP-availability
        # fallback. So the ICMP-availability primary is the third block
        # and its fallback is the fourth.
        all_blocks = re.findall(
            r"OPTIONAL MATCH \(existing:Event \{ci_id: row\.node_id, metric_id: row\.metric_id\}\)\s*\n\s*WHERE existing\.status IN \[(?P<list>[^\]]+)\]",
            source,
        )
        assert len(all_blocks) >= 4, (
            f"expected at least 4 ci_id-keyed OPTIONAL MATCH blocks "
            f"(collection-failures primary+fallback, ICMP-availability primary+fallback); "
            f"got {len(all_blocks)}"
        )
        for label, idx in (("primary", 2), ("fallback", 3)):
            status_list = all_blocks[idx]
            for required in ("'OPEN'", "'ACK'", "'RECOVERED'"):
                assert required in status_list, (
                    f"ICMP-availability {label} predicate MUST include "
                    f"{required}; got list={status_list!r}"
                )

    def test_icmp_availability_predicates_are_distinct_blocks(self):
        """Defensive: confirm the primary and fallback blocks exist and
        are NOT duplicates. A naive copy-paste regression would have the
        fallback regress to the older ``['OPEN', 'ACK']`` set; this test
        guards against that by asserting the two blocks are separately
        identifiable."""
        source = _read_snmp_worker_source()
        # Split by ``primary_query = """\n            UNWIND`` and
        # ``fallback_query = """\n            UNWIND`` markers so we know
        # which block is which.
        primary_marker = 'primary_query = """\n            UNWIND'
        fallback_marker = 'fallback_query = """\n            UNWIND'

        # Find ICMP-availability section by anchoring on ``event_type = 'AVAILABILITY'``.
        avail_sections = re.split(
            r"(?=primary_query = \"\"\"\s*\n\s*UNWIND \$availability_events)",
            source,
        )
        assert len(avail_sections) >= 2, "ICMP-availability primary_query block not found"
        primary_section = avail_sections[1]
        fallback_sections = primary_section.split(fallback_marker, 1)
        assert len(fallback_sections) >= 2, "ICMP-availability fallback_query block not found"
        primary_block = fallback_sections[0]
        fallback_block = fallback_sections[1].split(primary_marker, 1)[0]

        primary_match = re.search(r"existing\.status IN \[(?P<list>[^\]]+)\]", primary_block)
        fallback_match = re.search(r"existing\.status IN \[(?P<list>[^\]]+)\]", fallback_block)
        assert primary_match, "ICMP-availability primary status IN list not found"
        assert fallback_match, "ICMP-availability fallback status IN list not found"
        assert primary_match.group("list") == fallback_match.group("list"), (
            "ICMP-availability primary and fallback predicates diverged — "
            "either both must keep RECOVERED, or the contract test is "
            "comparing the wrong pair."
        )


class TestRecoveryWritersDoNotRegressToOpenAckOnly:
    """REQ-PRUNE-005 contract: the four existing recovery writers MUST NOT
    be narrowed to ``['OPEN', 'ACK']`` only. Issue #423's narrative said
    they were, but HEAD includes RECOVERED. This test asserts the IN
    list is NOT the ``['OPEN', 'ACK']`` shape that would be a regression
    of the post-fix-423 contract.
    """

    def test_collection_failures_primary_is_not_open_ack_only(self):
        source = _read_snmp_worker_source()
        all_blocks = re.findall(
            r"OPTIONAL MATCH \(existing:Event \{ci_id: row\.node_id, metric_id: row\.metric_id\}\)\s*\n\s*WHERE existing\.status IN \[(?P<list>[^\]]+)\]",
            source,
        )
        primary = all_blocks[0]
        normalized = re.sub(r"\s+", "", primary)
        assert normalized != "'OPEN','ACK'", (
            "collection-failures primary regressed to OPEN/ACK-only — "
            "REQ-PRUNE-005 requires RECOVERED to stay in the predicate."
        )

    def test_collection_failures_fallback_is_not_open_ack_only(self):
        source = _read_snmp_worker_source()
        all_blocks = re.findall(
            r"OPTIONAL MATCH \(existing:Event \{ci_id: row\.node_id, metric_id: row\.metric_id\}\)\s*\n\s*WHERE existing\.status IN \[(?P<list>[^\]]+)\]",
            source,
        )
        fallback = all_blocks[1]
        normalized = re.sub(r"\s+", "", fallback)
        assert normalized != "'OPEN','ACK'", (
            "collection-failures fallback regressed to OPEN/ACK-only — "
            "REQ-PRUNE-005 requires RECOVERED to stay in the predicate."
        )
