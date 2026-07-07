"""Device + Metric repository for the generic MQTT persistence model.

Replaces RTU/Sensor for new MQTT messages. Idempotent upserts via MERGE so the
same device or metric can be written repeatedly without creating duplicates.

Schema (see ``backend/migrations/002_generic_device_schema.cypher``):
- :Device { id (unique), name, location_id, source_topic, parser_name,
            first_seen, last_seen, extra (JSON string) }
- :Metric { id (unique), device_id, name, last_value, unit,
            last_ts, tags (JSON string) }
- (:Device)-[:HAS_METRIC]->(:Metric)

Design reference: design \u00a74. Implementation notes:

- The repo uses the SYNC neo4j driver (matching ``topology_repo`` /
  ``rtu_sensor_repo`` \u2014 neo4j 5.x in this project, not async).
- ``extra`` and ``tags`` are stored as JSON strings (not maps) to avoid Neo4j
  property-name cardinality bloat. Read paths deserialize on demand.
- All public methods wrap driver exceptions in ``RuntimeError`` with context
  so callers (``services.mqtt.subscriber._persist_reading``) can NACK
  uniformly on persistence failure (PR3b design).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, cast

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cypher queries (single source of truth, used by repo methods)
# ---------------------------------------------------------------------------

_UPSERT_DEVICE_CYPHER = """
MERGE (d:Device {id: $device_id})
ON CREATE SET
    d.name = $name,
    d.location_id = $location_id,
    d.source_topic = $source_topic,
    d.parser_name = $parser_name,
    d.first_seen = datetime($ts),
    d.last_seen = datetime($ts),
    d.extra = $extra_json
ON MATCH SET
    d.name = COALESCE($name, d.name),
    d.last_seen = datetime($ts),
    d.extra = $extra_json
RETURN d.id AS id,
       d.name AS name,
       d.location_id AS location_id,
       d.source_topic AS source_topic,
       d.parser_name AS parser_name,
       d.first_seen AS first_seen,
       d.last_seen AS last_seen,
       d.extra AS extra
"""

_UPSERT_METRIC_CYPHER = """
MERGE (m:Metric {id: $metric_id})
ON CREATE SET
    m.device_id = $device_id,
    m.name = $name,
    m.last_value = $value,
    m.unit = $unit,
    m.last_ts = datetime($ts),
    m.tags = $tags_json
ON MATCH SET
    m.last_value = $value,
    m.last_ts = datetime($ts),
    m.tags = $tags_json
WITH m
MATCH (d:Device {id: $device_id})
MERGE (d)-[r:HAS_METRIC]->(m)
RETURN m.id AS id,
       m.device_id AS device_id,
       m.name AS name,
       m.last_value AS last_value,
       m.unit AS unit,
       m.last_ts AS last_ts,
       m.tags AS tags
"""

_GET_DEVICE_CYPHER = """
MATCH (d:Device {id: $device_id})
RETURN d.id AS id,
       d.name AS name,
       d.location_id AS location_id,
       d.source_topic AS source_topic,
       d.parser_name AS parser_name,
       d.first_seen AS first_seen,
       d.last_seen AS last_seen,
       d.extra AS extra
"""

_LIST_METRICS_CYPHER = """
MATCH (:Device {id: $device_id})-[:HAS_METRIC]->(m:Metric)
RETURN m.id AS id,
       m.device_id AS device_id,
       m.name AS name,
       m.last_value AS last_value,
       m.unit AS unit,
       m.last_ts AS last_ts,
       m.tags AS tags
ORDER BY m.name
"""

_LIST_DEVICES_CYPHER = """
MATCH (d:Device)
WHERE d.source_topic IS NOT NULL
OPTIONAL MATCH (d)-[:HAS_METRIC]->(m:Metric)
OPTIONAL MATCH (m)-[:HAS_MQTT_MAPPING]->(mapping:MqttMetricMapping)
WITH d,
     count(DISTINCT m) AS metric_count,
     count(DISTINCT CASE WHEN mapping.status = 'APPROVED' THEN m END) AS mapped_metrics_count
RETURN d.id AS id,
       d.name AS name,
       d.location_id AS location_id,
       d.source_topic AS source_topic,
       d.parser_name AS parser_name,
       d.first_seen AS first_seen,
       d.last_seen AS last_seen,
       d.extra AS extra,
       metric_count AS metric_count,
       mapped_metrics_count AS mapped_metrics_count
