"""Unit tests for MQTT subscriber — topic parsing, payload validation, and upsert orchestration.

Mark: unit
"""

import pytest
import json
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4


class TestParseTelemetryTopic:
    """Tests for parse_telemetry_topic — extracts location_id and rtu_id from MQTT topic.

    Topic structure: rtu/{location_id}/{rtu_id}/telemetry
    """

    def test_valid_topic_extracts_segments(self):
        """Valid topic 'rtu/{loc}/{rtu}/telemetry' returns (location_id, rtu_id)."""
        from services.mqtt_subscriber import parse_telemetry_topic

        location_id = str(uuid4())
        rtu_id = str(uuid4())
        topic = f"rtu/{location_id}/{rtu_id}/telemetry"

        loc, rtu = parse_telemetry_topic(topic)

        assert loc == location_id
        assert rtu == rtu_id

    def test_valid_topic_with_uuid_format(self):
        """UUID-formatted segments are returned as-is (no validation at parse layer)."""
        from services.mqtt_subscriber import parse_telemetry_topic

        topic = "rtu/550e8400-e29b-41d4-a716-446655440000/6ba7b810-9dad-11d1-80b4-00c04fd430c8/telemetry"

        loc, rtu = parse_telemetry_topic(topic)

        assert loc == "550e8400-e29b-41d4-a716-446655440000"
        assert rtu == "6ba7b810-9dad-11d1-80b4-00c04fd430c8"

    def test_topic_wrong_prefix_raises(self):
        """Topic not starting with 'rtu/' raises ValueError."""
        from services.mqtt_subscriber import parse_telemetry_topic

        with pytest.raises(ValueError) as exc_info:
            parse_telemetry_topic("sensor/123/456/telemetry")
        assert "rtu/" in str(exc_info.value)

    def test_topic_too_few_segments_raises(self):
        """Topic with fewer than 4 segments raises ValueError."""
        from services.mqtt_subscriber import parse_telemetry_topic

        with pytest.raises(ValueError) as exc_info:
            parse_telemetry_topic("rtu/location/rtu")
        assert "Expected 4 topic segments" in str(exc_info.value)

    def test_topic_too_many_segments_raises(self):
        """Topic with more than 4 segments raises ValueError."""
        from services.mqtt_subscriber import parse_telemetry_topic

        with pytest.raises(ValueError) as exc_info:
            parse_telemetry_topic("rtu/loc/rtu/extra/telemetry")
        assert "Expected 4 topic segments" in str(exc_info.value)

    def test_topic_wrong_suffix_raises(self):
        """Topic not ending with 'telemetry' raises ValueError."""
        from services.mqtt_subscriber import parse_telemetry_topic

        location_id = str(uuid4())
        rtu_id = str(uuid4())
        topic = f"rtu/{location_id}/{rtu_id}/status"

        with pytest.raises(ValueError) as exc_info:
            parse_telemetry_topic(topic)
        assert "telemetry" in str(exc_info.value)

    def test_empty_topic_raises(self):
        """Empty string raises ValueError."""
        from services.mqtt_subscriber import parse_telemetry_topic

        with pytest.raises(ValueError):
            parse_telemetry_topic("")

    def test_partial_topic_raises(self):
        """Partial topic 'rtu/loc/rtu' raises ValueError."""
        from services.mqtt_subscriber import parse_telemetry_topic

        with pytest.raises(ValueError):
            parse_telemetry_topic("rtu/loc/rtu")


