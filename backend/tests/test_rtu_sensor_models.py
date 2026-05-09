"""Unit tests for RTU/Sensor Pydantic models — pure validation logic, no external deps."""

import pytest
from pydantic import ValidationError
from uuid import uuid4


class TestRTUBaseModel:
    """Tests for RTU base and create models."""

    def test_valid_rtu_create(self):
        """Create RTU with all required fields."""
        from models.rtu_sensor import RTUCreate

        rtu = RTUCreate(
            name="RTU-BH-01",
            location_id=uuid4(),
            ip="192.168.1.100",
            mqtt_config={"broker_host": "mqtt.example.com", "broker_port": 8883},
        )
        assert rtu.name == "RTU-BH-01"
        assert rtu.ip == "192.168.1.100"
        assert rtu.location_id is not None

    def test_rtu_create_defaults(self):
        """RTUCreate with only required fields."""
        from models.rtu_sensor import RTUCreate

        rtu = RTUCreate(name="RTU-Default", location_id=uuid4())
        assert rtu.ip is None
        assert rtu.mqtt_config is None

    def test_rtu_create_missing_name_raises(self):
        """Missing required 'name' raises ValidationError."""
        from models.rtu_sensor import RTUCreate

        with pytest.raises(ValidationError) as exc_info:
            RTUCreate(location_id=uuid4())
        assert "name" in str(exc_info.value)

    def test_rtu_create_missing_location_id_raises(self):
        """Missing required 'location_id' raises ValidationError."""
        from models.rtu_sensor import RTUCreate

        with pytest.raises(ValidationError) as exc_info:
            RTUCreate(name="RTU-Test")
        assert "location_id" in str(exc_info.value)


class TestRTUUpdateModel:
    """Tests for RTUUpdate model."""

    def test_valid_rtu_update(self):
        """Update RTU with optional fields."""
        from models.rtu_sensor import RTUUpdate

        update = RTUUpdate(name="RTU-Updated", ip="10.0.0.50", status="offline")
        assert update.name == "RTU-Updated"
        assert update.ip == "10.0.0.50"
        assert update.status == "offline"

    def test_rtu_update_all_optional(self):
        """RTUUpdate fields are all optional."""
        from models.rtu_sensor import RTUUpdate

        update = RTUUpdate()
        assert update.name is None
        assert update.ip is None
        assert update.status is None

    def test_rtu_update_invalid_status_raises(self):
        """RTUUpdate with invalid status value raises ValidationError."""
        from models.rtu_sensor import RTUUpdate

        with pytest.raises(ValidationError) as exc_info:
            RTUUpdate(status="foobar")
        assert "status" in str(exc_info.value)


class TestRTUResponseModel:
    """Tests for RTUResponse model."""

    def test_valid_rtu_response(self):
        """RTUResponse includes all expected fields."""
        from models.rtu_sensor import RTUResponse

        rtu_id = uuid4()
        location_id = uuid4()
        rtu = RTUResponse(
            id=rtu_id,
            name="RTU-Resp-01",
            ip="192.168.1.50",
            layer="RTU",
            status="online",
            location_id=location_id,
            mqtt_topic=f"rtu/{location_id}/{rtu_id}/telemetry",
            created_at="2026-05-04T12:00:00Z",
            updated_at="2026-05-04T12:00:00Z",
        )
        assert rtu.id == rtu_id
        assert rtu.layer == "RTU"
        assert rtu.status == "online"

    def test_rtu_response_defaults(self):
        """RTUResponse defaults layer to RTU."""
        from models.rtu_sensor import RTUResponse

        rtu_id = uuid4()
        location_id = uuid4()
        rtu = RTUResponse(
            id=rtu_id,
            name="RTU-Default",
            location_id=location_id,
            mqtt_topic=f"rtu/{location_id}/{rtu_id}/telemetry",
            created_at="2026-05-04T12:00:00Z",
            updated_at="2026-05-04T12:00:00Z",
        )
        assert rtu.layer == "RTU"
        assert rtu.ip is None


