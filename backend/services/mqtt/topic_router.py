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

from typing import TYPE_CHECKING, Any

from services.mqtt.parsers import all_parsers

if TYPE_CHECKING:
    from services.mqtt.parsers.base import Parser


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
        """Return the value for the most specific matching pattern, or None.

        Specificity (descending):
          1. Higher literal-segment count wins.
          2. Ties break toward no-``#`` patterns (no-``#`` is more specific).
        """
        topic_segments = topic.split("/")
        # Sort by specificity on every match — O(n log n) per call, fine for
        # the ≤20-pattern budget per design §11. The sort is stable so
        # equivalent patterns preserve insertion order.
        sorted_patterns = sorted(
            self._patterns,
            key=lambda item: _specificity(item[0]),
            reverse=True,
        )
        for segments, value in sorted_patterns:
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


def _specificity(segments: list[str]) -> tuple[int, int]:
    """Return ``(literal_segment_count, 0 if '#' in pattern else 1)``.

    Higher = more specific. Sort descending.

    Examples:
      * ``foo/+/bar`` -> ``(2, 1)`` — 2 literals, no ``#``.
      * ``foo/+/+/bar`` -> ``(3, 1)`` — 3 literals, no ``#``.
      * ``foo/#`` -> ``(0, 0)`` — 0 literals, has ``#``.

    The second element (``0`` for ``#``, ``1`` for non-``#``) breaks ties
    in the FIRST element: no-``#`` patterns are always more specific than
    ``#`` patterns of the same literal count.
    """
    literal_count = sum(1 for seg in segments if seg not in ("+", "#"))
    no_hash = 0 if "#" in segments else 1
    return (literal_count, no_hash)


class TopicRouter:
    """Resolves a topic to a parser, evaluating patterns in specificity order.

    On construction, the router registers every pattern declared by each
    parser. Patterns ending in ``/#`` (including the catch-all ``#``) are
    remembered as fallback candidates — used when no specific pattern
    matches the topic.
    """

    def __init__(self, parsers: list[Parser] | None = None) -> None:
        # Use the registered parsers by default; the parameter is for tests.
        self._parsers: list[Parser] = list(parsers if parsers is not None else all_parsers())
        self._matcher: MQTTMatcher = MQTTMatcher()
        self._fallback_parser: Parser | None = None
        for parser in self._parsers:
            for pattern in parser.topic_patterns:
                if pattern.endswith("/#"):
                    self._fallback_parser = parser
                self._matcher[pattern] = parser

    def resolve(self, topic: str) -> Parser | None:
        """Return the matching parser, or the ``#`` fallback parser, or None.

        Specificity (via :class:`MQTTMatcher`) determines which parser
        wins when multiple patterns match. If no specific pattern matches
        but a ``#`` parser was registered, that fallback parser is returned.
        """
        result = self._matcher.match(topic)
        if result is not None:
            return result  # type: ignore[no-any-return]
        return self._fallback_parser

    def subscribe_patterns(self) -> list[str]:
        """Return the deduplicated union of all parser patterns (sorted)."""
        seen: set[str] = set()
        for parser in self._parsers:
            for pattern in parser.topic_patterns:
                seen.add(pattern)
        return sorted(seen)
