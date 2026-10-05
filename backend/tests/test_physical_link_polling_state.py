"""Tests for the PhysicalLink polling status derivation service — feat-443 (PR2, slice 4/4).

The service derives ``status`` (UP / DOWN / UNKNOWN / PLANNED) from
``metric_values`` freshness and completeness. Pure function — no Neo4j
or polling pipeline required.

TDD coverage (PR2): T13, T14, T15, T16, T17.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("FEATURE_CMDB_PHYSICAL_LINKS_ENABLED", "true")


def _now() -> datetime:
    return datetime(2026, 10, 3, 20, 54, 37, tzinfo=UTC)


def _row(seconds_ago: int) -> dict:
    return {"time": _now() - timedelta(seconds=seconds_ago), "value": 1.0}


def _samples(ci_a, ci_b) -> dict:
    return {
        "ci-A": {"ifInOctets": ci_a, "ifOutOctets": []},
        "ci-B": {"ifInOctets": ci_b, "ifOutOctets": []},
    }


def _link(capacity_gbps=10.0, status="UP") -> dict:
    return {
        "id": "pl-1",
        "endpoints": ["ci-A", "ci-B"],
        "status": status,
        "capacity_gbps": capacity_gbps,
    }


def _derive(link, samples):
    from services.physical_link_polling_state import derive_status

    return derive_status(link, samples, now=_now(), stale_after_seconds=1800)


# T13: any fresh endpoint → UP


def test_t13_both_endpoints_fresh_returns_up():
    assert _derive(_link(), _samples([_row(10)], [_row(5)])) == "UP"


# T14: stale endpoint(s) with no fresh endpoint → UNKNOWN


def test_t14_one_stale_one_silent_returns_unknown():
    samples = _samples([_row(1900)], [])  # ci-A stale (>1800s), ci-B silent
    assert _derive(_link(), samples) == "UNKNOWN"


# T15: every endpoint's most-recent sample older than threshold → DOWN


def test_t15_all_endpoints_stale_returns_down():
    samples = _samples([_row(1900)], [_row(1900)])
    assert _derive(_link(), samples) == "DOWN"


# T16: no samples for either endpoint → UNKNOWN (NOT DOWN)


def test_t16_no_samples_returns_unknown():
    samples = _samples([], [])
    assert _derive(_link(), samples) == "UNKNOWN"


def test_t16_no_samples_does_not_collapse_to_down():
    assert _derive(_link(), _samples([], [])) != "DOWN"


# T17: PLANNED (capacity_gbps=None) is excluded from derivation


def test_t17_planned_link_with_null_capacity_returns_planned():
    link = _link(capacity_gbps=None, status="PLANNED")
    # Even with all-fresh samples, PLANNED wins — utilization is undefined.
    samples = _samples([_row(10)], [_row(5)])
    assert _derive(link, samples) == "PLANNED"
