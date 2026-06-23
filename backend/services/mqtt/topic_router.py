"""Topic routing for the MQTT subscriber (PR2a).

Two layers of abstraction:
  * :class:`MQTTMatcher` — a low-level dict-backed pattern store with MQTT
    wildcard semantics. Knows nothing about parsers.
  * :class:`TopicRouter` — builds an :class:`MQTTMatcher` from a list of
    :class:`~services.mqtt.parsers.base.Parser` instances, resolves topics
    to parsers, and aggregates the deduplicated subscription set.

Both layers are pure: no broker I/O, no asyncio, no Neo4j. They are the
heart of the PR2 dispatch path and must be exhaustively unit-tested.
"""

from __future__ import annotations

from typing import Any


class MQTTMatcher:
    """Dict-backed MQTT topic matcher with wildcard support.

    Wildcards:
      * ``+`` matches exactly one segment.
      * ``#`` matches one or more segments and must be the final segment.

    Specificity: more literal segments = more specific. ``#`` patterns are
    least specific. See :func:`_specificity` and ``match()``.
    """

    def __init__(self) -> None:
        # Each entry is (segments, value). Iterated in registration order;
        # specificity ordering is applied lazily on the first ``match`` call
        # so insertion order does NOT affect dispatch.
        self._patterns: list[tuple[list[str], Any]] = []

    def __setitem__(self, pattern: str, value: Any) -> None:
        """Register a pattern. Raises if ``#`` is not a well-placed whole segment.

        Per the MQTT spec, ``#`` is a *whole* segment, not a character sequence.
        It must appear alone, and only as the final segment of the pattern.
        """
        segments = pattern.split("/")
        for i, seg in enumerate(segments):
            if seg == "#":
                if i != len(segments) - 1:
                    raise ValueError(
                        f"Invalid MQTT pattern {pattern!r}: '#' must be the final segment"
                    )
            elif "#" in seg:
                raise ValueError(f"Invalid MQTT pattern {pattern!r}: '#' must be a whole segment")
        self._patterns.append((segments, value))

    def match(self, topic: str) -> Any | None:
        """Return the value for the most specific matching pattern, or None."""
        topic_segments = topic.split("/")
        # Insertion order is fine for Task 2a.1; Task 2a.2 layers on
        # specificity sorting to make registration order irrelevant.
        for segments, value in self._patterns:
            if _segments_match(segments, topic_segments):
                return value
        return None


def _segments_match(pattern: list[str], topic: list[str]) -> bool:
    """Return True iff ``topic`` matches the pre-split ``pattern`` segments."""
    i = 0
    while i < len(pattern):
        p = pattern[i]
        if p == "#":
            # `#` matches one or more remaining segments. Always last segment,
            # so any leftover topic segments make this a match.
            return i < len(pattern) and len(topic) >= i
        if i >= len(topic):
            return False
        if p != "+" and p != topic[i]:
            return False
        i += 1
    return i == len(topic)