class TestTelemetryPayloadValidation:
    """Tests for TelemetryMessage parsing from MQTT JSON payload."""

    def test_valid_payload_parses(self):
        """Valid JSON payload with sensors array parses to TelemetryMessage."""
        from models.rtu_sensor import TelemetryMessage

        payload = {
            "timestamp": "2026-05-04T12:00:00Z",
            "sensors": [
                {"register_addr": 0, "value": 2375, "unit": "0.01°C"},
                {"register_addr": 2, "value": 5120, "unit": "0.01%RH"},
            ],
            "digital_inputs": [1, 0, 1, 0, 0, 0, 0, 0],
            "relays": [0, 0, 0, 0],
        }

        msg = TelemetryMessage(**payload)

        assert msg.timestamp == "2026-05-04T12:00:00Z"
        assert len(msg.sensors) == 2
        assert msg.sensors[0].register_addr == 0
        assert msg.sensors[0].value == 2375
        assert msg.digital_inputs == [1, 0, 1, 0, 0, 0, 0, 0]
        assert msg.relays == [0, 0, 0, 0]

    def test_payload_without_optional_timestamp(self):
        """Payload without timestamp is valid (optional field)."""
        from models.rtu_sensor import TelemetryMessage

        payload = {
            "sensors": [{"register_addr": 0, "value": 2375, "unit": "0.01°C"}],
        }

        msg = TelemetryMessage(**payload)

        assert msg.timestamp is None
        assert len(msg.sensors) == 1

    def test_payload_missing_sensors_raises(self):
        """Payload without sensors array raises ValidationError."""
        from pydantic import ValidationError
        from models.rtu_sensor import TelemetryMessage

        with pytest.raises(ValidationError) as exc_info:
            TelemetryMessage(**{"timestamp": "2026-05-04T12:00:00Z"})
        assert "sensors" in str(exc_info.value)

    def test_payload_empty_sensors_raises(self):
        """Payload with empty sensors array raises ValidationError."""
        from pydantic import ValidationError
        from models.rtu_sensor import TelemetryMessage

        with pytest.raises(ValidationError) as exc_info:
            TelemetryMessage(**{"sensors": []})
        assert "at least 1" in str(exc_info.value).lower() or "sensors" in str(exc_info.value)

    def test_payload_sensor_register_out_of_bounds_raises(self):
        """Sensor with register_addr > 319 raises ValidationError."""
        from pydantic import ValidationError
        from models.rtu_sensor import TelemetryMessage

        payload = {
            "sensors": [{"register_addr": 400, "value": 2375, "unit": "0.01°C"}],
        }

        with pytest.raises(ValidationError) as exc_info:
            TelemetryMessage(**payload)
        assert "319" in str(exc_info.value)

    def test_payload_sensor_missing_required_field_raises(self):
        """Sensor missing 'value' field raises ValidationError."""
        from pydantic import ValidationError
        from models.rtu_sensor import TelemetryMessage

        payload = {
            "sensors": [{"register_addr": 0, "unit": "0.01°C"}],
        }

        with pytest.raises(ValidationError) as exc_info:
            TelemetryMessage(**payload)
        assert "value" in str(exc_info.value)

    def test_payload_with_minimal_sensor(self):
        """Payload with only required sensor fields is valid."""
        from models.rtu_sensor import TelemetryMessage

        payload = {
            "sensors": [{"register_addr": 0, "value": 2375}],
        }

        msg = TelemetryMessage(**payload)

        assert len(msg.sensors) == 1
        assert msg.sensors[0].unit is None


