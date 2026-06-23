"""Tests for :class:`MQTTMatcher` and :class:`TopicRouter` (PR2a).

These tests are pure: no broker I/O, no asyncio, no Neo4j. The router is
the heart of the PR2 dispatch path — every subscriber test depends on it.
"""

from __future__ import annotations

import pytest

from services.mqtt.topic_router import MQTTMatcher


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