class TestSensorCreateModel:
    """Tests for SensorCreate model."""

    def test_valid_sensor_create(self):
        """Create sensor with all required fields."""
        from models.rtu_sensor import SensorCreate

        sensor = SensorCreate(
            name="Temperature Sensor 1",
            register_addr=0,
            register_count=2,
            sensor_type="temperature",
        )
        assert sensor.name == "Temperature Sensor 1"
        assert sensor.register_addr == 0
        assert sensor.register_count == 2
        assert sensor.sensor_type == "temperature"

    def test_sensor_create_default_count(self):
        """register_count defaults to 1."""
        from models.rtu_sensor import SensorCreate

        sensor = SensorCreate(name="DI Sensor", register_addr=5, sensor_type="digital_input")
        assert sensor.register_count == 1

    def test_sensor_create_missing_required_raises(self):
        """Missing name, register_addr, or sensor_type raises ValidationError."""
        from models.rtu_sensor import SensorCreate

        # Missing name
        with pytest.raises(ValidationError) as exc_info:
            SensorCreate(register_addr=0, sensor_type="temperature")
        assert "name" in str(exc_info.value)

        # Missing register_addr
        with pytest.raises(ValidationError) as exc_info:
            SensorCreate(name="Sensor", sensor_type="temperature")
        assert "register_addr" in str(exc_info.value)


class TestSensorUpdateModel:
    """Tests for SensorUpdate model."""

    def test_valid_sensor_update(self):
        """SensorUpdate with optional fields."""
        from models.rtu_sensor import SensorUpdate

        update = SensorUpdate(name="Updated Sensor", unit="0.1°C")
        assert update.name == "Updated Sensor"
        assert update.unit == "0.1°C"

    def test_sensor_update_all_optional(self):
        """SensorUpdate fields are all optional."""
        from models.rtu_sensor import SensorUpdate

        update = SensorUpdate()
        assert update.name is None
        assert update.unit is None


class TestSensorResponseModel:
    """Tests for SensorResponse model."""

    def test_valid_sensor_response(self):
        """SensorResponse includes all expected fields."""
        from models.rtu_sensor import SensorResponse

        sensor_id = uuid4()
        rtu_id = uuid4()
        sensor = SensorResponse(
            id=sensor_id,
            name="Temp Sensor",
            register_addr=0,
            register_count=2,
            unit="0.01°C",
            sensor_type="temperature",
            rtu_id=rtu_id,
            created_at="2026-05-04T12:00:00Z",
            updated_at="2026-05-04T12:00:00Z",
        )
        assert sensor.id == sensor_id
        assert sensor.rtu_id == rtu_id
        assert sensor.register_addr == 0


class TestTelemetrySensorModel:
    """Tests for TelemetrySensor (inside MQTT payload)."""

    def test_valid_telemetry_sensor(self):
        """Valid TelemetrySensor with required fields."""
        from models.rtu_sensor import TelemetrySensor

        ts = TelemetrySensor(register_addr=0, value=2375)
        assert ts.register_addr == 0
        assert ts.value == 2375
        assert ts.unit is None

    def test_telemetry_sensor_with_unit(self):
        """TelemetrySensor with optional unit field."""
        from models.rtu_sensor import TelemetrySensor

        ts = TelemetrySensor(register_addr=2, value=5120, unit="0.01%RH")
        assert ts.unit == "0.01%RH"

    def test_telemetry_sensor_missing_register_addr_raises(self):
        """Missing register_addr raises ValidationError."""
        from models.rtu_sensor import TelemetrySensor

        with pytest.raises(ValidationError) as exc_info:
            TelemetrySensor(value=100)
        assert "register_addr" in str(exc_info.value)