class TestProcessTelemetryMessage:
    """Tests for process_telemetry_message — orchestrates RTU/Sensor upsert from MQTT message.

    Uses mocking to isolate the business logic without requiring a live Neo4j.
    """

    def test_process_message_calls_upsert_for_rtu_and_sensors(self):
        """process_telemetry_message calls upsert for RTU and each sensor in payload."""
        from services.mqtt_subscriber import process_telemetry_message
        from models.rtu_sensor import TelemetryMessage
        from unittest.mock import MagicMock

        location_id = str(uuid4())
        rtu_id = str(uuid4())
        topic = f"rtu/{location_id}/{rtu_id}/telemetry"
        payload = {
            "timestamp": "2026-05-04T12:00:00Z",
            "sensors": [
                {"register_addr": 0, "value": 2375, "unit": "0.01°C"},
                {"register_addr": 2, "value": 5120, "unit": "0.01%RH"},
            ],
        }
        msg = TelemetryMessage(**payload)

        mock_rtu_service = MagicMock()
        mock_rtu_service.get_or_create_rtu = MagicMock(return_value={"id": rtu_id})
        mock_rtu_service.get_or_create_sensor = MagicMock(return_value={"id": "sensor-1"})

        result = process_telemetry_message(topic, msg, mock_rtu_service)

        # Should have called get_or_create_rtu once
        assert mock_rtu_service.get_or_create_rtu.call_count == 1
        # Should have called get_or_create_sensor once per sensor
        assert mock_rtu_service.get_or_create_sensor.call_count == 2
        # Result should indicate success
        assert result["status"] == "processed"

    def test_process_message_with_invalid_topic_returns_error(self):
        """process_telemetry_message returns error dict for malformed topic (no exception raised)."""
        from services.mqtt_subscriber import process_telemetry_message
        from models.rtu_sensor import TelemetryMessage
        from unittest.mock import MagicMock

        payload = {
            "sensors": [{"register_addr": 0, "value": 2375}],
        }
        msg = TelemetryMessage(**payload)
        mock_rtu_service = MagicMock()

        result = process_telemetry_message("bad/topic", msg, mock_rtu_service)

        assert result["status"] == "error"
        assert "Invalid topic" in result["error"]

    def test_process_message_returns_error_on_service_failure(self):
        """process_telemetry_message returns error dict when service raises."""
        from services.mqtt_subscriber import process_telemetry_message
        from models.rtu_sensor import TelemetryMessage
        from unittest.mock import MagicMock

        location_id = str(uuid4())
        rtu_id = str(uuid4())
        topic = f"rtu/{location_id}/{rtu_id}/telemetry"
        payload = {
            "sensors": [{"register_addr": 0, "value": 2375}],
        }
        msg = TelemetryMessage(**payload)

        mock_rtu_service = MagicMock()
        mock_rtu_service.get_or_create_rtu = MagicMock(side_effect=Exception("Neo4j connection failed"))

        result = process_telemetry_message(topic, msg, mock_rtu_service)

        assert result["status"] == "error"
        assert "Neo4j" in result["error"]


class TestRTUServiceGetOrCreate:
    """Tests for RTUService.get_or_create_rtu and get_or_create_sensor.

    These methods are used by the MQTT subscriber to upsert RTU/Sensor nodes.
    They mirror the existing create_* methods but provide get-or-create semantics.
    """

    def test_get_or_create_rtu_creates_when_not_exists(self, mock_neo4j_driver):
        """get_or_create_rtu calls upsert_rtu when RTU does not exist."""
        from services.rtu_service import RTUService
        from unittest.mock import MagicMock

        location_id = uuid4()
        rtu_id = uuid4()

        # Simulate RTU not found (empty result)
        mock_neo4j_driver.mock_session.set_response(
            "match (r:rtu",
            []
        )
        mock_neo4j_driver.mock_session.set_response(
            "merge (r:rtu",
            [{"id": str(rtu_id)}]
        )

        service = RTUService(driver=mock_neo4j_driver)
        # The service internally calls get_rtu first, then upsert_rtu if not found
        # For this test we simulate the "not found" path
        result = service.get_or_create_rtu(
            rtu_id=str(rtu_id),
            location_id=str(location_id),
            name="RTU-Test",
            ip="192.168.1.100",
        )

        # Should have called upsert (verify via query capture)
        upsert_calls = [
            q for q in mock_neo4j_driver.mock_session.queries
            if "merge (r:rtu" in q["query"].lower()
        ]
        assert len(upsert_calls) >= 1

    def test_list_rtus_filters_by_location_id(self, mock_neo4j_driver):
        """list_rtus with location_id filter passes it to repo."""
        from services.rtu_service import RTUService

        location_id = str(uuid4())
        mock_neo4j_driver.mock_session.set_response(
            "match (r:rtu",
            []
        )

        service = RTUService(driver=mock_neo4j_driver)
        result = service.list_rtus(location_id=location_id)

        # Verify the location_id was passed in params
        list_queries = [
            q for q in mock_neo4j_driver.mock_session.queries
            if "match (r:rtu" in q["query"].lower()
        ]
        assert len(list_queries) >= 1
        # The query should include location_id parameter
        params = list_queries[0].get("params", {})
        assert "location_id" in params or str(location_id) in str(params)


# Mark entire module as unit tests
pytestmark = [pytest.mark.unit]
