"""Unit tests for RTU Service — business logic layer above repository."""

import pytest
from uuid import uuid4
from unittest.mock import MagicMock, patch


class TestRTUServiceCreation:
    """Tests for RTU creation business logic."""

    @pytest.fixture
    def mock_repo(self):
        """Mock RTUSensorRepository functions."""
        with patch("services.rtu_service.get_db") as mock_get_db:
            mock_driver = MagicMock()
            mock_session = MagicMock()
            mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value = mock_driver
            yield mock_session


class TestSensorServiceCreation:
    """Tests for Sensor creation business logic."""

    def test_create_sensor_validates_register_bounds(self):
        """create_sensor raises ValueError for out-of-bounds register_addr."""
        with patch("services.rtu_service.get_db") as mock_get_db:
            mock_driver = MagicMock()
            mock_get_db.return_value = mock_driver

            from services.rtu_service import RTUService

            service = RTUService()

            with pytest.raises(ValueError) as exc_info:
                service.create_sensor(
                    rtu_id=str(uuid4()),
                    name="Test Sensor",
                    register_addr=500,  # Invalid: > 319
                    register_count=1,
                    sensor_type="temperature",
                )
            assert "500" in str(exc_info.value)


class TestRTUServiceMQTTTopic:
    """Tests for MQTT topic computation."""

    def test_mqtt_topic_computed_on_create(self):
        """RTU mqtt_topic is computed as rtu/{location_id}/{rtu_id}/telemetry."""
        from services.rtu_service import compute_mqtt_topic

        location_id = uuid4()
        rtu_id = uuid4()

        topic = compute_mqtt_topic(location_id, rtu_id)

        assert topic == f"rtu/{location_id}/{rtu_id}/telemetry"
        assert topic.startswith("rtu/")
        assert "/telemetry" in topic

    def test_mqtt_topic_unique_per_rtu(self):
        """Different RTUs at same location produce different MQTT topics."""
        from services.rtu_service import compute_mqtt_topic

        location_id = uuid4()
        rtu_id_1 = uuid4()
        rtu_id_2 = uuid4()

        topic_1 = compute_mqtt_topic(location_id, rtu_id_1)
        topic_2 = compute_mqtt_topic(location_id, rtu_id_2)

        assert topic_1 != topic_2
        assert rtu_id_1.__str__() in topic_1
        assert rtu_id_2.__str__() in topic_2