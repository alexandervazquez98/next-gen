"""Tests for :class:`MQTTMatcher` and :class:`TopicRouter` (PR2a).

These tests are pure: no broker I/O, no asyncio, no Neo4j. The router is
the heart of the PR2 dispatch path — every subscriber test depends on it.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from services.mqtt.topic_router import MQTTMatcher, TopicRouter

# ── Fixtures ────────────────────────────────────────────────────────────────


@dataclass
class _StubParser:
    """Minimal Parser-shaped object for router tests."""

    name: str
    topic_patterns: tuple[str, ...] = ()


# ── Task 2a.1: MQTTMatcher with MQTT wildcard semantics ─────────────────────


class TestMqttMatcherWildcards:
    def test_mqtt_matcher_single_plus(self) -> None:
        matcher: MQTTMatcher = MQTTMatcher()
        matcher["foo/+/bar"] = "match"
        assert matcher.match("foo/x/bar") == "match"
        # `+` is exactly one segment — NOT a multi-segment wildcard.
        assert matcher.match("foo/x/y/bar") is None

    def test_mqtt_matcher_hash_matches_rest(self) -> None:
        matcher: MQTTMatcher = MQTTMatcher()
        matcher["foo/#"] = "hash"
        assert matcher.match("foo/x") == "hash"
        assert matcher.match("foo/x/y") == "hash"
        assert matcher.match("foo/x/y/z") == "hash"

    def test_mqtt_matcher_exact_match(self) -> None:
        matcher: MQTTMatcher = MQTTMatcher()
        matcher["foo/bar"] = "exact"
        assert matcher.match("foo/bar") == "exact"
        # Any other topic — including subsets or supersets — does not match.
        assert matcher.match("foo") is None
        assert matcher.match("foo/bar/baz") is None
        assert matcher.match("baz/foo/bar") is None

    def test_mqtt_matcher_no_match_returns_none(self) -> None:
        matcher: MQTTMatcher = MQTTMatcher()
        matcher["foo/+/bar"] = "match"
        assert matcher.match("baz/x/bar") is None
        # No patterns registered.
        empty: MQTTMatcher = MQTTMatcher()
        assert empty.match("anything") is None

    def test_mqtt_matcher_hash_must_be_last_raises(self) -> None:
        matcher: MQTTMatcher = MQTTMatcher()
        with pytest.raises(ValueError):
            matcher["foo/#/bar"] = "bad"  # '#' not in final position
        # `#` as a whole final segment IS valid.
        matcher["foo/#"] = "ok"
        # `#` embedded inside another segment is invalid (whole-segment rule).
        with pytest.raises(ValueError):
            matcher["foo/+/bar#"] = "bad-trailing"


# ── Task 2a.2: Specificity scoring ─────────────────────────────────────────


class TestSpecificityScoring:
    def test_specificity_more_segments_wins(self) -> None:
        matcher: MQTTMatcher = MQTTMatcher()
        # Two valid patterns, no `#`. The one with more literals must win.
        matcher["foo/+/bar"] = "two_literals"
        matcher["foo/+/+/bar"] = "three_literals"
        assert matcher.match("foo/x/y/bar") == "three_literals"

    def test_specificity_hash_is_least(self) -> None:
        matcher: MQTTMatcher = MQTTMatcher()
        # A pattern with `#` is LESS specific than a pattern with no `#`,
        # even when the no-`#` pattern has FEWER literals.
        matcher["foo/#"] = "hash"
        matcher["foo/+/bar"] = "plus_bar"
        # `foo/x/bar` matches both; `foo/+/bar` (no `#`) must win.
        assert matcher.match("foo/x/bar") == "plus_bar"

    def test_specificity_stable_for_equivalent_patterns(self) -> None:
        matcher: MQTTMatcher = MQTTMatcher()
        matcher["a/b/c"] = "first"
        matcher["a/b/c"] = "second"  # exact duplicate — last write wins
        # Two identical patterns have the same score — the resulting value
        # depends on iteration order, but it must be a non-None match.
        assert matcher.match("a/b/c") in ("first", "second")

    def test_mqtt_matcher_specificity_wins(self) -> None:
        """Registration order does NOT matter — specificity does."""
        # Register the fallback FIRST, then the more specific pattern.
        matcher: MQTTMatcher = MQTTMatcher()
        matcher["foo/#"] = "fallback"
        matcher["foo/+/bar"] = "specific"
        assert matcher.match("foo/x/bar") == "specific"


# ── Task 2a.3: TopicRouter.resolve + subscribe_patterns ─────────────────────


class TestTopicRouterResolve:
    def test_router_resolves_most_specific_parser(self) -> None:
        bliiot = _StubParser(name="bliiot", topic_patterns=("rtu/+/+/telemetry",))
        generic = _StubParser(name="generic", topic_patterns=("#",))
        router = TopicRouter([bliiot, generic])
        assert router.resolve("rtu/loc/rtu/telemetry") is bliiot

    def test_router_fallback_to_hash_parser(self) -> None:
        bliiot = _StubParser(name="bliiot", topic_patterns=("rtu/+/+/telemetry",))
        generic = _StubParser(name="generic", topic_patterns=("#",))
        router = TopicRouter([bliiot, generic])
        # No specific match — the `#` fallback parser wins.
        assert router.resolve("tenants/acme/sensors/123") is generic

    def test_router_no_match_returns_none(self) -> None:
        # No `#` fallback registered.
        bliiot = _StubParser(name="bliiot", topic_patterns=("rtu/+/+/telemetry",))
        router = TopicRouter([bliiot])
        assert router.resolve("tenants/acme/sensors/123") is None

    def test_subscribe_patterns_dedupes(self) -> None:
        a = _StubParser(name="a", topic_patterns=("foo/+", "bar/+"))
        b = _StubParser(name="b", topic_patterns=("foo/+", "baz/#"))  # foo/+ shared
        router = TopicRouter([a, b])
        patterns = router.subscribe_patterns()
        # `foo/+` appears in both parsers — must be deduped.
        assert patterns.count("foo/+") == 1
        # All declared patterns present.
        assert set(patterns) == {"foo/+", "bar/+", "baz/#"}
        # Sorted for determinism.
        assert patterns == sorted(patterns)

    def test_subscribe_patterns_includes_fallback(self) -> None:
        bliiot = _StubParser(name="bliiot", topic_patterns=("rtu/+/+/telemetry",))
        generic = _StubParser(name="generic", topic_patterns=("#",))
        router = TopicRouter([bliiot, generic])
        assert "#" in router.subscribe_patterns()
