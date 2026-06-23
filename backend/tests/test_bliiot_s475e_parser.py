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


# ── Parser identity / registration metadata ─────────────────────────────────


class TestParserMetadata:
    def test_parser_name_and_topic_patterns(self) -> None:
        from services.mqtt.parsers.base import Parser
        from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser

        parser = BliiotS475EParser()
        assert parser.name == "bliiot_s475e"
        assert parser.topic_patterns == ("rtu/+/+/telemetry",)
        assert isinstance(parser, Parser)
