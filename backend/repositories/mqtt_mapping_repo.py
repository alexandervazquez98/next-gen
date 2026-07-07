"""Repository for MQTT metric-to-monitoring mappings (slice 1).

The repository enforces lifecycle state transitions and source/target checks:
DRAFT -> APPROVED -> REVOKED.

This layer intentionally avoids business policy; it only persists and validates
model constraints that affect persistence consistency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from database import get_db


# Lifecycle constants kept as plain strings for DB neutrality.
MAPPING_STATUS_DRAFT = "DRAFT"
MAPPING_STATUS_APPROVED = "APPROVED"
MAPPING_STATUS_REVOKED = "REVOKED"


class MappingNotFoundError(RuntimeError):
    """Raised when a mapping id or source reference is unknown."""


class MappingConflictError(RuntimeError):
    """Raised when lifecycle state transitions violate repository invariants."""


class MqttMappingRepo:
    """Persist and query ``MqttMetricMapping`` nodes."""

    def __init__(self, driver: Any | None = None):
        self._driver = driver if driver is not None else get_db()

    # ── private helpers ──────────────────────────────────────────────────────

    def _session(self):
        return self._driver.session() if hasattr(self._driver, "session") else self._driver

    @staticmethod
    def _record(row: Any, keys: tuple[str, ...]) -> dict[str, Any] | None:
        if row is None:
            return None
        if isinstance(row, dict):
            return {key: row.get(key) for key in keys if key in row}
        if hasattr(row, "__iter__") and not hasattr(row, "keys"):
            # Neo4j records are not always regular mappings.
            return {key: row[key] for key in keys if key in row}
        try:
            return {key: row[key] for key in keys if row[key] is not None or key in row}
        except Exception:
            return {key: row.get(key) for key in keys}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(tz=UTC).replace(microsecond=0)

    @staticmethod
    def _to_iso(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.isoformat()

    # ── existence checks ────────────────────────────────────────────────────

    def _require_device_exists(self, tx: Any, source_device_id: str) -> None:
        query = """
        MATCH (d:Device)
            WHERE d.id = $source_device_id
        WITH count(d) AS c
        RETURN c
        """
        row = tx.run(query, source_device_id=source_device_id).single()
        count = row["c"] if row else 0
        if int(count or 0) == 0:
            raise MappingNotFoundError(f"Source device not found: {source_device_id}")

    def _require_metric_target_exists(self, tx: Any, target_ci_id: str) -> None:
        query = """
        MATCH (c:CI)
            WHERE c.id = $target_ci_id
        WITH count(c) AS c
        RETURN c
        """
        row = tx.run(query, target_ci_id=target_ci_id).single()
        count = row["c"] if row else 0
        if int(count or 0) == 0:
            raise MappingNotFoundError(f"Target CI not found: {target_ci_id}")

    def _require_metric_def_exists(self, tx: Any, target_metric_def_id: str) -> None:
        query = """
        MATCH (md:MetricDef)
            WHERE md.id = $target_metric_def_id
        WITH count(md) AS c
        RETURN c
        """
        row = tx.run(query, target_metric_def_id=target_metric_def_id).single()
        count = row["c"] if row else 0
        if int(count or 0) == 0:
            raise MappingNotFoundError(f"MetricDef not found: {target_metric_def_id}")

    def _get(self, tx: Any, mapping_id: str) -> dict[str, Any] | None:
        query = """
        MATCH (m:MqttMetricMapping) WHERE m.id = $mapping_id
        RETURN
            m.id AS id,
            m.source_device_id AS source_device_id,
            m.source_metric_id AS source_metric_id,
            m.source_metric_name AS source_metric_name,
            m.target_ci_id AS target_ci_id,
            m.target_metric_def_id AS target_metric_def_id,
            m.status AS status,
            m.version AS version,
            m.created_by AS created_by,
            m.approved_by AS approved_by,
            m.revoked_by AS revoked_by,
            m.created_at AS created_at,
            m.approved_at AS approved_at,
            m.revoked_at AS revoked_at,
            m.updated_at AS updated_at,
            m.warning AS warning,
            m.critical AS critical,
            m.operator AS operator
        """
        row = tx.run(query, mapping_id=mapping_id).single()
        if row is None:
            return None
        return self._record(
            row,
            (
                "id",
                "source_device_id",
                "source_metric_id",
                "source_metric_name",
                "target_ci_id",
                "target_metric_def_id",
                "status",
                "version",
                "created_by",
                "approved_by",
                "revoked_by",
                "created_at",
                "approved_at",
                "revoked_at",
                "updated_at",
                "warning",
                "critical",
                "operator",
            ),
        )

    def create_draft(
        self,
        mapping_id: str,
        source_device_id: str,
        source_metric_id: str,
        source_metric_name: str,
        target_ci_id: str,
        target_metric_def_id: str,
        created_by: str,
        warning: float | None = None,
        critical: float | None = None,
        operator: str | None = None,
    ) -> dict[str, Any]:
        with self._session() as tx:
            existing = self._get(tx, mapping_id)
            if existing is not None:
                raise MappingConflictError(f"Mapping id already exists: {mapping_id}")

            self._require_device_exists(tx, source_device_id)
            self._require_metric_target_exists(tx, target_ci_id)
            self._require_metric_def_exists(tx, target_metric_def_id)

            ts = self._to_iso(self._now())
            query = """
            MATCH (d:Device {id: $source_device_id})
            MATCH (ci:CI {id: $target_ci_id})
            MATCH (md:MetricDef {id: $target_metric_def_id})
            OPTIONAL MATCH (sm:Metric {id: $source_metric_id})
            CREATE (m:MqttMetricMapping)
            SET
                m.id = $mapping_id,
                m.source_device_id = $source_device_id,
                m.source_metric_id = $source_metric_id,
                m.source_metric_name = $source_metric_name,
                m.target_ci_id = $target_ci_id,
                m.target_metric_def_id = $target_metric_def_id,
                m.status = 'DRAFT',
                m.warning = $warning,
                m.critical = $critical,
                m.operator = $operator,
                m.created_by = $created_by,
                m.created_at = datetime($created_at),
                m.updated_at = datetime($updated_at),
                m.version = 1
            MERGE (d)-[:HAS_MQTT_MAPPING]->(m)
            FOREACH (_ IN CASE WHEN sm IS NOT NULL THEN [1] ELSE [] END |
                MERGE (sm)-[:HAS_MQTT_MAPPING]->(m)
            )
            MERGE (m)-[:TARGETS_CI]->(ci)
            MERGE (m)-[:TARGETS_METRIC_DEF]->(md)
            RETURN
                m.id AS id,
                m.source_device_id AS source_device_id,
                m.source_metric_id AS source_metric_id,
                m.source_metric_name AS source_metric_name,
                m.target_ci_id AS target_ci_id,
                m.target_metric_def_id AS target_metric_def_id,
                m.status AS status,
                m.version AS version,
                m.warning AS warning,
                m.critical AS critical,
                m.operator AS operator,
                m.created_by AS created_by
            """
            params = {
                "mapping_id": mapping_id,
                "source_device_id": source_device_id,
                "source_metric_id": source_metric_id,
                "source_metric_name": source_metric_name,
                "target_ci_id": target_ci_id,
                "target_metric_def_id": target_metric_def_id,
                "created_by": created_by,
                "warning": warning,
                "critical": critical,
                "operator": operator,
                "created_at": ts,
                "updated_at": ts,
            }
            row = tx.run(query, **params).single()
            if row is None:
                raise RuntimeError("Failed to create mapping draft")
            return self._record(
                row,
                (
                    "id",
                    "source_device_id",
                    "source_metric_id",
                    "source_metric_name",
                    "target_ci_id",
                    "target_metric_def_id",
                    "status",
                    "version",
                    "warning",
                    "critical",
                    "operator",
                    "created_by",
                ),
            )

    def get_approved(
        self, source_device_id: str, source_metric_id: str
    ) -> dict[str, Any] | None:
        with self._session() as tx:
            query = """
                // mqtt-mapping-get-approved
                MATCH (m:MqttMetricMapping)
            WHERE m.source_device_id = $source_device_id
              AND m.source_metric_id = $source_metric_id
              AND m.status = 'APPROVED'
            RETURN
                m.id AS id,
                m.source_device_id AS source_device_id,
                m.source_metric_id AS source_metric_id,
                m.source_metric_name AS source_metric_name,
                m.target_ci_id AS target_ci_id,
                m.target_metric_def_id AS target_metric_def_id,
                m.status AS status,
                m.version AS version,
                m.warning AS warning,
                m.critical AS critical,
                m.operator AS operator,
                m.approved_by AS approved_by,
                m.approved_at AS approved_at
            LIMIT 1
            """
            row = tx.run(
                query,
                source_device_id=source_device_id,
                source_metric_id=source_metric_id,
            ).single()
            if row is None:
                return None
            return self._record(
                row,
                (
                    "id",
                    "source_device_id",
                    "source_metric_id",
                    "source_metric_name",
                    "target_ci_id",
                    "target_metric_def_id",
                    "status",
                    "version",
                    "warning",
                    "critical",
                    "operator",
                    "approved_by",
                    "approved_at",
                ),
            )

    def approve(
        self,
        mapping_id: str,
        approved_by: str,
    ) -> dict[str, Any]:
        session = self._session()
        tx = session.begin_transaction()
        try:
            mapping = self._get(tx, mapping_id)
            if not mapping:
                raise MappingNotFoundError(f"Mapping not found: {mapping_id}")

            if mapping["status"] == MAPPING_STATUS_APPROVED:
                tx.commit()
                return mapping

            if mapping["status"] == MAPPING_STATUS_REVOKED:
                raise MappingConflictError("Revoke mappings must be recreated before approval")

            source_key = f"{mapping['source_device_id']}|{mapping['source_metric_id']}"
            now = self._to_iso(self._now())
            query = """
            // mqtt-mapping-approve
            MATCH (m:MqttMetricMapping)
            WHERE m.id = $mapping_id
            // merge (l:mqttmappingsourcelock)
            MERGE (l:MqttMappingSourceLock {source_key: $source_key})
            SET
                l.source_device_id = m.source_device_id,
                l.source_metric_id = m.source_metric_id,
                l.last_approver = $approved_by,
                l.last_approve_requested_at = datetime($now),
                l.updated_at = datetime($now)
            WITH m
            OPTIONAL MATCH (d:Device {id: m.source_device_id})
            OPTIONAL MATCH (ci:CI {id: m.target_ci_id})
            OPTIONAL MATCH (md:MetricDef {id: m.target_metric_def_id})
            OPTIONAL MATCH (conflict:MqttMetricMapping)
            WHERE conflict.source_device_id = m.source_device_id
              AND conflict.source_metric_id = m.source_metric_id
              AND conflict.status = $approved_status
              AND conflict.id <> m.id
            WITH m,
                    d,
                    ci,
                    md,
                    m.version AS version,
                    count(conflict) AS conflict_count,
                    toInteger(coalesce(m.version, 0)) + 1 AS next_version
            WHERE m.status = $draft_status
              AND d IS NOT NULL
              AND ci IS NOT NULL
              AND md IS NOT NULL
            SET m.status = CASE
                    WHEN conflict_count = 0 THEN $approved_status
                    ELSE m.status
                END,
                m.approved_by = CASE
                    WHEN conflict_count = 0 THEN $approved_by
                    ELSE m.approved_by
                END,
                m.approved_at = CASE
                    WHEN conflict_count = 0 THEN datetime($approved_at)
                    ELSE m.approved_at
                END,
                m.updated_at = datetime($updated_at),
                m.version = CASE
                    WHEN conflict_count = 0 THEN next_version
                    ELSE version
                END
            RETURN
                m.id AS id,
                m.source_device_id AS source_device_id,
                m.source_metric_id AS source_metric_id,
                m.status AS status,
                m.version AS version,
                m.approved_by AS approved_by,
                m.approved_at AS approved_at,
                m.target_ci_id AS target_ci_id,
                m.target_metric_def_id AS target_metric_def_id,
                conflict_count AS conflict_count
            """
            row = tx.run(
                query,
                mapping_id=mapping_id,
                source_key=source_key,
                approved_by=approved_by,
                approved_status=MAPPING_STATUS_APPROVED,
                draft_status=MAPPING_STATUS_DRAFT,
                approved_at=now,
                updated_at=now,
                now=now,
            ).single()
            if row is None:
                raise RuntimeError("Failed to approve mapping")

            if (row.get("conflict_count") or 0) > 0:
                raise MappingConflictError("Another approved mapping already exists for this source pair")

            tx.commit()
            return self._record(
                row,
                (
                    "id",
                    "status",
                    "version",
                    "approved_by",
                    "approved_at",
                    "target_ci_id",
                    "target_metric_def_id",
                ),
            )
        except Exception:
            tx.rollback()
            raise
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()

    def revoke(self, mapping_id: str, revoked_by: str | None = None) -> dict[str, Any]:
        with self._session() as tx:
            mapping = self._get(tx, mapping_id)
            if not mapping:
                raise MappingNotFoundError(f"Mapping not found: {mapping_id}")

            if mapping["status"] == MAPPING_STATUS_REVOKED:
                return mapping

            next_version = int(mapping.get("version") or 0) + 1
            now = self._to_iso(self._now())
            query = """
            MATCH (m:MqttMetricMapping)
            WHERE m.id = $mapping_id
            SET m.status = "REVOKED",
                m.revoked_by = $revoked_by,
                m.revoked_at = datetime($revoked_at),
                m.updated_at = datetime($updated_at),
                m.version = $next_version
            RETURN
                m.id AS id,
                m.status AS status,
                m.version AS version,
                m.revoked_by AS revoked_by,
                m.revoked_at AS revoked_at
            """
            row = tx.run(
                query,
                mapping_id=mapping_id,
                revoked_by=revoked_by,
                revoked_at=now,
                updated_at=now,
                next_version=next_version,
            ).single()
            if row is None:
                raise RuntimeError("Failed to revoke mapping")
            return self._record(row, ("id", "status", "version", "revoked_by", "revoked_at"))


# Backward-compatible singleton style (same pattern as DeviceMetricRepo).

_mapping_repo: MqttMappingRepo | None = None


def get_mqtt_mapping_repo(driver: Any | None = None) -> MqttMappingRepo:
    global _mapping_repo
    if _mapping_repo is None:
        _mapping_repo = MqttMappingRepo(driver=driver)
    return _mapping_repo
