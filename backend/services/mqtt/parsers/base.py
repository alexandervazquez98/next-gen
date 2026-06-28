"""Canonical parser protocol and Reading dataclasses for the MQTT subscriber.

The subscriber loop dispatches incoming messages to a registered :class:`Parser`
implementation. Each parser owns:
  * the MQTT topic patterns it consumes (with `+` and `#` wildcards),
  * the payload encoding/framing (UTF-8, JSON, etc.),
  * the domain semantics (register addresses for BLIIoT, dotted paths for generic JSON, etc.).

All parsers emit a list of :class:`Reading` objects — a frozen, transport-neutral
representation that crosses the parser → persistence boundary safely.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class MetricReading:
    """A single (name, value, unit) reading produced by a parser.

    Attributes:
        name: Stable metric identifier (e.g. ``"temperature"``, ``"register_0"``).
        value: Observed value. May be numeric, boolean, or string.
        unit: Optional unit string (e.g. ``"°C"``, ``"0.01°C"``).
        tags: Optional key-value labels for filtering/grouping in storage.
    """

    name: str
    value: float | int | bool | str
    unit: str | None = None
    tags: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Reading:
    """A parser's output for a single MQTT message.

    Attributes:
        device_id: Stable device identifier (parser-provided, payload-precedence per
            design Q1 — payload > topic-derived).
        location_id: Optional logical location/grouping identifier.
        timestamp: When the reading was observed. Defaults to ``datetime.now(UTC)``
            when the payload omits it.
        metrics: One :class:`MetricReading` per observation in the payload.
        source_topic: The original MQTT topic — preserved for logging and debug.
        parser_name: The parser's :attr:`Parser.name` — used for routing and metrics.
        extra: Parser-specific metadata (e.g. ``digital_inputs``, ``relays``). Capped
            at 4 KB by the subscriber loop per design Q2.
    """

    device_id: str
    location_id: str | None
    timestamp: datetime
    metrics: tuple[MetricReading, ...]
    source_topic: str
    parser_name: str
    extra: Mapping[str, Any] = field(default_factory=dict)


class ParseError(Exception):
    """Unrecoverable payload or topic parse failure.

    The subscriber loop catches :class:`ParseError` and ACKs the message — the
    payload is malformed and redelivery would loop forever. Transient backend
    failures are NOT parse errors and must surface as different exceptions.
    """


@runtime_checkable
class Parser(Protocol):
    """Pluggable MQTT payload parser.

    Implementations declare the topic patterns they own (:attr:`topic_patterns`)
    and a :meth:`parse` method that decodes the raw bytes into canonical
    :class:`Reading` objects. The :class:`TopicRouter` (PR2) uses
    :attr:`topic_patterns` for subscription aggregation and dispatch.
    """

    name: str
    topic_patterns: tuple[str, ...]

    def parse(self, topic: str, payload: bytes) -> list[Reading]:
        """Decode a raw MQTT message into canonical readings.

        Args:
            topic: The full MQTT topic the message arrived on.
            payload: The raw bytes from the broker — parsers own encoding handling.

        Returns:
            A list of :class:`Reading` objects. Empty list is valid (e.g. heartbeat).

        Raises:
            ParseError: The payload or topic is malformed and will never succeed on
                redelivery. Subscriber ACKs and drops.
        """
