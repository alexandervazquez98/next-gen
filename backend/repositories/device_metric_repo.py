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
from datetime import datetime
from typing import Any, Optional

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(ts: datetime) -> str:
    """Serialize a datetime as an ISO-8601 string with UTC 'Z' suffix.

    Neo4j's ``datetime()`` function accepts ISO strings. Keeping an explicit
    suffix prevents timezone ambiguity.
    """
    from datetime import timezone as _tz

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_tz.utc)
    return ts.isoformat().replace("+00:00", "Z")


def _serialize_extra(extra: Optional[dict[str, Any]]) -> str:
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
        location_id: Optional[str],
        source_topic: str,
        parser_name: str,
        extra: Optional[dict[str, Any]] = None,
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
        unit: Optional[str],
        ts: datetime,
        tags: Optional[dict[str, Any]] = None,
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

    def get_device(self, device_id: str) -> Optional[dict[str, Any]]:
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


# ---------------------------------------------------------------------------
# Module-level singleton (lazy) — added in Task 3a.3
# ---------------------------------------------------------------------------


_device_metric_repo: Optional[DeviceMetricRepo] = None


def get_device_metric_repo() -> DeviceMetricRepo:
    """Return cached DeviceMetricRepo (singleton, lazy).

    Mirrors the ``get_mqtt_settings()`` / ``get_event_batch_settings()`` pattern
    in ``config.py``. The driver is created on first call via ``database.get_db()``
    so importing this module is free.
    """
    global _device_metric_repo
    if _device_metric_repo is None:
        from database import get_db

        driver = get_db()
        _device_metric_repo = DeviceMetricRepo(driver)
    return _device_metric_repo


def set_device_metric_repo(repo: Optional[DeviceMetricRepo]) -> None:
    """Override the singleton (for tests). Pass ``None`` to clear.

    Used by ``tests/test_device_metric_repo.py::_reset_singleton`` (autouse) and
    by any integration test that needs to inject a mock repo.
    """
    global _device_metric_repo
    _device_metric_repo = repo