class TestTelemetryMessageModel:
    """Tests for TelemetryMessage (MQTT payload root)."""

    def test_valid_telemetry_message(self):
        """Valid MQTT payload with sensors array."""
        from models.rtu_sensor import TelemetryMessage, TelemetrySensor

        msg = TelemetryMessage(
            timestamp="2026-05-04T12:00:00Z",
            sensors=[
                TelemetrySensor(register_addr=0, value=2375, unit="0.01°C"),
                TelemetrySensor(register_addr=2, value=5120, unit="0.01%RH"),
            ],
            digital_inputs=[1, 0, 1, 0, 0, 0, 0, 0],
            relays=[0, 0, 0, 0],
        )
        assert len(msg.sensors) == 2
        assert msg.timestamp == "2026-05-04T12:00:00Z"
        assert msg.digital_inputs == [1, 0, 1, 0, 0, 0, 0, 0]

    def test_telemetry_message_minimal(self):
        """TelemetryMessage with only required sensors field."""
        from models.rtu_sensor import TelemetryMessage, TelemetrySensor

        msg = TelemetryMessage(sensors=[TelemetrySensor(register_addr=0, value=100)])
        assert len(msg.sensors) == 1
        assert msg.timestamp is None
        assert msg.digital_inputs is None
        assert msg.relays is None

    def test_telemetry_message_missing_sensors_raises(self):
        """Missing sensors array raises ValidationError."""
        from models.rtu_sensor import TelemetryMessage

        with pytest.raises(ValidationError) as exc_info:
            TelemetryMessage()
        assert "sensors" in str(exc_info.value)

    def test_telemetry_message_empty_sensors_raises(self):
        """Empty sensors array raises ValidationError."""
        from models.rtu_sensor import TelemetryMessage

        with pytest.raises(ValidationError) as exc_info:
            TelemetryMessage(sensors=[])
        assert "sensors" in str(exc_info.value)


class TestRegisterBoundsValidation:
    """Tests for Modbus register bounds (0-319 per spec)."""

    def test_register_addr_valid_range(self):
        """register_addr 0-319 is valid."""
        from models.rtu_sensor import SensorCreate

        # Lower bound
        sensor = SensorCreate(name="Sensor", register_addr=0, sensor_type="temperature")
        assert sensor.register_addr == 0

        # Upper bound
        sensor = SensorCreate(name="Sensor", register_addr=319, sensor_type="temperature")
        assert sensor.register_addr == 319

    def test_register_addr_invalid_above_319_raises(self):
        """register_addr > 319 raises ValidationError."""
        from models.rtu_sensor import SensorCreate

        with pytest.raises(ValidationError) as exc_info:
            SensorCreate(name="Sensor", register_addr=320, sensor_type="temperature")
        assert "register_addr" in str(exc_info.value)

    def test_register_addr_invalid_negative_raises(self):
        """register_addr < 0 raises ValidationError."""
        from models.rtu_sensor import SensorCreate

        with pytest.raises(ValidationError) as exc_info:
            SensorCreate(name="Sensor", register_addr=-1, sensor_type="temperature")
        assert "register_addr" in str(exc_info.value)

    def test_register_count_valid_range(self):
        """register_count 1-4 is valid."""
        from models.rtu_sensor import SensorCreate

        sensor = SensorCreate(name="Sensor", register_addr=0, register_count=1, sensor_type="temperature")
        assert sensor.register_count == 1

        sensor = SensorCreate(name="Sensor", register_addr=0, register_count=4, sensor_type="temperature")
        assert sensor.register_count == 4

    def test_register_count_invalid_above_4_raises(self):
        """register_count > 4 raises ValidationError."""
        from models.rtu_sensor import SensorCreate

        with pytest.raises(ValidationError) as exc_info:
            SensorCreate(name="Sensor", register_addr=0, register_count=5, sensor_type="temperature")
        assert "register_count" in str(exc_info.value)

    def test_register_count_invalid_below_1_raises(self):
        """register_count < 1 raises ValidationError."""
        from models.rtu_sensor import SensorCreate

        with pytest.raises(ValidationError) as exc_info:
            SensorCreate(name="Sensor", register_addr=0, register_count=0, sensor_type="temperature")
        assert "register_count" in str(exc_info.value)


class TestSensorTypeEnum:
    """Tests for SensorType enum values."""

    def test_valid_sensor_types(self):
        """All valid sensor_type values are accepted."""
        from models.rtu_sensor import SensorCreate

        valid_types = ["temperature", "humidity", "analog_input", "relay", "digital_input"]
        for sensor_type in valid_types:
            sensor = SensorCreate(name="Sensor", register_addr=0, sensor_type=sensor_type)
            assert sensor.sensor_type == sensor_type

    def test_invalid_sensor_type_accepted_as_string(self):
        """sensor_type accepts any string (no strict enum in model)."""
        from models.rtu_sensor import SensorCreate

        # Model accepts any string — no validation enum restricting values
        sensor = SensorCreate(name="Sensor", register_addr=0, sensor_type="custom_type")
        assert sensor.sensor_type == "custom_type"