ORDER BY d.id
"""

_LIST_DEVICE_METRICS_WITH_MAPPING_STATUS_CYPHER = """
MATCH (d:Device {id: $device_id})-[:HAS_METRIC]->(m:Metric)
WHERE d.source_topic IS NOT NULL
OPTIONAL MATCH (m)-[:HAS_MQTT_MAPPING]->(mapping:MqttMetricMapping)
WITH m,
     CASE
        WHEN count(mapping) = 0 THEN 'UNMAPPED'
        WHEN any(status IN collect(mapping.status) WHERE status = 'APPROVED') THEN 'APPROVED'
        WHEN any(status IN collect(mapping.status) WHERE status = 'DRAFT') THEN 'DRAFT'
        ELSE 'REVOKED'
     END AS mapping_status
RETURN m.id AS id,
       m.device_id AS device_id,
       m.name AS name,
       m.last_value AS last_value,
       m.unit AS unit,
       m.last_ts AS last_ts,
       m.tags AS tags,
       mapping_status AS mapping_status
ORDER BY m.name
"""

_LIST_LATEST_READINGS_CYPHER = """
MATCH (d:Device)-[:HAS_METRIC]->(m:Metric)
WHERE d.source_topic IS NOT NULL
OPTIONAL MATCH (m)-[:HAS_MQTT_MAPPING]->(mapping:MqttMetricMapping)
WITH d, m,
     CASE
        WHEN count(mapping) = 0 THEN 'UNMAPPED'
        WHEN any(status IN collect(mapping.status) WHERE status = 'APPROVED') THEN 'APPROVED'
        WHEN any(status IN collect(mapping.status) WHERE status = 'DRAFT') THEN 'DRAFT'
        ELSE 'REVOKED'
     END AS mapping_status
RETURN m.id AS id,
       m.device_id AS device_id,
       m.name AS name,
       m.last_value AS last_value,
       m.unit AS unit,
       m.last_ts AS last_ts,
       m.tags AS tags,
       mapping_status AS mapping_status
ORDER BY d.id, m.name
LIMIT $limit
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(ts: datetime) -> str:
    """Serialize a datetime as an ISO-8601 string with UTC 'Z' suffix.

    Neo4j's ``datetime()`` function accepts ISO strings. Keeping an explicit
    suffix prevents timezone ambiguity.
    """

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.isoformat().replace("+00:00", "Z")


def _serialize_extra(extra: dict[str, Any] | None) -> str:
    """Serialize the ``extra`` dict to a JSON string.

    ``None`` becomes ``'{}'`` so the column is never NULL (Neo4j indexes NULL
    poorly and ``MATCH ... WHERE d.extra IS NULL`` is rarely what callers want).
    """
    if extra is None:
        return "{}"
    return json.dumps(extra, default=str)


def _record_to_device(record: dict[str, Any]) -> dict[str, Any]:
    """Convert a Neo4j record (or our mock shape) to a plain dict.

    Handles both real Neo4j ``Record`` objects (``record['key']``) and our
    test mock records (dicts with a single ``'d'`` key holding the node dict).
    """
    if "d" in record and isinstance(record["d"], dict):
        node = record["d"]
        return {
            "id": node.get("id"),
            "name": node.get("name"),
            "location_id": node.get("location_id"),
            "source_topic": node.get("source_topic"),
            "parser_name": node.get("parser_name"),
            "first_seen": _iso_dt(node.get("first_seen")),
            "last_seen": _iso_dt(node.get("last_seen")),
            "extra": _deserialize_extra(node.get("extra")),
        }
    # Real neo4j Record path
    return {
        "id": _get(record, "id"),
        "name": _get(record, "name"),
        "location_id": _get(record, "location_id"),
        "source_topic": _get(record, "source_topic"),
        "parser_name": _get(record, "parser_name"),
        "first_seen": _iso_dt(_get(record, "first_seen")),
        "last_seen": _iso_dt(_get(record, "last_seen")),
        "extra": _deserialize_extra(_get(record, "extra")),
    }


