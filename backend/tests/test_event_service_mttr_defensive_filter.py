"""Strict-TDD regression test for the MTTR defensive filter.

PR #3 of chore-events-backfill-stuck-icmp-recovery-486: the backfill
introduces a new ``event_type = 'legacy-no-relevant'`` value (via the
cascade). The ``get_availability_report`` query already excludes events
with ``event_type = 'AVAILABILITY'``, which means jitter/packet-loss
THRESHOLD_BREACH rows never reach MTTR today. However, the new
``legacy-no-relevant`` rows MUST be excluded explicitly via:

    AND e.event_type <> 'legacy-no-relevant'

This defensive clause:

1. Documents the intended exclusion in code (not only in the spec).
2. Guards against future MTTR scope expansion (e.g. someone removing the
   ``event_type = 'AVAILABILITY'`` filter or adding THRESHOLD_BREACH rows).

If you remove this clause from ``event_service.py``, this test fails.
"""

from __future__ import annotations

import re
from pathlib import Path

EVENT_SERVICE_PATH = Path(__file__).resolve().parents[1] / "services" / "event_service.py"


def _read_event_service_source() -> str:
    return EVENT_SERVICE_PATH.read_text(encoding="utf-8")


def test_get_availability_report_excludes_legacy_no_relevant():
    """The MTTR query MUST contain ``event_type <> 'legacy-no-relevant'``."""
    source = _read_event_service_source()

    # The clause is in the WHERE block of the recovered_result query inside
    # get_availability_report. We assert the substring is present anywhere
    # in the file under services/event_service.py to keep the test focused
    # on the contract, not on indentation/formatting drift.
    assert "event_type <> 'legacy-no-relevant'" in source, (
        "get_availability_report must include the defensive clause "
        "AND e.event_type <> 'legacy-no-relevant' to exclude backfilled "
        "legacy-no-relevant Event rows from MTTR aggregation. See "
        "openspec/changes/chore-events-backfill-stuck-icmp-recovery-486/"
        "specs/event-prune-recovery-lifecycle/spec.md for the contract."
    )


def test_get_availability_report_clause_is_within_availabilty_window_query():
    """The defensive clause must be co-located with the MTTR window query.

    A loose grep could match a comment or a docstring. We assert the clause
    appears within 200 lines of the ``get_availability_report`` definition.
    """
    source = _read_event_service_source()

    fn_match = re.search(
        r"def\s+get_availability_report\s*\(",
        source,
    )
    assert fn_match, "get_availability_report must be defined in event_service.py"
    fn_start = fn_match.start()

    # Heuristic window: 200 lines from the function definition. This keeps
    # the assertion local to the MTTR query without coupling to exact line
    # numbers (which drift across edits).
    window = source[fn_start : fn_start + 200 * 80]  # ~200 lines @ avg 80 chars

    assert "event_type <> 'legacy-no-relevant'" in window, (
        "The defensive clause must be co-located with the MTTR window "
        "query in get_availability_report, not in a distant function."
    )
