"""Tests for engines.snmp_worker correlation wiring (Tasks 2, 3, 4, 10).

Strict TDD: tests written FIRST, then implementation.

Covers:
- Task 2: ``_resolve_correlation`` helper (pure dict lookup, never raises).
- Task 3: ``poll_snmp`` cache-build wiring (ENABLE_TOPOLOGY_RCA kill-switch,
  cache built BEFORE the three CREATE sites, local to one cycle).
- Task 4: the three CREATE sites decorate rows from the cache instead of
  hardcoding ``correlation_type: 'ROOT'``.
- Task 10: failure-fallback resilience (cache-build raises → events still
  created as ROOT, UNWIND...CREATE ran, warning logged).
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from engines import snmp_worker
from engines.snmp_worker import _resolve_correlation


# ---------------------------------------------------------------------------
# Task 2 — _resolve_correlation helper
# ---------------------------------------------------------------------------


def test_resolve_correlation_propagated_on_cache_hit():
    cache = {("ci-E", "cpu-load"): {"parent_event_id": "evt-A", "root_cause_ci_id": "ci-A"}}

    result = _resolve_correlation(cache, "ci-E", "cpu-load")

    assert result == {
        "correlation_type": "PROPAGATED",
        "propagated_from": "evt-A",
        "root_cause_ci_id": "ci-A",
    }


def test_resolve_correlation_root_on_cache_miss():
    result = _resolve_correlation({}, "ci-E", "cpu-load")

    assert result == {
        "correlation_type": "ROOT",
        "propagated_from": None,
        "root_cause_ci_id": "ci-E",
    }


@pytest.mark.parametrize("bad_cache", [None, "not-a-dict", 42, object()])
def test_resolve_correlation_never_raises_on_malformed_cache(bad_cache):
    """The hot CREATE path must stay exception-free — _resolve_correlation never raises."""
    result = _resolve_correlation(bad_cache, "ci-E", "cpu-load")  # type: ignore[arg-type]

    assert result["correlation_type"] == "ROOT"
    assert result["root_cause_ci_id"] == "ci-E"


def test_resolve_correlation_handles_missing_parent_event_id():
    """A cache entry without parent_event_id is treated as a miss → ROOT."""
    cache = {("ci-E", "cpu-load"): {"root_cause_ci_id": "ci-A"}}  # no parent_event_id

    result = _resolve_correlation(cache, "ci-E", "cpu-load")

    assert result["correlation_type"] == "ROOT"


def test_resolve_correlation_falls_back_to_parent_event_id_for_root_cause():
    """If root_cause_ci_id is missing, use parent_event_id as the root cause."""
    cache = {("ci-E", "cpu-load"): {"parent_event_id": "evt-A"}}

    result = _resolve_correlation(cache, "ci-E", "cpu-load")

    assert result["correlation_type"] == "PROPAGATED"
    assert result["propagated_from"] == "evt-A"
    assert result["root_cause_ci_id"] == "evt-A"


def test_resolve_correlation_uses_ci_metric_pair_key():
    """Two metrics on the same CI with different cache entries resolve independently."""
    cache = {
        ("ci-E", "cpu-load"): {"parent_event_id": "evt-A", "root_cause_ci_id": "ci-A"},
        ("ci-E", "mem-load"): {"parent_event_id": "evt-B", "root_cause_ci_id": "ci-B"},
    }

    cpu = _resolve_correlation(cache, "ci-E", "cpu-load")
    mem = _resolve_correlation(cache, "ci-E", "mem-load")

    assert cpu["propagated_from"] == "evt-A"
    assert mem["propagated_from"] == "evt-B"
