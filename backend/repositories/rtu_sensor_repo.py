"""RTU/Sensor Repository — Neo4j persistence layer for RTU nodes and Sensor nodes.

Implements the data access pattern following `topology_repo.py` conventions:
- Uses `database.driver` global for Neo4j sessions
- All functions accept session or use `with driver.session() as session:` pattern
- MERGE for upserts (idempotent), DETACH DELETE for removals
- Validates Modbus register bounds before any write
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import uuid4

from database import get_db

# ── Modbus bounds ─────────────────────────────────────────────────────────────

_MODBUS_REGISTER_MIN = 0
_MODBUS_REGISTER_MAX = 319
_MODBUS_REGISTER_COUNT_MIN = 1
_MODBUS_REGISTER_COUNT_MAX = 4


def _validate_register_bounds(register_addr: int, register_count: int) -> None:
    """Validate Modbus register address and count against spec limits.

    Raises:
        ValueError: If register_addr or register_count are out of bounds,
                    or if (register_addr + register_count - 1) exceeds 319.
    """
    if not (_MODBUS_REGISTER_MIN <= register_addr <= _MODBUS_REGISTER_MAX):
        raise ValueError(
            f"register_addr must be {_MODBUS_REGISTER_MIN}-{_MODBUS_REGISTER_MAX}, got {register_addr}"
        )
    if not (_MODBUS_REGISTER_COUNT_MIN <= register_count <= _MODBUS_REGISTER_COUNT_MAX):
        raise ValueError(
            f"register_count must be {_MODBUS_REGISTER_COUNT_MIN}-{_MODBUS_REGISTER_COUNT_MAX}, got {register_count}"
        )
    last_register = register_addr + register_count - 1
    if last_register > _MODBUS_REGISTER_MAX:
        raise ValueError(
            f"register_addr {register_addr} + register_count {register_count} "
            f"would exceed Modbus limit {_MODBUS_REGISTER_MAX} (last register {last_register})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# RTU Operations
# ─────────────────────────────────────────────────────────────────────────────


def upsert_rtu(
    tx,
    rtu_id: str,
    location_id: str,
    mqtt_topic: str,
    name: str,
    ip: Optional[str],
    status: str,
    mqtt_config: Optional[Dict[str, Any]],
) -> None:
    """Upsert an RTU node with LOCATED_AT relationship to Location.

    Uses MERGE on RTU.id so the operation is idempotent — repeated calls
    update existing nodes rather than creating duplicates.

    Args:
        tx: Neo4j transaction object
        rtu_id: UUID string for the RTU node
        location_id: UUID string of the parent Location node
        mqtt_topic: Full MQTT topic string rtu/{location_id}/{rtu_id}/telemetry
        name: Human-readable RTU name
        ip: Device IP address or None
        status: Operational state (online/offline/unknown)
        mqtt_config: Optional broker configuration dict
    """
    cypher = """
        MERGE (r:RTU {id: $rtu_id})
        SET r.name = $name,
            r.ip = $ip,
            r.layer = 'RTU',
            r.status = $status,
            r.mqtt_topic = $mqtt_topic,
            r.mqtt_config = $mqtt_config,
            r.updated_at = datetime()
        ON CREATE SET r.created_at = datetime()
        WITH r
        MERGE (l:Location {id: $location_id})
        MERGE (r)-[:LOCATED_AT]->(l)
    """
    tx.run(
        cypher,
        rtu_id=rtu_id,
        location_id=location_id,
        mqtt_topic=mqtt_topic,
        name=name,
        ip=ip,
        status=status,
        mqtt_config=mqtt_config,
    )


def get_rtu(tx, rtu_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single RTU node by id.

    Returns:
        Dict of RTU properties including id, name, ip, layer, status, mqtt_topic,
        location_id, created_at, updated_at, or None if not found.
    """
    cypher = """
        MATCH (r:RTU {id: $rtu_id})-[:LOCATED_AT]->(l:Location)
        RETURN r.id as id,
               r.name as name,
               r.ip as ip,
               r.layer as layer,
               r.status as status,
               r.mqtt_topic as mqtt_topic,
               r.mqtt_config as mqtt_config,
               r.created_at as created_at,
               r.updated_at as updated_at,
               l.id as location_id
    """
    result = tx.run(cypher, rtu_id=rtu_id)
    record = result.single()
    if record is None:
        return None
    # Serialize datetime objects
    out = dict(record)
    for key, value in out.items():
        if hasattr(value, "isoformat"):
            out[key] = value.isoformat()
    return out


