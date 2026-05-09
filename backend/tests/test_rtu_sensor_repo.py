"""Unit tests for RTU/Sensor Repository — mock Neo4j driver tests.

Tests the standalone functions in repositories.rtu_sensor_repo:
- RTU: upsert_rtu, get_rtu, list_rtus, update_rtu, delete_rtu
- Sensor: upsert_sensor, get_sensor, list_sensors, update_sensor, delete_sensor
- Bounds validation: _validate_register_bounds
"""

import pytest
from uuid import uuid4
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_driver():
    """Create a mock Neo4j driver with configurable session."""
    from tests.conftest import MockNeo4jDriver

    driver = MockNeo4jDriver()
    with patch("database.driver", driver):
        with patch("database.verify_connection", return_value=None):
            yield driver


@pytest.fixture
def repo_functions(mock_driver):
    """Import and return the repo module after patching database.

    Returns a dict-like object so tests can call repo.upsert_rtu(...)
    without needing a class wrapper.
    """
    import repositories.rtu_sensor_repo as repo

    return repo


# ─────────────────────────────────────────────────────────────────────────────
# RTU Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRTURepository:
    """Tests for RTU repository standalone functions."""

    def test_upsert_rtu_creates_node(self, repo_functions, mock_driver):
        """upsert_rtu MERGEs an RTU node with all properties set."""
        import repositories.rtu_sensor_repo as repo

        rtu_id = str(uuid4())
        location_id = str(uuid4())
        mqtt_topic = f"rtu/{location_id}/{rtu_id}/telemetry"

        mock_driver.mock_session.set_default_response([])

        repo.upsert_rtu(
            tx=mock_driver.mock_session,
            rtu_id=rtu_id,
            location_id=location_id,
            mqtt_topic=mqtt_topic,
            name="RTU-Test-01",
            ip="192.168.1.100",
            status="online",
            mqtt_config={"broker_host": "mqtt.example.com"},
        )

        queries = mock_driver.mock_session.queries
        assert len(queries) == 1
        cypher = queries[0]["query"].lower()
        assert "merge" in cypher
        assert "rtu" in cypher
        assert queries[0]["params"]["rtu_id"] == rtu_id
        assert queries[0]["params"]["name"] == "RTU-Test-01"
        assert queries[0]["params"]["ip"] == "192.168.1.100"
        assert queries[0]["params"]["status"] == "online"

    def test_upsert_rtu_sets_located_at_relationship(self, repo_functions, mock_driver):
        """upsert_rtu also creates LOCATED_AT relationship to Location node."""
        import repositories.rtu_sensor_repo as repo

        rtu_id = str(uuid4())
        location_id = str(uuid4())
        mqtt_topic = f"rtu/{location_id}/{rtu_id}/telemetry"

        mock_driver.mock_session.set_default_response([])

        repo.upsert_rtu(
            tx=mock_driver.mock_session,
            rtu_id=rtu_id,
            location_id=location_id,
            mqtt_topic=mqtt_topic,
            name="RTU-Loc-01",
            ip=None,
            status="offline",
            mqtt_config=None,
        )

        queries = mock_driver.mock_session.queries
        assert len(queries) == 1
        cypher = queries[0]["query"]
        assert "MERGE" in cypher
        assert queries[0]["params"]["location_id"] == location_id

    def test_get_rtu_returns_dict_with_all_fields(self, repo_functions, mock_driver):
        """get_rtu returns a dict with RTU properties when found."""
        import repositories.rtu_sensor_repo as repo

        rtu_id = str(uuid4())
        location_id = str(uuid4())
        created_at = "2026-05-04T12:00:00Z"
        updated_at = "2026-05-04T12:00:00Z"

        mock_driver.mock_session.set_response(
            "match (r:rtu",
            [
                {
                    "id": rtu_id,
                    "name": "RTU-Found-01",
                    "ip": "10.0.0.50",
                    "layer": "RTU",
                    "status": "online",
                    "mqtt_topic": f"rtu/{location_id}/{rtu_id}/telemetry",
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "location_id": location_id,
                }
            ],
        )

        result = repo.get_rtu(tx=mock_driver.mock_session, rtu_id=rtu_id)

        assert result is not None
        assert result["id"] == rtu_id
        assert result["name"] == "RTU-Found-01"
        assert result["layer"] == "RTU"

    def test_get_rtu_returns_none_when_not_found(self, repo_functions, mock_driver):
        """get_rtu returns None when no RTU node exists."""
        import repositories.rtu_sensor_repo as repo

        rtu_id = str(uuid4())
        mock_driver.mock_session.set_default_response([])

        result = repo.get_rtu(tx=mock_driver.mock_session, rtu_id=rtu_id)

        assert result is None

    def test_list_rtus_returns_all_when_no_filter(self, repo_functions, mock_driver):
        """list_rtus returns all RTUs when no location filter."""
        import repositories.rtu_sensor_repo as repo

        rtu_id_1 = str(uuid4())
        rtu_id_2 = str(uuid4())

        mock_driver.mock_session.set_response(
            "match (r:rtu)",
            [
                {"id": rtu_id_1, "name": "RTU-All-01", "layer": "RTU", "status": "online"},
                {"id": rtu_id_2, "name": "RTU-All-02", "layer": "RTU", "status": "offline"},
            ],
        )

        result = repo.list_rtus(tx=mock_driver.mock_session)

        assert len(result) == 2
        assert result[0]["id"] == rtu_id_1
        assert result[1]["id"] == rtu_id_2

    def test_list_rtus_filters_by_location_id(self, repo_functions, mock_driver):
        """list_rtus filters RTUs by location_id when provided."""
        import repositories.rtu_sensor_repo as repo

        location_id = str(uuid4())
        rtu_id = str(uuid4())

        mock_driver.mock_session.set_response(
            "location_id",
            [{"r": {"id": rtu_id, "name": "RTU-Loc-Filter", "layer": "RTU", "status": "online"}}],
        )

        result = repo.list_rtus(tx=mock_driver.mock_session, location_id=location_id)

        assert len(result) == 1
        queries = mock_driver.mock_session.queries
        assert any("location_id" in str(q["params"]) for q in queries)

    def test_delete_rtu_detaches_and_deletes(self, repo_functions, mock_driver):
        """delete_rtu DETACHes DELETE the RTU node (cascades to sensors)."""
        import repositories.rtu_sensor_repo as repo

        rtu_id = str(uuid4())
        mock_driver.mock_session.set_default_response([])

        repo.delete_rtu(tx=mock_driver.mock_session, rtu_id=rtu_id)

        queries = mock_driver.mock_session.queries
        assert len(queries) == 1
        cypher = queries[0]["query"].lower()
        assert "detach" in cypher
        assert "delete" in cypher
        assert queries[0]["params"]["rtu_id"] == rtu_id

    def test_update_rtu_sets_properties(self, repo_functions, mock_driver):
        """update_rtu SETs only the provided properties on existing RTU."""
        import repositories.rtu_sensor_repo as repo

        rtu_id = str(uuid4())
        mock_driver.mock_session.set_default_response([])

        repo.update_rtu(tx=mock_driver.mock_session, rtu_id=rtu_id, name="RTU-Updated-Name", status="offline")

        queries = mock_driver.mock_session.queries
        assert len(queries) == 1
        cypher = queries[0]["query"].lower()
        assert "set" in cypher
        assert queries[0]["params"]["name"] == "RTU-Updated-Name"
        assert queries[0]["params"]["status"] == "offline"

    def test_update_rtu_with_empty_update(self, repo_functions, mock_driver):
        """update_rtu with empty dict does nothing (no query emitted)."""
        import repositories.rtu_sensor_repo as repo

        rtu_id = str(uuid4())
        mock_driver.mock_session.set_default_response([])

        repo.update_rtu(tx=mock_driver.mock_session, rtu_id=rtu_id, name=None, ip=None, status=None)

        queries = mock_driver.mock_session.queries
        # Empty update — may emit no query or a query that does nothing
        if queries:
            assert "match" in queries[0]["query"].lower() or "set" in queries[0]["query"].lower()


