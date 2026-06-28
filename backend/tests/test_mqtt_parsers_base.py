"""Unit tests for the MQTT parser protocol and canonical Reading/MetricReading dataclasses.

Mark: unit
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import pytest

pytestmark = [pytest.mark.unit]


class TestParserProtocol:
    """Tests for the runtime-checkable Parser protocol."""

    def test_parser_protocol_runtime_check(self) -> None:
        """A class with name/topic_patterns/parse() satisfies isinstance(_, Parser)."""
        from services.mqtt.parsers.base import Parser

        class _GoodParser:
            name = "good"
            topic_patterns = ("rtu/+/+/telemetry",)
            events: list[tuple[str, bytes]] = []

            def parse(self, topic: str, payload: bytes) -> list[Any]:
                self.events.append((topic, payload))
                return []

        assert isinstance(_GoodParser(), Parser)

    def test_parser_protocol_missing_parse_fails(self) -> None:
        """A class missing the parse() method does NOT satisfy isinstance(_, Parser)."""
        from services.mqtt.parsers.base import Parser

        class _BadParser:
            name = "bad"
            topic_patterns: tuple[str, ...] = ()

        assert not isinstance(_BadParser(), Parser)

    def test_parse_error_is_exception(self) -> None:
        """ParseError is a subclass of Exception so callers can `except Exception`."""
        from services.mqtt.parsers.base import ParseError

        assert issubclass(ParseError, Exception)
        with pytest.raises(ParseError, match="boom"):
            raise ParseError("boom")


class TestMetricReadingFrozen:
    """MetricReading must be frozen — parsers can share Reading objects safely."""

    def test_metric_reading_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        from services.mqtt.parsers.base import MetricReading

        mr = MetricReading(name="temperature", value=23.5, unit="°C")
        with pytest.raises(FrozenInstanceError):
            mr.name = "humidity"  # type: ignore[misc]

    def test_metric_reading_default_unit_and_tags(self) -> None:
        """Default unit=None and tags={} are usable without explicit args."""
        from services.mqtt.parsers.base import MetricReading

        mr = MetricReading(name="uptime", value=42)
        assert mr.unit is None
        assert mr.tags == {}

    def test_metric_reading_supports_tag_dict(self) -> None:
        """Custom tags dict is preserved."""
        from services.mqtt.parsers.base import MetricReading

        tags: Mapping[str, str] = {"register_addr": "0", "unit_kind": "raw"}
        mr = MetricReading(name="temperature", value=23.5, unit="°C", tags=tags)
        assert mr.tags == tags


class TestReadingFrozen:
    """Reading must be frozen — it crosses the parser → persistence boundary."""

    def test_reading_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        from services.mqtt.parsers.base import MetricReading, Reading

        ts = datetime(2026, 5, 4, 12, 0, 0)
        reading = Reading(
            device_id="rtu-1",
            location_id="loc-1",
            timestamp=ts,
            metrics=(MetricReading(name="t", value=1.0),),
            source_topic="rtu/loc-1/rtu-1/telemetry",
            parser_name="bliiot_s475e",
        )
        with pytest.raises(FrozenInstanceError):
            reading.device_id = "spoofed"  # type: ignore[misc]

    def test_reading_default_extra(self) -> None:
        """Default extra={} is a fresh dict, not a mutable shared one."""
        from services.mqtt.parsers.base import MetricReading, Reading

        r1 = Reading(
            device_id="d1",
            location_id=None,
            timestamp=datetime(2026, 1, 1),
            metrics=(MetricReading(name="x", value=0),),
            source_topic="t/1",
            parser_name="p",
        )
        r2 = Reading(
            device_id="d2",
            location_id=None,
            timestamp=datetime(2026, 1, 1),
            metrics=(MetricReading(name="x", value=0),),
            source_topic="t/2",
            parser_name="p",
        )
        # Default factories must not share state
        assert r1.extra == {}
        assert r2.extra == {}
        assert r1.extra is not r2.extra
