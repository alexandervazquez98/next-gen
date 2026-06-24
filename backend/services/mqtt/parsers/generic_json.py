"""Heuristic JSON parser for ad-hoc MQTT devices (PR4).

:class:`GenericJsonParser` is the catch-all parser. It registers the ``#``
fallback topic pattern so any message that no specific parser claims gets
routed here. The parser:

  * Decodes the payload as UTF-8 JSON.
  * Walks the JSON tree, turning every numeric leaf (other than ``bool`` and
    ``None``) into a :class:`MetricReading` whose name is the dotted path
    through the document (e.g. ``sensors.0.value``).
  * Caps traversal at :data:`MAX_DEPTH` (8) and metric collection at
    :data:`MAX_METRICS` (256) per message — runaway payloads must NOT bloat
    Neo4j.
  * Produces exactly one :class:`Reading` per message, with the device id
    taken from the payload's ``device_id`` field when present, otherwise a
    UUID4 is generated.
  * Raises :class:`ParseError` on malformed JSON or invalid UTF-8 so the
    subscriber ACKs and drops the message — redelivery would never recover.

The parser is deliberately "dumb": it does not validate shapes, units, or
semantics. It treats every numeric leaf as a scalar metric and lets the
heuristic absorb any future ad-hoc device without code changes. The price is
that some payloads will produce surprising metric names (e.g. an array of
objects with ``name``/``value`` keys becomes ``items.0.value`` instead of
``items.0.name``); that's accepted by design — PR4 explicitly trades
sophistication for zero-config reach (Q4: validation off).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from services.mqtt.parsers.base import MetricReading, ParseError, Reading

logger = logging.getLogger(__name__)

__all__ = ["GenericJsonParser", "MAX_DEPTH", "MAX_METRICS"]


# Hard caps per design §2.3. Depth 8 keeps dotted-path names short enough for
# Neo4j property indexes; 256 metrics caps any single message's write volume
# so a misbehaving device cannot starve the persistence path.
MAX_DEPTH = 8
MAX_METRICS = 256


class GenericJsonParser:
    """Heuristic JSON parser — produces one :class:`Reading` per message.

    The parser is the registry's ``#`` fallback. When a topic matches no
    specific parser, the :class:`~services.mqtt.topic_router.TopicRouter`
    hands the payload to this parser so the message still gets persisted.

    Attributes:
        name: Parser identity (``"generic_json"``).
        topic_patterns: ``("#",)`` — claims every topic; the router uses it as
            the fallback when no specific pattern matches.
    """

    name = "generic_json"
    topic_patterns: tuple[str, ...] = ("#",)

    def parse(self, topic: str, payload: bytes) -> list[Reading]:
        """Decode ``payload`` as JSON and walk the tree for numeric leaves.

        Args:
            topic: The MQTT topic the message arrived on. Preserved in
                :attr:`Reading.source_topic` for logging/debug.
            payload: UTF-8 encoded JSON bytes.

        Returns:
            A single-element list containing one :class:`Reading`. The list
            shape matches the :class:`Parser` protocol even though this parser
            never produces multiple readings per message.

        Raises:
            ParseError: The payload is not valid UTF-8 JSON. The subscriber
                catches this and ACKs the message — redelivery would never
                recover.
        """
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ParseError(f"Invalid UTF-8 payload: {e}") from e

        try:
            data: Any = json.loads(text)
        except json.JSONDecodeError as e:
            raise ParseError(f"Invalid JSON payload: {e}") from e

        # Identity: payload `device_id` wins; otherwise generate a UUID4 so
        # the message still lands somewhere (per Q1 — payload > topic-derived,
        # and for ad-hoc devices the topic carries no stable identity).
        payload_device_id: str | None = None
        timestamp: datetime = datetime.now(UTC)
        original_keys: list[str] = []
        if isinstance(data, dict):
            raw_id = data.get("device_id")
            if isinstance(raw_id, str) and raw_id:
                payload_device_id = raw_id
            raw_ts = data.get("timestamp")
            if isinstance(raw_ts, str):
                # Use the parser-side parser for the few shapes we see in
                # the wild; fall back to "now" on any failure (validation
                # is OFF by design — better a wrong ts than a ParseError).
                parsed_ts = _parse_iso_timestamp(raw_ts)
                if parsed_ts is not None:
                    timestamp = parsed_ts
            original_keys = list(data.keys())

        device_id = payload_device_id or str(uuid.uuid4())

        metrics: list[MetricReading] = []
        # Walk the tree. We pass `data` (not just dicts) so a top-level array
        # or scalar still produces a sensible Reading with whatever leaves
        # are reachable.
        _traverse(data, "", metrics, depth=0)

        return [
            Reading(
                device_id=device_id,
                location_id=None,
                timestamp=timestamp,
                metrics=tuple(metrics),
                source_topic=topic,
                parser_name=self.name,
                extra={
                    "_generic": True,
                    "_original_keys": original_keys,
                },
            )
        ]


# ── Internal helpers ────────────────────────────────────────────────────────


def _traverse(
    node: Any,
    path: str,
    metrics: list[MetricReading],
    depth: int,
) -> None:
    """Walk a JSON tree, appending a :class:`MetricReading` per numeric leaf.

    Stops when ``depth > MAX_DEPTH`` (the cap is exclusive) or when the
    ``metrics`` list is already at :data:`MAX_METRICS`. ``bool`` is excluded
    because Python treats it as a subclass of ``int`` — without the explicit
    ``isinstance(..., bool)`` check, ``True`` would become ``MetricReading(
    name="x", value=1)``.

    Args:
        node: The current JSON value (dict, list, scalar, or None).
        path: The dotted-path prefix accumulated so far. The first call uses
            ``""`` so the top-level key is written without a leading dot.
        metrics: Accumulator list — appended in place when a numeric leaf is
            found.
        depth: Current recursion depth (0 = root).
    """
    if depth > MAX_DEPTH:
        # Past the cap — log once and stop. Logging at WARNING so operators
        # notice abusive payload shapes.
        if depth == MAX_DEPTH + 1:
            logger.warning(
                "GenericJsonParser stopped at depth %d (cap=%d) — payload too deep",
                depth,
                MAX_DEPTH,
            )
        return
    # Cap check runs BEFORE recursing/appending so the warning fires on the
    # call that would exceed the cap, not on the call that already matched it.
    if len(metrics) >= MAX_METRICS:
        logger.warning(
            "GenericJsonParser stopped at %d metrics (cap=%d) — payload too large",
            MAX_METRICS,
            MAX_METRICS,
        )
        return

    if isinstance(node, dict):
        for key, value in node.items():
            if len(metrics) >= MAX_METRICS:
                logger.warning(
                    "GenericJsonParser stopped at %d metrics (cap=%d) — payload too large",
                    MAX_METRICS,
                    MAX_METRICS,
                )
                return
            child_path = f"{path}.{key}" if path else str(key)
            _traverse(value, child_path, metrics, depth + 1)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if len(metrics) >= MAX_METRICS:
                logger.warning(
                    "GenericJsonParser stopped at %d metrics (cap=%d) — payload too large",
                    MAX_METRICS,
                    MAX_METRICS,
                )
                return
            child_path = f"{path}.{index}"
            _traverse(value, child_path, metrics, depth + 1)
    elif isinstance(node, bool):
        # Explicit branch — bool IS an int subclass, but we treat it as
        # non-numeric per Q4 (validation off, no bool-as-int surprises).
        return
    elif isinstance(node, (int, float)):
        metrics.append(
            MetricReading(
                name=path or "value",
                value=node,
                unit=None,
                tags={},
            )
        )


def _parse_iso_timestamp(raw: str) -> datetime | None:
    """Best-effort ISO-8601 parse; return ``None`` on any failure.

    Generic JSON validation is OFF (Q4), so a malformed timestamp must NOT
    raise — falling back to ``datetime.now(UTC)`` is the safer failure mode
    (the message still lands, with a slightly wrong timestamp).
    """
    try:
        # ``datetime.fromisoformat`` handles ``2026-06-23T12:00:00`` and
        # ``2026-06-23T12:00:00+00:00`` in Python 3.11+. The trailing ``Z``
        # form requires the ``Z`` -> ``+00:00`` rewrite.
        normalized = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
        parsed = datetime.fromisoformat(normalized)
    except (TypeError, ValueError):
        return None
    # Treat naive datetimes as UTC. Timestamps without a tz are common in
    # JSON payloads; we have no way to ask the publisher, so assume UTC.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
