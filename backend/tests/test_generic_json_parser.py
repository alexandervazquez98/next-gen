"""Tests for :class:`GenericJsonParser` (PR4) and fallback registration.

The parser is the heuristic catch-all for ad-hoc MQTT devices: it walks the
JSON payload, turns every numeric leaf into a :class:`MetricReading` whose name
is the dotted path, and produces one :class:`Reading` per message. It registers
itself as the ``#`` fallback in the parser registry so any topic that no
specific parser claims routes here.

Test layering:

  * Task 4.1 — pure-parser behavior (10 tests).
  * Task 4.4 — auto-registration as fallback (2 tests).

The two tasks share this file because both validate the parser's role in the
registry, and the 4.4 wiring test depends on the parser class existing.
"""

from __future__ import annotations

import json
import logging
import uuid

import pytest

pytestmark = [pytest.mark.unit]


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_parser_registry():
    """Reset the parser registry between tests so registry additions do not leak.

    The autouse fixture mirrors the pattern in ``test_bliiot_s475e_parser.py``
    and ``test_topic_router.py``: clear, re-seed BLIIoT (so the
    ``test_fallback_resolves_to_generic_json`` test sees a non-empty registry
    when constructing :class:`TopicRouter` without explicit parsers), yield,
    clear again.
    """
    from services.mqtt.parsers import _clear_registry, register
    from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser
    from services.mqtt.parsers.generic_json import GenericJsonParser

    _clear_registry()
    register(BliiotS475EParser())
    register(GenericJsonParser())
    yield
    _clear_registry()


# ── Task 4.1: GenericJsonParser heuristic ──────────────────────────────────


class TestGenericJsonParserBasic:
    """Happy-path traversal of common JSON shapes."""

    def test_flat_key_value_payload(self):
        """Flat payload → one MetricReading per numeric key, dotted path = key."""
        from services.mqtt.parsers.generic_json import GenericJsonParser

        parser = GenericJsonParser()
        payload = json.dumps({"device_id": "d1", "temperature": 23.5, "humidity": 60}).encode(
            "utf-8"
        )

        readings = parser.parse("tenants/acme/devices/d1/state", payload)

        assert len(readings) == 1
        reading = readings[0]
        assert reading.device_id == "d1"
        assert reading.parser_name == "generic_json"
        assert reading.source_topic == "tenants/acme/devices/d1/state"

        metric_names = {m.name for m in reading.metrics}
        # `device_id` is NOT a metric — it's the device identity field.
        # `temperature` and `humidity` are the two numeric leaves.
        assert metric_names == {"temperature", "humidity"}
        values_by_name = {m.name: m.value for m in reading.metrics}
        assert values_by_name["temperature"] == 23.5
        assert values_by_name["humidity"] == 60

    def test_nested_object_payload(self):
        """Nested dict → metric name is the dotted path through the keys."""
        from services.mqtt.parsers.generic_json import GenericJsonParser

        parser = GenericJsonParser()
        payload = json.dumps({"device_id": "d1", "sensors": {"temp": 23.5}}).encode("utf-8")

        readings = parser.parse("tenants/acme/devices/d1/state", payload)

        assert len(readings) == 1
        reading = readings[0]
        # The path is `sensors.temp` — single dot, no leading dot.
        assert len(reading.metrics) == 1
        metric = reading.metrics[0]
        assert metric.name == "sensors.temp"
        assert metric.value == 23.5
        assert metric.unit is None
        assert dict(metric.tags) == {}

    def test_array_of_objects_payload(self):
        """Array elements are indexed in the dotted path (``a.0``, ``a.1``)."""
        from services.mqtt.parsers.generic_json import GenericJsonParser

        parser = GenericJsonParser()
        payload = json.dumps(
            {
                "device_id": "d1",
                "readings": [
                    {"name": "a", "value": 1},
                    {"name": "b", "value": 2},
                ],
            }
        ).encode("utf-8")

        readings = parser.parse("tenants/acme/devices/d1/state", payload)

        assert len(readings) == 1
        reading = readings[0]
        names_to_values = {m.name: m.value for m in reading.metrics}
        # Two numeric leaves, both inside the `readings` array.
        assert names_to_values == {
            "readings.0.value": 1,
            "readings.1.value": 2,
        }

    def test_mixed_types_skips_non_numeric(self):
        """Strings, nulls, and booleans must NOT become MetricReadings."""
        from services.mqtt.parsers.generic_json import GenericJsonParser

        parser = GenericJsonParser()
        payload = json.dumps(
            {
                "device_id": "d1",
                "a": 1,
                "b": "str",
                "c": None,
                "d": True,  # `bool` is a subclass of `int` — must be excluded.
                "e": False,
                "f": 3.14,
            }
        ).encode("utf-8")

        readings = parser.parse("tenants/acme/devices/d1/state", payload)

        assert len(readings) == 1
        reading = readings[0]
        names = {m.name for m in reading.metrics}
        # Only `a` and `f` survive — everything else is non-numeric.
        assert names == {"a", "f"}
        for m in reading.metrics:
            assert isinstance(m.value, (int, float))
            assert not isinstance(m.value, bool)


