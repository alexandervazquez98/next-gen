"""Strict-TDD regression test for the six recovery-writer predicate sites.

REQ-PRUNE-005 / AD-7 (fix-423) and REQ-RECOVERY-002 (fix-484). The
collection-failures (``engines/snmp_worker.py``), ICMP-availability,
ICMP-jitter, and ICMP-packet-loss writers MUST keep ``RECOVERED`` in
their ``existing.status IN [...]`` predicate (and their respective
``event_type`` discriminator) so a subsequent failure reopens the
existing ROOT Event rather than creating a new ROOT.

The test parses ``engines/snmp_worker.py`` and asserts:

* All six predicate sites (collection-failures primary+fallback keyed
  on ``(ci_id, metric_id)``; ICMP-availability primary+fallback keyed
  on ``(ci_id, metric_id)``; ICMP-jitter primary+fallback keyed on
  ``(metric_id, event_type='THRESHOLD_BREACH')``; ICMP-packet-loss
  primary+fallback keyed on
  ``(metric_id, event_type='THRESHOLD_BREACH')``) include ``'OPEN'``,
  ``'ACK'``, AND ``'RECOVERED'`` in the status list.
* The preceding ``OPTIONAL MATCH`` line is anchored on the right key:
  - ``ci_id, metric_id`` for collection-failures / ICMP-availability
  - ``metric_id, event_type='THRESHOLD_BREACH'`` for the three ICMP
    refresh writers (latency, jitter, packet-loss).

If you change ``engines/snmp_worker.py`` to drop ``RECOVERED`` from any
of these six status lists, this test fails.
"""

from __future__ import annotations

import re
from pathlib import Path

SNMP_WORKER_PATH = Path(__file__).resolve().parents[1] / "engines" / "snmp_worker.py"

# Regex matches the (ci_id, metric_id)-keyed OPTIONAL MATCH used by the
# collection-failures and ICMP-availability refresh helpers. The status
# list is captured as a named group ``list``.
_CI_METRIC_OPTIONAL_MATCH_RE = re.compile(
    r"OPTIONAL MATCH \(existing:Event \{ci_id: row\.node_id, metric_id: row\.metric_id\}\)\s*\n"
    r"\s*WHERE existing\.status IN \[(?P<list>[^\]]+)\]"
)

# Regex matches the (metric_id, event_type)-keyed OPTIONAL MATCH used by
# the three ICMP refresh writers (latency, jitter, packet-loss).
_METRIC_EVENT_OPTIONAL_MATCH_RE = re.compile(
    r"OPTIONAL MATCH \(n\)-\[:HAS_EVENT\]->\(existing:Event \{metric_id: row\.metric_id, event_type: 'THRESHOLD_BREACH'\}\)\s*\n"
    r"\s*WHERE existing\.status IN \[(?P<list>[^\]]+)\]"
)


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


# Each entry pins ONE of the six existing predicate sites.
# ``start_marker`` identifies the OPTIONAL MATCH line; ``end_marker``
# closes at the next boundary.
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
    # ── fix-484 (REQ-RECOVERY-002 / AD-7) ──────────────────────────────
    # ICMP-jitter and ICMP-packet-loss use the metric_id+event_type keyed
    # OPTIONAL MATCH (different from collection-failures / availability).
    # Each entry's primary / fallback distinction is anchored via the
    # anchor marker on the ``UNWIND`` line and the named metric_id arg
    # check.
    (
        "icmp_jitter_events_predicate_site",
        "UNWIND $breaches AS row\n"
        "            MATCH (n:CI {id: row.node_id})\n"
        "            MATCH (m:MetricDef {id: row.metric_id})\n"
        "            OPTIONAL MATCH (n)-[:HAS_EVENT]->(existing:Event {metric_id: row.metric_id, event_type: 'THRESHOLD_BREACH'})\n"
        "            WHERE existing.status IN",
        "AND coalesce(existing.correlation_type, 'ROOT') = 'ROOT'",
    ),
    (
        "icmp_packet_loss_events_predicate_site",
        "UNWIND $breaches AS row\n"
        "            MATCH (n:CI {id: row.node_id})\n"
        "            MATCH (m:MetricDef {id: row.metric_id})\n"
        "            OPTIONAL MATCH (n)-[:HAS_EVENT]->(existing:Event {metric_id: row.metric_id, event_type: 'THRESHOLD_BREACH'})\n"
        "            WHERE existing.status IN",
        "AND coalesce(existing.correlation_type, 'ROOT') = 'ROOT'",
    ),
)


