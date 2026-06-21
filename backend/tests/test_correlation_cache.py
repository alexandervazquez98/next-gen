"""Unit tests for the per-poll-cycle memo cache in resolve_correlation_fields.

T12 (infra): the resolver accepts an optional `cache` dict so a burst of
dependent events inside the same poll cycle only re-traverses the topology
once per ci_id. The TTL is ~5s (configurable via the `now` callable).

These tests are TDD: a new test asserts cache behaviour, and the existing
resolver implementation already satisfies the contract (it was added in T4
because T6 needed it). The tests document and lock in the contract.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from services.event_service import resolve_correlation_fields, _CORRELATION_CACHE_TTL_S


def _parent_event(event_id="evt-parent-001", parent_ci="ci-parent-001", root="ci-parent-001"):
    return {
        "parent_event_id": event_id,
        "parent_ci_id": parent_ci,
        "root_cause_ci_id": root,
        "correlation_type": "ROOT",
    }


class TestCacheMissCallsLookup:
    """A fresh cache must consult find_open_parent_event."""

    def test_no_cache_calls_lookup(self):
        with patch(
            "repositories.topology_repo.find_open_parent_event",
            return_value=None,
        ) as mock_lookup:
            result = resolve_correlation_fields("ci-x", "CRITICAL")
        assert result["correlation_type"] == "ROOT"
        assert mock_lookup.call_count == 1

    def test_cache_miss_on_first_call_then_consults_lookup(self):
        cache: dict = {}
        with patch(
            "repositories.topology_repo.find_open_parent_event",
            return_value=_parent_event(),
        ) as mock_lookup:
            result = resolve_correlation_fields("ci-x", "CRITICAL", cache=cache)
        assert result["correlation_type"] == "PROPAGATED"
        assert mock_lookup.call_count == 1
        # The result must be written into the cache for next time.
        assert "ci-x" in cache


class TestCacheHitSkipsLookup:
    """Within the TTL, the cache must short-circuit the parent lookup."""

    def test_second_call_within_ttl_skips_lookup(self):
        cache: dict = {}
        # Drive a fake monotonic clock so we can assert TTL behaviour.
        clock = [0.0]

        def _now() -> float:
            return clock[0]

        with patch(
            "repositories.topology_repo.find_open_parent_event",
            return_value=_parent_event(),
        ) as mock_lookup:
            # First call at t=0 — cache miss, hits the lookup.
            resolve_correlation_fields("ci-x", "CRITICAL", cache=cache, now=_now)
            # Second call at t=2 (well within 5s TTL) — cache hit, no lookup.
            clock[0] = 2.0
            resolve_correlation_fields("ci-x", "CRITICAL", cache=cache, now=_now)
            # Third call at t=4.9 (still within 5s TTL).
            clock[0] = 4.9
            resolve_correlation_fields("ci-x", "CRITICAL", cache=cache, now=_now)

        # Only the first call invoked find_open_parent_event.
        assert mock_lookup.call_count == 1, (
            f"expected 1 lookup within TTL, got {mock_lookup.call_count}"
        )

    def test_cache_is_keyed_by_ci_id(self):
        """Different ci_ids must have independent cache entries."""
        cache: dict = {}
        with patch(
            "repositories.topology_repo.find_open_parent_event",
            side_effect=[
                _parent_event(event_id="evt-A"),
                _parent_event(event_id="evt-B"),
            ],
        ) as mock_lookup:
            a_result = resolve_correlation_fields("ci-A", "CRITICAL", cache=cache)
            b_result = resolve_correlation_fields("ci-B", "CRITICAL", cache=cache)
            # A second call for ci-A is a cache hit; ci-B was just looked up.
            a_again = resolve_correlation_fields("ci-A", "CRITICAL", cache=cache)

        assert mock_lookup.call_count == 2  # one per distinct ci_id
        assert a_result["propagated_from"] == "evt-A"
        assert b_result["propagated_from"] == "evt-B"
        assert a_again == a_result  # same dict content (new copy, but same values)


class TestCacheTTLExpiry:
    """Past the TTL, the cache must invalidate and re-consult the lookup."""

    def test_lookup_called_again_after_ttl_expiry(self):
        cache: dict = {}
        clock = [0.0]

        def _now() -> float:
            return clock[0]

        with patch(
            "repositories.topology_repo.find_open_parent_event",
            return_value=_parent_event(),
        ) as mock_lookup:
            resolve_correlation_fields("ci-x", "CRITICAL", cache=cache, now=_now)
            # Move past the TTL.
            clock[0] = _CORRELATION_CACHE_TTL_S + 0.1
            resolve_correlation_fields("ci-x", "CRITICAL", cache=cache, now=_now)

        assert mock_lookup.call_count == 2, (
            f"expected 2 lookups after TTL expiry, got {mock_lookup.call_count}"
        )

    def test_ttl_is_about_5_seconds(self):
        # Lock in the design's stated ~5s per-poll-cycle memoization window.
        assert 4.0 <= _CORRELATION_CACHE_TTL_S <= 6.0, (
            f"cache TTL is {_CORRELATION_CACHE_TTL_S}s; design mandates ~5s per cycle"
        )


class TestCacheMutationIsolation:
    """Cached results must not be mutable across calls (defensive copy)."""

    def test_caller_mutation_does_not_corrupt_cache(self):
        cache: dict = {}
        with patch(
            "repositories.topology_repo.find_open_parent_event",
            return_value=_parent_event(),
        ) as mock_lookup:
            result = resolve_correlation_fields("ci-x", "CRITICAL", cache=cache)
            # Caller mutates the result.
            result["correlation_type"] = "TAMPERED"
            result["propagated_from"] = "evil"
            # Second call returns the cached value, untouched by the mutation.
            result2 = resolve_correlation_fields("ci-x", "CRITICAL", cache=cache)

        assert result2["correlation_type"] == "PROPAGATED"
        assert result2["propagated_from"] == "evt-parent-001"


class TestNoCacheParameterDisablesMemoization:
    """When `cache` is None, every call must hit the lookup (no memoization)."""

    def test_no_cache_two_calls_two_lookups(self):
        with patch(
            "repositories.topology_repo.find_open_parent_event",
            return_value=None,
        ) as mock_lookup:
            resolve_correlation_fields("ci-x", "CRITICAL")
            resolve_correlation_fields("ci-x", "CRITICAL")
        assert mock_lookup.call_count == 2