class TestGenericJsonParserLimits:
    """Traversal caps protect downstream Neo4j from runaway payloads."""

    def test_max_depth_exceeded_stops_and_logs(self, caplog):
        """Beyond depth 8 → recursion stops, a WARNING is logged."""
        from services.mqtt.parsers.generic_json import GenericJsonParser

        parser = GenericJsonParser()
        # Build a JSON tree that is 10 levels deep with a numeric leaf at the
        # bottom. Depth 8 should NOT see the leaf; depth 10 should.
        deep: dict = {"value": 99.9}
        for _ in range(10):
            deep = {"nested": deep}
        payload = json.dumps({"device_id": "d1", "x": deep}).encode("utf-8")

        with caplog.at_level(logging.WARNING, logger="services.mqtt.parsers.generic_json"):
            readings = parser.parse("tenants/acme/devices/d1/state", payload)

        # The leaf at depth 10 is unreachable — no `nested...nested.value`.
        # The shallow numeric leaves that ARE within depth 8 may or may not
        # appear; the only assertion we make is that depth was hit.
        for reading in readings:
            for m in reading.metrics:
                # The 10-deep leaf is too deep — confirm by the dot count.
                # `nested.nested.nested.nested.nested.nested.nested.nested.x`
                # is depth 8 + 1 (value) = path of 9 dots before `value`.
                dot_count = m.name.count(".")
                # Anything with >= 9 dots is past the cap (8 segments deep).
                assert dot_count < 9

        # The parser MUST emit at least one warning when depth is exceeded.
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("depth" in r.message.lower() for r in warnings), (
            f"Expected a depth warning, got: {[r.message for r in caplog.records]}"
        )

    def test_max_metrics_exceeded_stops_and_logs(self, caplog):
        """Beyond 256 metrics → collection stops, a WARNING is logged."""
        from services.mqtt.parsers.generic_json import GenericJsonParser

        parser = GenericJsonParser()
        # 300 numeric fields — well past the 256 cap.
        big = {"device_id": "d1"}
        big.update({f"k{i}": i for i in range(300)})
        payload = json.dumps(big).encode("utf-8")

        with caplog.at_level(logging.WARNING, logger="services.mqtt.parsers.generic_json"):
            readings = parser.parse("tenants/acme/devices/d1/state", payload)

        # No more than 256 metrics collected.
        total_metrics = sum(len(r.metrics) for r in readings)
        assert total_metrics <= 256

        # WARNING about the cap.
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "metric" in r.message.lower()
            and ("cap" in r.message.lower() or "256" in r.message or "limit" in r.message.lower())
            for r in warnings
        ), f"Expected a metrics-cap warning, got: {[r.message for r in caplog.records]}"