def _record_to_metric(record: dict[str, Any]) -> dict[str, Any]:
    """Convert a Neo4j record (or mock shape) to a metric dict."""
    if "m" in record and isinstance(record["m"], dict):
        node = record["m"]
        return {
            "id": node.get("id"),
            "device_id": node.get("device_id"),
            "name": node.get("name"),
            "last_value": node.get("last_value"),
            "unit": node.get("unit"),
            "last_ts": _iso_dt(node.get("last_ts")),
            "tags": _deserialize_extra(node.get("tags")),
        }
    return {
        "id": _get(record, "id"),
        "device_id": _get(record, "device_id"),
        "name": _get(record, "name"),
        "last_value": _get(record, "last_value"),
        "unit": _get(record, "unit"),
        "last_ts": _iso_dt(_get(record, "last_ts")),
        "tags": _deserialize_extra(_get(record, "tags")),
    }


def _get(record: Any, key: str) -> Any:
    """Get a key from a real neo4j ``Record`` (supports ``record['key']``)."""
    try:
        return record[key]
    except (KeyError, TypeError):
        try:
            return record.get(key)
        except AttributeError:
            return None


def _iso_dt(value: Any) -> Any:
    """Convert datetime-like values to ISO strings (idempotent on strings)."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        s = value.isoformat()
        return s.replace("+00:00", "Z") if s.endswith("+00:00") else s
    return value


def _deserialize_extra(value: Any) -> Any:
    """Parse a JSON-string ``extra``/``tags`` column. Returns dict or original value.

    If the stored value is already a dict (older migration or different code
    path wrote it that way), return it as-is. If it's None, return ``{}``.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            logger.warning("device_metric_repo: malformed extra/tags JSON: %r", value)
            return {}
    return value


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class DeviceMetricRepo:
    """Repository for Device and Metric nodes (idempotent upserts)."""

    def __init__(self, driver: Any) -> None:
        self._driver = driver

    # ----- write -----------------------------------------------------------

    def upsert_device(
        self,
        device_id: str,
        name: str,
        location_id: str | None,
        source_topic: str,
        parser_name: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or update a Device node. Idempotent (MERGE).

        Returns a device dict with keys: id, name, location_id, source_topic,
        parser_name, first_seen, last_seen, extra.
        """
        ts = datetime.now(__import__("datetime").timezone.utc)
        params = {
            "device_id": device_id,
            "name": name,
            "location_id": location_id,
            "source_topic": source_topic,
            "parser_name": parser_name,
            "extra_json": _serialize_extra(extra),
            "ts": _iso(ts),
        }
        try:
            with self._driver.session() as session:
                result = session.run(_UPSERT_DEVICE_CYPHER, **params)
                record = result.single() if hasattr(result, "single") else None
                if record is None:
                    return {"id": device_id}
                return _record_to_device(record)
        except Exception as exc:
            logger.exception("upsert_device failed for %s", device_id)
            raise RuntimeError(f"upsert_device failed for {device_id!r}: {exc}") from exc

    def upsert_metric(
        self,
        metric_id: str,
        device_id: str,
        name: str,
        value: Any,
        unit: str | None,
        ts: datetime,
        tags: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or update a Metric node and HAS_METRIC relationship. Idempotent.

        Returns a metric dict with keys: id, device_id, name, last_value, unit,
        last_ts, tags.
        """
        params = {
            "metric_id": metric_id,
            "device_id": device_id,
            "name": name,
            "value": value,
            "unit": unit,
            "ts": _iso(ts),
            "tags_json": _serialize_extra(tags),
        }
        try:
            with self._driver.session() as session:
                result = session.run(_UPSERT_METRIC_CYPHER, **params)
                record = result.single() if hasattr(result, "single") else None
                if record is None:
                    return {"id": metric_id}
                return _record_to_metric(record)
        except Exception as exc:
            logger.exception("upsert_metric failed for %s", metric_id)
            raise RuntimeError(f"upsert_metric failed for {metric_id!r}: {exc}") from exc

    # ----- read ------------------------------------------------------------

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        """Return the device dict or None."""
        try:
            with self._driver.session() as session:
                result = session.run(_GET_DEVICE_CYPHER, device_id=device_id)
                record = result.single() if hasattr(result, "single") else None
                if record is None:
                    return None
                return _record_to_device(record)
        except Exception as exc:
            logger.exception("get_device failed for %s", device_id)
            raise RuntimeError(f"get_device failed for {device_id!r}: {exc}") from exc

    def list_metrics(self, device_id: str) -> list[dict[str, Any]]:
        """Return all metrics for a device. Empty list if device unknown."""
        try:
            with self._driver.session() as session:
                result = session.run(_LIST_METRICS_CYPHER, device_id=device_id)
                # result may be iterable (real neo4j) or a MockNeo4jResult
                records = list(result)
                return [_record_to_metric(r) for r in records]
        except Exception as exc:
            logger.exception("list_metrics failed for %s", device_id)
            raise RuntimeError(f"list_metrics failed for {device_id!r}: {exc}") from exc

    def list_devices(self) -> list[dict[str, Any]]:
        """Return raw MQTT devices with mapping counts for API visibility."""
        try:
            with self._driver.session() as session:
                result = session.run(_LIST_DEVICES_CYPHER)
                devices = []
                for record in list(result):
                    device = _record_to_device(record)
                    metric_count = int(_get(record, "metric_count") or 0)
                    mapped_count = int(_get(record, "mapped_metrics_count") or 0)
                    device["metric_count"] = metric_count
                    device["mapped_metrics_count"] = mapped_count
                    device["unmapped_metrics_count"] = max(metric_count - mapped_count, 0)
                    devices.append(device)
                return devices
        except Exception as exc:
            logger.exception("list_devices failed")
            raise RuntimeError(f"list_devices failed: {exc}") from exc

    def list_metrics_with_mapping_status(self, device_id: str) -> list[dict[str, Any]]:
        """Return latest device metrics annotated with mapping lifecycle status."""
        try:
            with self._driver.session() as session:
                result = session.run(
                    _LIST_DEVICE_METRICS_WITH_MAPPING_STATUS_CYPHER,
                    device_id=device_id,
                )
                metrics = []
                for record in list(result):
                    metric = _record_to_metric(record)
                    metric["mapping_status"] = _get(record, "mapping_status") or "UNMAPPED"
                    metrics.append(metric)
                return metrics
        except Exception as exc:
            logger.exception("list_metrics_with_mapping_status failed for %s", device_id)
            raise RuntimeError(
                f"list_metrics_with_mapping_status failed for {device_id!r}: {exc}"
            ) from exc

    def list_latest_readings(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return latest raw MQTT metric snapshots across devices."""
        try:
            with self._driver.session() as session:
                result = session.run(_LIST_LATEST_READINGS_CYPHER, limit=limit)
                readings = []
                for record in list(result):
                    metric = _record_to_metric(record)
                    metric["mapping_status"] = _get(record, "mapping_status") or "UNMAPPED"
                    readings.append(metric)
                return readings
        except Exception as exc:
            logger.exception("list_latest_readings failed")
            raise RuntimeError(f"list_latest_readings failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Module-level singleton (lazy) — added in Task 3a.3
# ---------------------------------------------------------------------------


_device_metric_repo: DeviceMetricRepo | None = None


def get_device_metric_repo() -> DeviceMetricRepo:
    """Return cached DeviceMetricRepo (singleton, lazy).

    Mirrors the ``get_mqtt_settings()`` / ``get_event_batch_settings()`` pattern
    in ``config.py``. The driver is created on first call via ``database.get_db()``
    so importing this module is free.
    """
    global _device_metric_repo
    if _device_metric_repo is None:
        from database import get_db

        # database.get_db() is untyped at the source (database.py:21,27,33
        # all lack return annotations). This is a pre-existing condition
        # shared with topology_repo and rtu_sensor_repo. The runtime contract
        # is documented in repositories/__init__.py: every Neo4j-backed module
        # here takes a driver via get_db() or as a constructor arg.
        driver = cast(Any, get_db())  # type: ignore[no-untyped-call]
        _device_metric_repo = DeviceMetricRepo(driver)
    return _device_metric_repo


def set_device_metric_repo(repo: DeviceMetricRepo | None) -> None:
    """Override the singleton (for tests). Pass ``None`` to clear.

    Used by ``tests/test_device_metric_repo.py::_reset_singleton`` (autouse) and
    by any integration test that needs to inject a mock repo.
    """
    global _device_metric_repo
    _device_metric_repo = repo