class TestRecoveryWriterPredicatesContainRecovered:
    """REQ-PRUNE-005 / REQ-RECOVERY-002 — lock contract on the six writers."""

    def test_collection_failure_primary_includes_recovered(self):
        source = _read_snmp_worker_source()
        # The first occurrence in source order is the collection-failures
        # primary query — it's the first OPTIONAL MATCH in the file.
        all_blocks = _CI_METRIC_OPTIONAL_MATCH_RE.findall(source)
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
        all_blocks = _CI_METRIC_OPTIONAL_MATCH_RE.findall(source)
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
        all_blocks = _CI_METRIC_OPTIONAL_MATCH_RE.findall(source)
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

    # ── fix-484 (REQ-RECOVERY-002) — extend the lock to six sites ─────

    def test_icmp_jitter_events_predicate_includes_recovered(self):
        """REQ-RECOVERY-002 / fix-484: ICMP-jitter RECOVERED eligibility.

        The ``_refresh_icmp_jitter_events`` writer MUST keep ``'RECOVERED'``
        in its existing-event ``status IN [...]`` predicate so a subsequent
        failure reopens the existing ROOT Event rather than creating a new
        ROOT. Locks the 5th predicate site in the regression contract.
        """
        source = _read_snmp_worker_source()
        # Lock the writer's primary + fallback by anchoring on the
        # call site (``_refresh_icmp_jitter_events`` function).
        primary_marker = (
            "def _refresh_icmp_jitter_events(session, updates, cache=None, lock_db=None):"
        )
        assert (
            primary_marker in source
        ), "_refresh_icmp_jitter_events definition not found — regression test is stale"

        primary_start = source.find(primary_marker)
        assert primary_start != -1
        writer_source = source[primary_start:]

        # Primary block + fallback block both live inside the writer's
        # ``run_with_cypher_param_fallback`` call; assert that both kept
        # RECOVERED in their predicate.
        primary_match = _METRIC_EVENT_OPTIONAL_MATCH_RE.search(writer_source)
        assert primary_match, "_refresh_icmp_jitter_events primary OPTIONAL MATCH shape not found"
        primary_list = primary_match.group("list")
        for required in ("'OPEN'", "'ACK'", "'RECOVERED'"):
            assert required in primary_list, (
                f"_refresh_icmp_jitter_events primary predicate MUST include "
                f"{required}; got list={primary_list!r}"
            )

    def test_icmp_packet_loss_events_predicate_includes_recovered(self):
        """REQ-RECOVERY-002 / fix-484: ICMP-packet-loss RECOVERED eligibility.

        The ``_refresh_icmp_packet_loss_events`` writer MUST keep
        ``'RECOVERED'`` in its existing-event ``status IN [...]`` predicate
        so a subsequent failure reopens the existing ROOT Event rather than
        creating a new ROOT. Locks the 6th predicate site in the regression
        contract.
        """
        source = _read_snmp_worker_source()
        primary_marker = (
            "def _refresh_icmp_packet_loss_events(session, updates, cache=None, lock_db=None):"
        )
        assert (
            primary_marker in source
        ), "_refresh_icmp_packet_loss_events definition not found — regression test is stale"

        primary_start = source.find(primary_marker)
        assert primary_start != -1
        writer_source = source[primary_start:]

        primary_match = _METRIC_EVENT_OPTIONAL_MATCH_RE.search(writer_source)
        assert (
            primary_match
        ), "_refresh_icmp_packet_loss_events primary OPTIONAL MATCH shape not found"
        primary_list = primary_match.group("list")
        for required in ("'OPEN'", "'ACK'", "'RECOVERED'"):
            assert required in primary_list, (
                f"_refresh_icmp_packet_loss_events primary predicate MUST include "
                f"{required}; got list={primary_list!r}"
            )

    def test_predicate_sites_registry_extends_to_six_entries(self):
        """REQ-RECOVERY-002: the test author extended PREDICATE_SITES from
        4 to 6 entries; this test asserts the registry shape so a future
        contributor doesn't accidentally narrow it back to 4.
        """
        assert len(PREDICATE_SITES) == 6, (
            f"PREDICATE_SITES must enumerate six predicate sites "
            f"(collection-failures ×2, ICMP-availability ×2, ICMP-jitter ×1, "
            f"ICMP-packet-loss ×1) — got {len(PREDICATE_SITES)}"
        )
        site_labels = {site[0] for site in PREDICATE_SITES}
        for required in (
            "icmp_jitter_events_predicate_site",
            "icmp_packet_loss_events_predicate_site",
        ):
            assert required in site_labels, f"PREDICATE_SITES must include {required!r} per fix-484"


class TestRecoveryWritersDoNotRegressToOpenAckOnly:
    """REQ-PRUNE-005 contract: the six recovery writers MUST NOT be
    narrowed to ``['OPEN', 'ACK']`` only. Issue #423's narrative said the
    first four were, but HEAD includes RECOVERED. fix-484 extends the
    contract to the two ICMP-writer predicates that followed in #432.
    """

    def test_collection_failures_primary_is_not_open_ack_only(self):
        source = _read_snmp_worker_source()
        all_blocks = _CI_METRIC_OPTIONAL_MATCH_RE.findall(source)
        primary = all_blocks[0]
        normalized = re.sub(r"\s+", "", primary)
        assert normalized != "'OPEN','ACK'", (
            "collection-failures primary regressed to OPEN/ACK-only — "
            "REQ-PRUNE-005 requires RECOVERED to stay in the predicate."
        )

    def test_collection_failures_fallback_is_not_open_ack_only(self):
        source = _read_snmp_worker_source()
        all_blocks = _CI_METRIC_OPTIONAL_MATCH_RE.findall(source)
        fallback = all_blocks[1]
        normalized = re.sub(r"\s+", "", fallback)
        assert normalized != "'OPEN','ACK'", (
            "collection-failures fallback regressed to OPEN/ACK-only — "
            "REQ-PRUNE-005 requires RECOVERED to stay in the predicate."
        )
