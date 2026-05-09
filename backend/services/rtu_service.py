"""RTU/Sensor Service ÔÇö business logic layer above the repository.

This service:
- Wraps repository functions with transaction management
- Computes mqtt_topic from location_id + rtu_id
- Provides get-or-create semantics for RTU/Sensor
- Validates business rules (Modbus register bounds) before calling repo
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import UUID, uuid4

from database import get_db
from repositories import rtu_sensor_repo as repo


# ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ
# Helpers
# ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ


def compute_mqtt_topic(location_id: UUID, rtu_id: UUID) -> str:
    """Compute the canonical MQTT topic for an RTU.

    Topic structure: rtu/{location_id}/{rtu_id}/telemetry

    This is deterministic ÔÇö same location_id + rtu_id always produces the same topic.
    """
    return f"rtu/{location_id}/{rtu_id}/telemetry"


# ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ
# RTU Service
# ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ


class RTUService:
    """Business logic layer for RTU and Sensor operations.

    All methods manage their own Neo4j sessions and transactions.
    """

    def __init__(self, driver=None):
        self._driver = driver or get_db()

    # ÔöÇÔöÇ RTU operations ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

    def create_rtu(
        self,
        name: str,
        location_id: UUID,
        ip: Optional[str] = None,
        mqtt_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new RTU node.

        Computes mqtt_topic from location_id + auto-generated rtu_id.
        """
        rtu_id = uuid4()
        mqtt_topic = compute_mqtt_topic(location_id, rtu_id)

        with self._driver.session() as session:
            repo.upsert_rtu(
                tx=session,
                rtu_id=str(rtu_id),
                location_id=str(location_id),
                mqtt_topic=mqtt_topic,
                name=name,
                ip=ip,
                status="unknown",
                mqtt_config=mqtt_config,
            )

        return self.get_rtu(str(rtu_id))

    def get_rtu(self, rtu_id: str) -> Optional[Dict[str, Any]]:
        """Get a single RTU by id."""
        with self._driver.session() as session:
            return repo.get_rtu(tx=session, rtu_id=rtu_id)

    def list_rtus(self, location_id: Optional[UUID] = None) -> List[Dict[str, Any]]:
        """List RTUs, optionally filtered by location_id."""
        with self._driver.session() as session:
            return repo.list_rtus(
                tx=session,
                location_id=str(location_id) if location_id else None,
            )

    def update_rtu(
        self,
        rtu_id: str,
        name: Optional[str] = None,
        ip: Optional[str] = None,
        status: Optional[str] = None,
        mqtt_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update RTU properties. Returns updated RTU or None if not found."""
        with self._driver.session() as session:
            found = repo.update_rtu(
                tx=session,
                rtu_id=rtu_id,
                name=name,
                ip=ip,
                status=status,
                mqtt_config=mqtt_config,
            )
        if not found:
            return None
        return self.get_rtu(rtu_id)

    def delete_rtu(self, rtu_id: str) -> bool:
        """Delete RTU and all its Sensors. Returns True if deleted."""
        with self._driver.session() as session:
            # Check existence first
            existing = repo.get_rtu(tx=session, rtu_id=rtu_id)
            if not existing:
                return False
            repo.delete_rtu(tx=session, rtu_id=rtu_id)
            return True

    # ÔöÇÔöÇ Sensor operations ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

    def create_sensor(
        self,
        rtu_id: str,
        name: str,
        register_addr: int,
        register_count: int = 1,
        unit: Optional[str] = None,
        sensor_type: str = "analog_input",
    ) -> Dict[str, Any]:
        """Create a new Sensor attached to an RTU.

        Validates Modbus register bounds before writing.

        Raises:
            ValueError: If register_addr or register_count violate Modbus limits.
        """
        # Validate bounds via repo (raises ValueError if invalid)
        repo._validate_register_bounds(register_addr, register_count)

        sensor_id = uuid4()

        with self._driver.session() as session:
            repo.upsert_sensor(
                tx=session,
                sensor_id=str(sensor_id),
                rtu_id=rtu_id,
                register_addr=register_addr,
                register_count=register_count,
                name=name,
                unit=unit,
                sensor_type=sensor_type,
            )

        return self.get_sensor(str(sensor_id))

    def get_sensor(self, sensor_id: str) -> Optional[Dict[str, Any]]:
        """Get a single Sensor by id."""
        with self._driver.session() as session:
            return repo.get_sensor(tx=session, sensor_id=sensor_id)

    def list_sensors(self, rtu_id: str) -> List[Dict[str, Any]]:
        """List all Sensors for an RTU."""
        with self._driver.session() as session:
            return repo.list_sensors(tx=session, rtu_id=rtu_id)

    def update_sensor(
        self,
        rtu_id: str,
        sensor_id: str,
        name: Optional[str] = None,
        unit: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update Sensor properties. Returns updated Sensor or None if not found."""
        with self._driver.session() as session:
            found = repo.update_sensor(
                tx=session,
                rtu_id=rtu_id,
                sensor_id=sensor_id,
                name=name,
                unit=unit,
            )
        if not found:
            return None
        return self.get_sensor(sensor_id)

    def delete_sensor(self, rtu_id: str, sensor_id: str) -> bool:
        """Delete a single Sensor anchored to its parent RTU. Returns True if deleted."""
        with self._driver.session() as session:
            return repo.delete_sensor(tx=session, rtu_id=rtu_id, sensor_id=sensor_id)

    # ÔöÇÔöÇ MQTT Subscriber helpers (get-or-create semantics) ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

    def get_or_create_rtu(
        self,
        rtu_id: str,
        location_id: str,
        name: str,
        ip: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get an existing RTU or create a new one if not found.

        Used by the MQTT subscriber to upsert RTU nodes from incoming telemetry.
        Computes mqtt_topic from location_id + rtu_id.
        """
        mqtt_topic = compute_mqtt_topic(UUID(location_id), UUID(rtu_id))

        with self._driver.session() as session:
            existing = repo.get_rtu(tx=session, rtu_id=rtu_id)
            if existing:
                return existing

            repo.upsert_rtu(
                tx=session,
                rtu_id=rtu_id,
                location_id=location_id,
                mqtt_topic=mqtt_topic,
                name=name,
                ip=ip,
                status="online",
                mqtt_config=None,
            )

            return repo.get_rtu(tx=session, rtu_id=rtu_id)

    def get_or_create_sensor(
        self,
        rtu_id: str,
        register_addr: int,
        name: str,
        unit: Optional[str] = None,
        sensor_type: str = "analog_input",
    ) -> Dict[str, Any]:
        """Get an existing Sensor or create a new one if not found.

        Used by the MQTT subscriber to upsert Sensor nodes from incoming telemetry.
        The sensor is identified by (rtu_id, register_addr, sensor_type).

        Raises:
            ValueError: If register_addr or register_count violate Modbus limits.
        """
        repo._validate_register_bounds(register_addr, register_count=1)

        sensor_id = uuid4()

        with self._driver.session() as session:
            existing = repo.find_sensor_by_key(
                tx=session,
                rtu_id=rtu_id,
                register_addr=register_addr,
                sensor_type=sensor_type,
            )
            if existing:
                return existing

            repo.upsert_sensor(
                tx=session,
                sensor_id=str(sensor_id),
                rtu_id=rtu_id,
                register_addr=register_addr,
                register_count=1,
                name=name,
                unit=unit,
                sensor_type=sensor_type,
            )

        return self.get_sensor(str(sensor_id))