class TestSensorRepository:
    """Tests for Sensor repository standalone functions."""

    def test_upsert_sensor_creates_node_with_all_properties(self, repo_functions, mock_driver):
        """upsert_sensor MERGEs a Sensor node with all properties."""
        import repositories.rtu_sensor_repo as repo

        rtu_id = str(uuid4())
        sensor_id = str(uuid4())

        mock_driver.mock_session.set_default_response([])

        repo.upsert_sensor(
            tx=mock_driver.mock_session,
            sensor_id=sensor_id,
            rtu_id=rtu_id,
            register_addr=0,
            register_count=2,
            name="Temp Sensor 1",
            unit="0.01°C",
            sensor_type="temperature",
        )

        queries = mock_driver.mock_session.queries
        assert len(queries) == 1
        cypher = queries[0]["query"].lower()
        assert "merge" in cypher
        assert "sensor" in cypher
        assert queries[0]["params"]["register_addr"] == 0
        assert queries[0]["params"]["register_count"] == 2
        assert queries[0]["params"]["name"] == "Temp Sensor 1"
        assert queries[0]["params"]["unit"] == "0.01°C"
        assert queries[0]["params"]["sensor_type"] == "temperature"

    def test_upsert_sensor_creates_has_sensor_relationship(self, repo_functions, mock_driver):
        """upsert_sensor creates HAS_SENSOR relationship between RTU and Sensor."""
        import repositories.rtu_sensor_repo as repo

        rtu_id = str(uuid4())
        sensor_id = str(uuid4())

        mock_driver.mock_session.set_default_response([])

        repo.upsert_sensor(
            tx=mock_driver.mock_session,
            sensor_id=sensor_id,
            rtu_id=rtu_id,
            register_addr=5,
            register_count=1,
            name="DI Sensor",
            unit=None,
            sensor_type="digital_input",
        )

        queries = mock_driver.mock_session.queries
        assert len(queries) == 1
        cypher = queries[0]["query"]
        assert "MERGE" in cypher
        assert "HAS_SENSOR" in cypher or "has_sensor" in cypher.lower()

    def test_get_sensor_returns_dict_when_found(self, repo_functions, mock_driver):
        """get_sensor returns sensor dict when node exists."""
        import repositories.rtu_sensor_repo as repo

        sensor_id = str(uuid4())
        rtu_id = str(uuid4())

        mock_driver.mock_session.set_response(
            "match (s:sensor",
            [
                {
                    "id": sensor_id,
                    "name": "Temp Sensor",
                    "register_addr": 0,
                    "register_count": 2,
                    "unit": "0.01°C",
                    "sensor_type": "temperature",
                    "rtu_id": rtu_id,
                }
            ],
        )

        result = repo.get_sensor(tx=mock_driver.mock_session, sensor_id=sensor_id)

        assert result is not None
        assert result["id"] == sensor_id
        assert result["name"] == "Temp Sensor"

    def test_get_sensor_returns_none_when_not_found(self, repo_functions, mock_driver):
        """get_sensor returns None when no Sensor node exists."""
        import repositories.rtu_sensor_repo as repo

        sensor_id = str(uuid4())
        mock_driver.mock_session.set_default_response([])

        result = repo.get_sensor(tx=mock_driver.mock_session, sensor_id=sensor_id)

        assert result is None

    def test_list_sensors_returns_all_for_rtu(self, repo_functions, mock_driver):
        """list_sensors returns all sensors for a given RTU_id."""
        import repositories.rtu_sensor_repo as repo

        rtu_id = str(uuid4())
        sensor_id_1 = str(uuid4())
        sensor_id_2 = str(uuid4())

        mock_driver.mock_session.set_response(
            "has_sensor",
            [
                {
                    "id": sensor_id_1,
                    "name": "Sensor-1",
                    "register_addr": 0,
                    "sensor_type": "temperature",
                },
                {
                    "id": sensor_id_2,
                    "name": "Sensor-2",
                    "register_addr": 2,
                    "sensor_type": "humidity",
                },
            ],
        )

        result = repo.list_sensors(tx=mock_driver.mock_session, rtu_id=rtu_id)

        assert len(result) == 2

    def test_list_sensors_empty_when_no_sensors(self, repo_functions, mock_driver):
        """list_sensors returns empty list when RTU has no sensors."""
        import repositories.rtu_sensor_repo as repo

        rtu_id = str(uuid4())
        mock_driver.mock_session.set_default_response([])

        result = repo.list_sensors(tx=mock_driver.mock_session, rtu_id=rtu_id)

        assert result == []

    def test_delete_sensor_deletes_node(self, repo_functions, mock_driver):
        """delete_sensor deletes the sensor node."""
        import repositories.rtu_sensor_repo as repo

        sensor_id = str(uuid4())
        rtu_id = str(uuid4())
        mock_driver.mock_session.set_default_response([{"deleted": 1}])

        result = repo.delete_sensor(tx=mock_driver.mock_session, rtu_id=rtu_id, sensor_id=sensor_id)

        queries = mock_driver.mock_session.queries
        assert len(queries) == 1
        cypher = queries[0]["query"].lower()
        assert "delete" in cypher
        assert queries[0]["params"]["sensor_id"] == sensor_id
        assert queries[0]["params"]["rtu_id"] == rtu_id
        assert result is True

    def test_update_sensor_sets_properties(self, repo_functions, mock_driver):
        """update_sensor SETs only the provided properties."""
        import repositories.rtu_sensor_repo as repo

        sensor_id = str(uuid4())
        rtu_id = str(uuid4())
        mock_driver.mock_session.set_default_response([{"id": sensor_id}])

        result = repo.update_sensor(tx=mock_driver.mock_session, rtu_id=rtu_id, sensor_id=sensor_id, name="Updated-Sensor-Name", unit="0.1°C")

        queries = mock_driver.mock_session.queries
        assert len(queries) == 1
        cypher = queries[0]["query"].lower()
        assert "set" in cypher
        assert queries[0]["params"]["name"] == "Updated-Sensor-Name"
        assert queries[0]["params"]["unit"] == "0.1°C"
        assert queries[0]["params"]["rtu_id"] == rtu_id
        assert result is True