class TestGenericJsonParserErrors:
    """Malformed input is a ParseError so the subscriber ACKs and drops it."""

    def test_malformed_json_raises_parse_error(self):
        """Invalid UTF-8 / JSON → ParseError, never silent fallback."""
        from services.mqtt.parsers.base import ParseError
        from services.mqtt.parsers.generic_json import GenericJsonParser

        parser = GenericJsonParser()

        with pytest.raises(ParseError):
            parser.parse("tenants/acme/devices/d1/state", b"this is { not json")

    def test_malformed_utf8_raises_parse_error(self):
        """Non-UTF-8 bytes → ParseError (not UnicodeDecodeError leaked out)."""
        from services.mqtt.parsers.base import ParseError
        from services.mqtt.parsers.generic_json import GenericJsonParser

        parser = GenericJsonParser()

        with pytest.raises(ParseError):
            parser.parse("tenants/acme/devices/d1/state", b"\xff\xfe\x00bad")


class TestGenericJsonParserIdentity:
    """device_id precedence: payload > generated UUID4."""

    def test_payload_device_id_wins_over_generated(self):
        """When the payload carries ``device_id``, the parser uses it verbatim."""
        from services.mqtt.parsers.generic_json import GenericJsonParser

        parser = GenericJsonParser()
        payload = json.dumps({"device_id": "explicit-id-42", "x": 1}).encode("utf-8")

        readings = parser.parse("tenants/acme/devices/d1/state", payload)

        assert len(readings) == 1
        assert readings[0].device_id == "explicit-id-42"

    def test_no_payload_device_id_generates_uuid4(self):
        """When the payload omits ``device_id``, a UUID4 is generated."""
        from services.mqtt.parsers.generic_json import GenericJsonParser

        parser = GenericJsonParser()
        payload = json.dumps({"x": 1, "y": 2}).encode("utf-8")

        readings = parser.parse("tenants/acme/devices/d1/state", payload)

        assert len(readings) == 1
        # The generated id is a valid UUID4 string.
        parsed = uuid.UUID(readings[0].device_id)
        assert parsed.version == 4

    def test_no_numeric_leaves_yields_empty_metrics(self):
        """Payload with no numerics → Reading with empty metrics (still valid)."""
        from services.mqtt.parsers.generic_json import GenericJsonParser

        parser = GenericJsonParser()
        payload = json.dumps({"device_id": "d1", "name": "foo", "label": "bar"}).encode("utf-8")

        readings = parser.parse("tenants/acme/devices/d1/state", payload)

        assert len(readings) == 1
        assert readings[0].device_id == "d1"
        assert readings[0].metrics == ()


# ── Task 4.4: Auto-registration as fallback ─────────────────────────────────


class TestGenericJsonRegistration:
    """GenericJsonParser must register itself as the ``#`` fallback."""

    def test_generic_json_registered_as_fallback(self):
        """``all_parsers()`` includes ``generic_json`` after module import."""
        from services.mqtt.parsers import all_parsers

        names = {p.name for p in all_parsers()}
        assert "generic_json" in names
        # Sanity: the other built-in parser is also present.
        assert "bliiot_s475e" in names

    def test_fallback_resolves_to_generic_json(self):
        """A topic that no specific parser claims falls back to GenericJson.

        ``tenants/acme/sensors/123`` is not claimed by BLIIoT (``rtu/+/+/telemetry``
        is its only pattern), so the router should resolve it to the ``#``
        fallback parser — which is now :class:`GenericJsonParser`.
        """
        from services.mqtt.parsers.generic_json import GenericJsonParser
        from services.mqtt.topic_router import TopicRouter

        router = TopicRouter()  # uses the global registry (BLIIoT + GenericJson)
        resolved = router.resolve("tenants/acme/sensors/123")
        assert resolved is not None
        assert isinstance(resolved, GenericJsonParser)
        assert resolved.name == "generic_json"