def list_rtus(tx, location_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all RTU nodes, optionally filtered by location_id.

    Args:
        tx: Neo4j transaction
        location_id: Optional UUID string to filter by location

    Returns:
        List of RTU dicts with all properties
    """
    if location_id:
        cypher = """
            MATCH (r:RTU)-[:LOCATED_AT]->(l:Location {id: $location_id})
            RETURN r.id as id,
                   r.name as name,
                   r.ip as ip,
                   r.layer as layer,
                   r.status as status,
                   r.mqtt_topic as mqtt_topic,
                   r.mqtt_config as mqtt_config,
                   r.created_at as created_at,
                   r.updated_at as updated_at,
                   l.id as location_id
            ORDER BY r.name
        """
        result = tx.run(cypher, location_id=location_id)
    else:
        cypher = """
            MATCH (r:RTU)-[:LOCATED_AT]->(l:Location)
            RETURN r.id as id,
                   r.name as name,
                   r.ip as ip,
                   r.layer as layer,
                   r.status as status,
                   r.mqtt_topic as mqtt_topic,
                   r.mqtt_config as mqtt_config,
                   r.created_at as created_at,
                   r.updated_at as updated_at,
                   l.id as location_id
            ORDER BY r.name
        """
        result = tx.run(cypher)

    rtus = []
    for record in result:
        out = dict(record)
        for key, value in out.items():
            if hasattr(value, "isoformat"):
                out[key] = value.isoformat()
        rtus.append(out)
    return rtus


def update_rtu(
    tx,
    rtu_id: str,
    name: Optional[str] = None,
    ip: Optional[str] = None,
    status: Optional[str] = None,
    mqtt_config: Optional[Dict[str, Any]] = None,
) -> bool:
    """Update RTU properties. Only non-None fields are written.

    Returns:
        True if RTU was found and updated, False if not found.
    """
    set_clauses = ["r.updated_at = datetime()"]
    params: Dict[str, Any] = {"rtu_id": rtu_id}

    if name is not None:
        set_clauses.append("r.name = $name")
        params["name"] = name
    if ip is not None:
        set_clauses.append("r.ip = $ip")
        params["ip"] = ip
    if status is not None:
        set_clauses.append("r.status = $status")
        params["status"] = status
    if mqtt_config is not None:
        set_clauses.append("r.mqtt_config = $mqtt_config")
        params["mqtt_config"] = mqtt_config

    if not set_clauses or len(set_clauses) == 1:
        # Nothing to update (only updated_at would be a no-op)
        return True

    cypher = f"""
        MATCH (r:RTU {{id: $rtu_id}})
        SET {' , '.join(set_clauses)}
        RETURN r.id as id
    """
    result = tx.run(cypher, **params)
    return result.single() is not None


def delete_rtu(tx, rtu_id: str) -> None:
    """Delete an RTU node and cascade-delete all its HAS_SENSOR relationships.

    Since Sensor nodes are children of RTU with no other references,
    DETACH DELETE removes both the RTU and its Sensor children cleanly.
    """
    cypher = """
        MATCH (r:RTU {id: $rtu_id})
        DETACH DELETE r
    """
    tx.run(cypher, rtu_id=rtu_id)


# ─────────────────────────────────────────────────────────────────────────────
# Sensor Operations
# ─────────────────────────────────────────────────────────────────────────────


def upsert_sensor(
    tx,
    sensor_id: str,
    rtu_id: str,
    register_addr: int,
    register_count: int,
    name: str,
    unit: Optional[str],
    sensor_type: str,
) -> None:
    """Upsert a Sensor node with HAS_SENSOR relationship to parent RTU.

    Validates Modbus register bounds before writing.
    Uses composite key (rtu_id, register_addr, sensor_type) for uniqueness.

    Args:
        tx: Neo4j transaction
        sensor_id: UUID string for the Sensor node
        rtu_id: UUID string of the parent RTU node
        register_addr: Modbus register address (0-319)
        register_count: Number of registers consumed (1-4)
        name: Human-readable sensor name
        unit: Unit of measurement or None
        sensor_type: Sensor classification string

    Raises:
        ValueError: If register_addr or register_count violate Modbus bounds
    """
    _validate_register_bounds(register_addr, register_count)

    cypher = """
        MERGE (r:RTU {id: $rtu_id})
        ON CREATE SET r.layer = 'RTU'
        WITH r
        MERGE (r)-[rel:HAS_SENSOR]->(s:Sensor {register_addr: $register_addr, sensor_type: $sensor_type})
        ON CREATE SET s.id = $sensor_id,
                      s.name = $name,
                      s.register_count = $register_count,
                      s.unit = $unit,
                      s.rtu_id = $rtu_id,
                      s.created_at = datetime()
        ON MATCH SET s.name = $name,
                     s.register_count = $register_count,
                     s.unit = $unit,
                     s.updated_at = datetime()
    """
    tx.run(
        cypher,
        sensor_id=sensor_id,
        rtu_id=rtu_id,
        register_addr=register_addr,
        register_count=register_count,
        name=name,
        unit=unit,
        sensor_type=sensor_type,
    )


def get_sensor(tx, sensor_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single Sensor node by id.

    Returns:
        Dict of Sensor properties, or None if not found.
    """
    cypher = """
        MATCH (s:Sensor {id: $sensor_id})
        RETURN s.id as id,
               s.name as name,
               s.register_addr as register_addr,
               s.register_count as register_count,
               s.unit as unit,
               s.sensor_type as sensor_type,
               s.rtu_id as rtu_id,
               s.created_at as created_at,
               s.updated_at as updated_at
    """
    result = tx.run(cypher, sensor_id=sensor_id)
    record = result.single()
    if record is None:
        return None
    out = dict(record)
    for key, value in out.items():
        if hasattr(value, "isoformat"):
            out[key] = value.isoformat()
    return out


def list_sensors(tx, rtu_id: str) -> List[Dict[str, Any]]:
    """List all Sensor nodes for a given RTU.

    Returns:
        List of Sensor dicts ordered by register_addr.
    """
    cypher = """
        MATCH (r:RTU {id: $rtu_id})-[:HAS_SENSOR]->(s:Sensor)
        RETURN s.id as id,
               s.name as name,
               s.register_addr as register_addr,
               s.register_count as register_count,
               s.unit as unit,
               s.sensor_type as sensor_type,
               s.rtu_id as rtu_id,
               s.created_at as created_at,
               s.updated_at as updated_at
        ORDER BY s.register_addr
    """
    result = tx.run(cypher, rtu_id=rtu_id)
    sensors = []
    for record in result:
        out = dict(record)
        for key, value in out.items():
            if hasattr(value, "isoformat"):
                out[key] = value.isoformat()
        sensors.append(out)
    return sensors


def update_sensor(
    tx,
    rtu_id: str,
    sensor_id: str,
    name: Optional[str] = None,
    unit: Optional[str] = None,
) -> bool:
    """Update Sensor properties. Only non-None fields are written.

    Returns:
        True if Sensor was found and updated, False if not found.
    """
    set_clauses = ["s.updated_at = datetime()"]
    params: Dict[str, Any] = {"rtu_id": rtu_id, "sensor_id": sensor_id}

    if name is not None:
        set_clauses.append("s.name = $name")
        params["name"] = name
    if unit is not None:
        set_clauses.append("s.unit = $unit")
        params["unit"] = unit

    if len(set_clauses) == 1:
        return True

    cypher = f"""
        MATCH (r:RTU {{id: $rtu_id}})-[:HAS_SENSOR]->(s:Sensor {{id: $sensor_id}})
        SET {' , '.join(set_clauses)}
        RETURN s.id as id
    """
    result = tx.run(cypher, **params)
    return result.single() is not None


def find_sensor_by_key(
    tx,
    rtu_id: str,
    register_addr: int,
    sensor_type: str,
) -> Optional[Dict[str, Any]]:
    """Find a Sensor node by its composite key (rtu_id, register_addr, sensor_type).

    Returns:
        Dict of Sensor properties, or None if not found.
    """
    cypher = """
        MATCH (r:RTU {id: $rtu_id})-[:HAS_SENSOR]->(s:Sensor {register_addr: $register_addr, sensor_type: $sensor_type})
        RETURN s.id as id,
               s.name as name,
               s.register_addr as register_addr,
               s.register_count as register_count,
               s.unit as unit,
               s.sensor_type as sensor_type,
               s.rtu_id as rtu_id,
               s.created_at as created_at,
               s.updated_at as updated_at
    """
    result = tx.run(cypher, rtu_id=rtu_id, register_addr=register_addr, sensor_type=sensor_type)
    record = result.single()
    if record is None:
        return None
    out = dict(record)
    for key, value in out.items():
        if hasattr(value, "isoformat"):
            out[key] = value.isoformat()
    return out


def delete_sensor(tx, rtu_id: str, sensor_id: str) -> bool:
    """Delete a single Sensor node anchored to its parent RTU.

    Returns:
        True if deleted, False if not found.
    """
    cypher = """
        MATCH (r:RTU {id: $rtu_id})-[:HAS_SENSOR]->(s:Sensor {id: $sensor_id})
        DETACH DELETE s
        RETURN count(s) as deleted
    """
    result = tx.run(cypher, rtu_id=rtu_id, sensor_id=sensor_id)
    record = result.single()
    return record is not None and record["deleted"] == 1