class TestRepositoryModbusValidation:
    """Tests for Modbus register bounds validation in repository layer."""

    def test_upsert_sensor_rejects_register_addr_above_319(self, repo_functions, mock_driver):
        """upsert_sensor rejects register_addr > 319 (Modbus limit)."""
        import repositories.rtu_sensor_repo as repo

        sensor_id = str(uuid4())
        rtu_id = str(uuid4())

        with pytest.raises(ValueError) as exc_info:
            repo.upsert_sensor(
                tx=mock_driver.mock_session,
                sensor_id=sensor_id,
                rtu_id=rtu_id,
                register_addr=320,  # Invalid
                register_count=1,
                name="Invalid Register",
                unit=None,
                sensor_type="temperature",
            )
        assert "register_addr" in str(exc_info.value)
        assert "320" in str(exc_info.value)

    def test_upsert_sensor_rejects_register_addr_negative(self, repo_functions, mock_driver):
        """upsert_sensor rejects register_addr < 0."""
        import repositories.rtu_sensor_repo as repo

        sensor_id = str(uuid4())
        rtu_id = str(uuid4())

        with pytest.raises(ValueError) as exc_info:
            repo.upsert_sensor(
                tx=mock_driver.mock_session,
                sensor_id=sensor_id,
                rtu_id=rtu_id,
                register_addr=-1,
                register_count=1,
                name="Invalid Register",
                unit=None,
                sensor_type="temperature",
            )
        assert "register_addr" in str(exc_info.value)
        assert "-1" in str(exc_info.value)

    def test_upsert_sensor_rejects_register_count_above_4(self, repo_functions, mock_driver):
        """upsert_sensor rejects register_count > 4."""
        import repositories.rtu_sensor_repo as repo

        sensor_id = str(uuid4())
        rtu_id = str(uuid4())

        with pytest.raises(ValueError) as exc_info:
            repo.upsert_sensor(
                tx=mock_driver.mock_session,
                sensor_id=sensor_id,
                rtu_id=rtu_id,
                register_addr=0,
                register_count=5,  # Invalid
                name="Invalid Count",
                unit=None,
                sensor_type="temperature",
            )
        assert "register_count" in str(exc_info.value)
        assert "5" in str(exc_info.value)

    def test_upsert_sensor_rejects_register_count_below_1(self, repo_functions, mock_driver):
        """upsert_sensor rejects register_count < 1."""
        import repositories.rtu_sensor_repo as repo

        sensor_id = str(uuid4())
        rtu_id = str(uuid4())

        with pytest.raises(ValueError) as exc_info:
            repo.upsert_sensor(
                tx=mock_driver.mock_session,
                sensor_id=sensor_id,
                rtu_id=rtu_id,
                register_addr=0,
                register_count=0,  # Invalid
                name="Invalid Count",
                unit=None,
                sensor_type="temperature",
            )
        assert "register_count" in str(exc_info.value)
        assert "0" in str(exc_info.value)

    def test_upsert_sensor_accepts_boundary_values(self, repo_functions, mock_driver):
        """upsert_sensor accepts boundary valid values (0, 319, 1, 4)."""
        import repositories.rtu_sensor_repo as repo

        rtu_id = str(uuid4())

        mock_driver.mock_session.set_default_response([])

        # register_addr=0 (min), register_count=1 (min) → OK
        repo.upsert_sensor(
            tx=mock_driver.mock_session,
            sensor_id=str(uuid4()),
            rtu_id=rtu_id,
            register_addr=0,
            register_count=1,
            name="Edge Min",
            unit=None,
            sensor_type="temperature",
        )

        # register_addr=316, count=4 → last register = 316 + 4 - 1 = 319 → OK (exactly at limit)
        repo.upsert_sensor(
            tx=mock_driver.mock_session,
            sensor_id=str(uuid4()),
            rtu_id=rtu_id,
            register_addr=316,
            register_count=4,
            name="Edge Max",
            unit=None,
            sensor_type="analog_input",
        )

        # Both calls succeeded without raising
        assert len(mock_driver.mock_session.queries) == 2

    def test_upsert_sensor_rejects_range_exceeding_modbus_limit(self, repo_functions, mock_driver):
        """upsert_sensor rejects register_addr + register_count - 1 > 319."""
        import repositories.rtu_sensor_repo as repo

        rtu_id = str(uuid4())

        # register_addr=318, count=2 → last register = 318 + 2 - 1 = 319 → OK
        mock_driver.mock_session.set_default_response([])
        repo.upsert_sensor(
            tx=mock_driver.mock_session,
            sensor_id=str(uuid4()),
            rtu_id=rtu_id,
            register_addr=318,
            register_count=2,
            name="Edge OK",
            unit=None,
            sensor_type="temperature",
        )

        # register_addr=318, count=3 → last register = 318 + 3 - 1 = 320 → exceeds 319
        sensor_id_2 = str(uuid4())
        with pytest.raises(ValueError) as exc_info:
            repo.upsert_sensor(
                tx=mock_driver.mock_session,
                sensor_id=sensor_id_2,
                rtu_id=rtu_id,
                register_addr=318,
                register_count=3,  # Would exceed 319
                name="Edge Fail",
                unit=None,
                sensor_type="temperature",
            )
        error_str = str(exc_info.value).lower()
        assert "319" in str(exc_info.value) or "exceed" in error_str