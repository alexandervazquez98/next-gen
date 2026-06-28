"""Unit tests for the BLIIoT S475E parser.

Mark: unit
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.unit]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _topic(loc: str | None = None, rtu: str | None = None) -> str:
    return f"rtu/{loc or uuid4()}/{rtu or uuid4()}/telemetry"


def _payload(
    sensors: list[dict[str, Any]] | None = None,
    *,
    timestamp: str | None = "2026-05-04T12:00:00Z",
    digital_inputs: list[int] | None = None,
    relays: list[int] | None = None,
) -> bytes:
    body: dict[str, Any] = {}
    if sensors is not None:
        body["sensors"] = sensors
    else:
        body["sensors"] = [{"register_addr": 0, "value": 2375, "unit": "0.01°C"}]
    if timestamp is not None:
        body["timestamp"] = timestamp
    if digital_inputs is not None:
        body["digital_inputs"] = digital_inputs
    if relays is not None:
        body["relays"] = relays
    return json.dumps(body).encode("utf-8")


# ── Topic parsing (re-exported helper) ──────────────────────────────────────


class TestParseTelemetryTopic:
    def test_valid_topic_extracts_segments(self) -> None:
        from services.mqtt.parsers.bliiot_s475e import parse_telemetry_topic

        location_id = str(uuid4())
        rtu_id = str(uuid4())
        topic = f"rtu/{location_id}/{rtu_id}/telemetry"

        loc, rtu = parse_telemetry_topic(topic)

        assert loc == location_id
        assert rtu == rtu_id

    def test_wrong_suffix_raises_value_error(self) -> None:
        from services.mqtt.parsers.bliiot_s475e import parse_telemetry_topic

        with pytest.raises(ValueError):
            parse_telemetry_topic(f"rtu/{uuid4()}/{uuid4()}/status")


# ── Parser class — happy path ───────────────────────────────────────────────


class TestBliiotParserHappyPath:
    def test_three_sensors_with_timestamp_no_extras(self) -> None:
        from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser

        topic = _topic()
        payload = _payload(
            sensors=[
                {"register_addr": 0, "value": 2375, "unit": "0.01°C"},
                {"register_addr": 1, "value": 5120, "unit": "0.01%RH"},
                {"register_addr": 2, "value": 1, "unit": None},
            ],
            digital_inputs=None,
            relays=None,
        )

        readings = BliiotS475EParser().parse(topic, payload)

        assert len(readings) == 1
        r = readings[0]
        assert r.parser_name == "bliiot_s475e"
        assert r.source_topic == topic
        assert r.timestamp == datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)
        # device_id and location_id from topic
        loc, rtu = topic.split("/")[1], topic.split("/")[2]
        assert r.device_id == rtu
        assert r.location_id == loc
        # 3 metrics, named by register
        names = [m.name for m in r.metrics]
        assert names == ["register_0", "register_1", "register_2"]
        # No extras -> extra empty
        assert r.extra == {}
        # Tags carry register_addr
        assert r.metrics[0].tags == {"register_addr": "0"}
        assert r.metrics[2].unit is None

    def test_one_sensor_with_digital_inputs_and_relays(self) -> None:
        from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser

        topic = _topic()
        payload = _payload(
            sensors=[{"register_addr": 5, "value": 12, "unit": "V"}],
            digital_inputs=[1, 0, 1, 0, 0, 0, 0, 0],
            relays=[0, 0, 1, 0],
        )

        r = BliiotS475EParser().parse(topic, payload)[0]

        assert r.metrics[0].name == "register_5"
        assert r.metrics[0].value == 12
        assert r.metrics[0].unit == "V"
        assert r.extra == {
            "digital_inputs": [1, 0, 1, 0, 0, 0, 0, 0],
            "relays": [0, 0, 1, 0],
        }

    def test_missing_timestamp_defaults_to_utc_now(self) -> None:
        from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser

        topic = _topic()
        payload = _payload(sensors=[{"register_addr": 0, "value": 1}], timestamp=None)
        before = datetime.now(UTC)

        r = BliiotS475EParser().parse(topic, payload)[0]
        after = datetime.now(UTC)

        # timestamp was None in payload, so parser fills with datetime.now(UTC)
        assert before <= r.timestamp <= after
        assert r.timestamp.tzinfo is not None


# ── Parser class — failure modes ────────────────────────────────────────────


class TestBliiotParserFailures:
    def test_malformed_topic_raises_parse_error(self) -> None:
        from services.mqtt.parsers.base import ParseError
        from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser

        with pytest.raises(ParseError):
            BliiotS475EParser().parse("bad/topic", _payload())

    def test_malformed_json_raises_parse_error(self) -> None:
        from services.mqtt.parsers.base import ParseError
        from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser

        with pytest.raises(ParseError):
            BliiotS475EParser().parse(_topic(), b"{not json")

    def test_empty_sensors_raises_parse_error(self) -> None:
        from services.mqtt.parsers.base import ParseError
        from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser

        with pytest.raises(ParseError):
            BliiotS475EParser().parse(_topic(), _payload(sensors=[]))

    def test_non_utf8_payload_raises_parse_error(self) -> None:
        from services.mqtt.parsers.base import ParseError
        from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser

        with pytest.raises(ParseError):
            BliiotS475EParser().parse(_topic(), b"\xff\xfe\xfd invalid utf-8")


# ── Backward compat — process_telemetry_message re-exported ─────────────────


class TestBackCompatFunctions:
    def test_process_telemetry_message_still_works(self) -> None:
        from unittest.mock import MagicMock

        from models.rtu_sensor import TelemetryMessage
        from services.mqtt.parsers.bliiot_s475e import process_telemetry_message

        topic = _topic()
        msg = TelemetryMessage(sensors=[{"register_addr": 0, "value": 1}])
        svc = MagicMock()
        svc.get_or_create_rtu = MagicMock(return_value={"id": "x"})
        svc.get_or_create_sensor = MagicMock(return_value={"id": "y"})

        result = process_telemetry_message(topic, msg, svc)

        assert result["status"] == "processed"
        assert svc.get_or_create_rtu.call_count == 1
        assert svc.get_or_create_sensor.call_count == 1

    def test_process_telemetry_message_invalid_topic_returns_error(self) -> None:
        from unittest.mock import MagicMock

        from models.rtu_sensor import TelemetryMessage
        from services.mqtt.parsers.bliiot_s475e import process_telemetry_message

        msg = TelemetryMessage(sensors=[{"register_addr": 0, "value": 1}])
        result = process_telemetry_message("bad/topic", msg, MagicMock())
        assert result["status"] == "error"
        assert "Invalid topic" in result["error"]

    def test_telemetry_message_re_exported(self) -> None:
        """TelemetryMessage must be importable from the parser module for back-compat."""
        # Same class — re-export, not copy
        from models.rtu_sensor import TelemetryMessage as Orig
        from services.mqtt.parsers.bliiot_s475e import TelemetryMessage as Re

        assert Re is Orig


# ── Sensor-skip on ValueError ───────────────────────────────────────────────


class TestSensorSkipOnValueError:
    def test_invalid_sensor_register_is_skipped_others_emitted(self) -> None:
        """If get_or_create_sensor raises ValueError, that sensor is skipped; others emit.

        We mock process_telemetry_message's RTUService so one sensor triggers
        a ValueError, and the rest succeed. The orchestrator's ACK/NACK layer
        does not see this — it is internal skip-and-continue behavior.
        """
        from unittest.mock import MagicMock

        from models.rtu_sensor import TelemetryMessage
        from services.mqtt.parsers.bliiot_s475e import process_telemetry_message

        topic = _topic()
        msg = TelemetryMessage(
            sensors=[
                {"register_addr": 0, "value": 1},
                {"register_addr": 1, "value": 2},  # this one will raise
                {"register_addr": 2, "value": 3},
            ]
        )

        svc = MagicMock()
        svc.get_or_create_rtu = MagicMock(return_value={"id": "r"})

        def maybe_raise(register_addr: int, **_kwargs: Any) -> dict[str, str]:
            if register_addr == 1:
                raise ValueError("register_addr out of bounds")
            return {"id": f"sensor-{register_addr}"}

        svc.get_or_create_sensor = MagicMock(side_effect=maybe_raise)

        result = process_telemetry_message(topic, msg, svc)

        # status still "processed" (skip-and-continue), but sensor_count == 2
        assert result["status"] == "processed"
        assert result["sensor_count"] == 2
        assert svc.get_or_create_sensor.call_count == 3  # all three attempted


# ── Pure-parser contract (architecture regression guard) ────────────────────


class TestBliiotParserIsPure:
    """Regression tests guarding the pure-parser architecture contract.

    Per the design (section 2.2), :class:`BliiotS475EParser` is a PURE parser
    that produces :class:`Reading` objects only — it must NOT call
    ``RTUService`` or any persistence layer. Persistence is the subscriber's
    responsibility (PR3b will route through ``DeviceMetricRepo``).

    NOTE: the module-level :func:`process_telemetry_message` function BELOW
    the parser class DOES call ``RTUService`` — that is intentional legacy
    back-compat behavior. Only the ``BliiotS475EParser`` CLASS must be pure.

    Triggered by sdd-verify-minimax FAIL (PR1, critical 5) — the verify grep
    found actual ``rtu_service.get_or_create_*`` calls under
    ``services/mqtt/``. The fix is to (a) confirm the parser class is pure
    via these tests, and (b) keep the legacy function's RTUService calls
    explicitly acknowledged as the back-compat path.
    """

    def test_parse_works_without_any_rtu_service(self) -> None:
        """Runtime contract: ``parse()`` produces a Reading with no service param.

        ``BliiotS475EParser.parse`` does NOT accept a service parameter and
        must not touch ``RTUService`` indirectly. We patch
        ``services.rtu_service.RTUService`` and assert the patch is never
        accessed. This guards against accidentally re-coupling the parser to
        the persistence layer.
        """
        from unittest.mock import patch

        from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser

        parser = BliiotS475EParser()
        sample_payload = (
            b'{"timestamp": "2026-01-01T00:00:00Z", '
            b'"sensors": [{"register_addr": 0, "value": 2375, "unit": "0.01\xc2\xb0C"}]}'
        )

        with patch("services.rtu_service.RTUService") as mock_rtu_class:
            readings = parser.parse("rtu/loc-1/rtu-1/telemetry", sample_payload)

        # Positive: parse() produced the expected Reading without any service
        assert len(readings) == 1
        assert readings[0].device_id == "rtu-1"
        assert readings[0].location_id == "loc-1"
        assert len(readings[0].metrics) == 1
        assert readings[0].metrics[0].name == "register_0"
        assert readings[0].metrics[0].value == 2375

        # Negative: RTUService class was never instantiated or accessed.
        # This is the architectural contract — the parser is a pure producer.
        mock_rtu_class.assert_not_called()
        assert mock_rtu_class.mock_calls == []

    def test_parser_class_source_has_no_rtu_service_references(self) -> None:
        """Static contract: ``BliiotS475EParser`` source must not mention RTUService.

        ``unittest.mock.patch`` cannot reliably catch a future regression
        where someone re-introduces persistence via ``from services.rtu_service
        import RTUService`` (the binding is captured at import time). Static
        source inspection is deterministic and catches both call patterns
        and import statements regardless of when the module is loaded.
        """
        import inspect

        from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser

        # Source of the class only — NOT the whole module. The legacy
        # ``process_telemetry_message`` function intentionally uses RTUService.
        source = inspect.getsource(BliiotS475EParser)

        forbidden_tokens = (
            "RTUService",
            "get_or_create_rtu",
            "get_or_create_sensor",
            "from services.rtu_service",
            "from services import rtu_service",
        )
        leaked = [t for t in forbidden_tokens if t in source]
        assert not leaked, (
            f"BliiotS475EParser source contains forbidden tokens: {leaked}. "
            f"The parser must be a pure producer of Reading objects; "
            f"persistence is the subscriber's responsibility (PR3b)."
        )

    def test_parser_parse_signature_takes_no_persistence_params(self) -> None:
        """Structural contract: ``parse`` signature is exactly ``(self, topic, payload)``.

        Defense-in-depth: even a defaulted ``rtu_service=None`` parameter
        would let a future caller wire persistence into the parser. Locking
        the signature makes that mistake obvious in code review.
        """
        import inspect

        from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser

        sig = inspect.signature(BliiotS475EParser.parse)
        param_names = list(sig.parameters.keys())

        assert param_names == ["self", "topic", "payload"], (
            f"BliiotS475EParser.parse signature must be (self, topic, payload) "
            f"— no rtu_service or persistence params. Got: {param_names}"
        )


# ── Parser identity / registration metadata ─────────────────────────────────


class TestParserMetadata:
    def test_parser_name_and_topic_patterns(self) -> None:
        from services.mqtt.parsers.base import Parser
        from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser

        parser = BliiotS475EParser()
        assert parser.name == "bliiot_s475e"
        assert parser.topic_patterns == ("rtu/+/+/telemetry",)
        assert isinstance(parser, Parser)


# ── Parser registry ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_registry():
    """Reset the global registry before each test in this module.

    The package __init__ auto-registers BLIIoT at import time, which would
    pollute test state across the suite. _clear_registry is intentionally
    private (underscore-prefixed) so production code cannot use it.
    """
    from services.mqtt.parsers import _clear_registry

    _clear_registry()
    yield
    _clear_registry()


class TestParserRegistry:
    def test_registry_register_twice_raises(self) -> None:
        """Re-registering a parser with the same name raises ValueError."""
        from services.mqtt.parsers import _clear_registry, register
        from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser

        _clear_registry()
        register(BliiotS475EParser())
        with pytest.raises(ValueError, match="bliiot_s475e"):
            register(BliiotS475EParser())

    def test_registry_get_unknown_raises(self) -> None:
        """get() with an unknown name raises KeyError."""
        from services.mqtt.parsers import _clear_registry, get

        _clear_registry()
        with pytest.raises(KeyError):
            get("nonexistent")

    def test_registry_all_parsers_returns_registered(self) -> None:
        """After register(), all_parsers() includes the new parser."""
        from services.mqtt.parsers import _clear_registry, all_parsers, register
        from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser

        _clear_registry()
        register(BliiotS475EParser())

        parsers = all_parsers()
        assert len(parsers) == 1
        assert parsers[0].name == "bliiot_s475e"
