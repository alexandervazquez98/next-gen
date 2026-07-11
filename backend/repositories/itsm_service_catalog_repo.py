"""Repository patterns for ITSM ServiceCatalog records.

These methods are intentionally narrow and query-focused to support WU1's
backend domain contract boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from database import get_db
from models.itsm import ServiceCatalogCreate, ServiceCatalogUpdate

_CREATE_SERVICE_CATALOG_QUERY = """
MERGE (sc:ServiceCatalog {service_id: $service_id})
ON CREATE SET
  sc.id = $service_id,
  sc.name = $name,
  sc.owner_team = $owner_team,
  sc.category = $category,
  sc.tier = $tier,
  sc.service_tier = $tier,
  sc.criticality = $criticality,
  sc.sla_target_minutes = $sla_target_minutes,
  sc.sla_minutes = $sla_target_minutes,
  sc.service_type = $service_type,
  sc.active = $active,
  sc.created_at = datetime($created_at),
  sc.updated_at = datetime($updated_at),
  sc.updated_by = $updated_by
ON MATCH SET
  sc.owner_team = coalesce($owner_team, sc.owner_team),
  sc.category = coalesce($category, sc.category),
  sc.tier = coalesce($tier, sc.tier),
  sc.service_tier = coalesce($tier, sc.service_tier),
  sc.criticality = coalesce($criticality, sc.criticality),
  sc.sla_target_minutes = coalesce($sla_target_minutes, sc.sla_target_minutes),
  sc.sla_minutes = coalesce($sla_target_minutes, sc.sla_minutes),
  sc.active = coalesce($active, sc.active),
  sc.updated_at = datetime($updated_at),
  sc.updated_by = $updated_by
RETURN
  sc.id AS id,
  sc.service_id AS service_id,
  sc.name AS name,
  sc.owner_team AS owner_team,
  sc.category AS category,
  sc.tier AS tier,
  sc.service_tier AS service_tier,
  sc.criticality AS criticality,
  sc.sla_target_minutes AS sla_target_minutes,
  sc.sla_minutes AS sla_minutes,
  sc.service_type AS service_type,
  sc.active AS active,
  sc.created_at AS created_at,
  sc.updated_at AS updated_at,
  sc.updated_by AS updated_by
"""

_GET_SERVICE_CATALOG_QUERY = """
MATCH (sc:ServiceCatalog)
WHERE sc.service_id = $service_id
RETURN
  sc.id AS id,
  sc.service_id AS service_id,
  sc.name AS name,
  sc.owner_team AS owner_team,
  sc.category AS category,
  sc.tier AS tier,
  sc.service_tier AS service_tier,
  sc.criticality AS criticality,
  sc.sla_target_minutes AS sla_target_minutes,
  sc.sla_minutes AS sla_minutes,
  sc.service_type AS service_type,
  sc.active AS active,
  sc.created_at AS created_at,
  sc.updated_at AS updated_at,
  sc.updated_by AS updated_by
"""

_LIST_SERVICE_CATALOGS_QUERY = """
MATCH (sc:ServiceCatalog)
RETURN
  sc.id AS id,
  sc.service_id AS service_id,
  sc.name AS name,
  sc.owner_team AS owner_team,
  sc.category AS category,
  sc.tier AS tier,
  sc.service_tier AS service_tier,
  sc.criticality AS criticality,
  sc.sla_target_minutes AS sla_target_minutes,
  sc.sla_minutes AS sla_minutes,
  sc.service_type AS service_type,
  sc.active AS active,
  sc.created_at AS created_at,
  sc.updated_at AS updated_at,
  sc.updated_by AS updated_by
ORDER BY coalesce(sc.updated_at, sc.created_at, "") DESC, sc.name
LIMIT $limit
"""

_DEACTIVATE_SERVICE_CATALOG_QUERY = """
MATCH (sc:ServiceCatalog {service_id: $service_id})
SET
  sc.active = false,
  sc.updated_at = datetime($updated_at),
  sc.updated_by = $updated_by
RETURN sc.service_id AS service_id, sc.active AS active
"""


class ServiceCatalogRepository:
    """Thin repository for ServiceCatalog nodes and compatibility aliases."""

    def __init__(self, driver: Any | None = None):
        self._driver = driver if driver is not None else get_db()

    @staticmethod
    def _record(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": row.get("id") if hasattr(row, "get") else row["id"],
            "service_id": row.get("service_id") if hasattr(row, "get") else row["service_id"],
            "name": row.get("name") if hasattr(row, "get") else row["name"],
            "owner_team": row.get("owner_team") if hasattr(row, "get") else row["owner_team"],
            "category": row.get("category") if hasattr(row, "get") else row["category"],
            "tier": row.get("tier") if hasattr(row, "get") else row["tier"],
            "service_tier": row.get("service_tier") if hasattr(row, "get") else row["service_tier"],
            "criticality": row.get("criticality") if hasattr(row, "get") else row["criticality"],
            "sla_target_minutes": (
                row.get("sla_target_minutes") if hasattr(row, "get") else row["sla_target_minutes"]
            ),
            "sla_minutes": row.get("sla_minutes") if hasattr(row, "get") else row["sla_minutes"],
            "service_type": row.get("service_type") if hasattr(row, "get") else row["service_type"],
            "active": row.get("active") if hasattr(row, "get") else row["active"],
            "created_at": row.get("created_at") if hasattr(row, "get") else row["created_at"],
            "updated_at": row.get("updated_at") if hasattr(row, "get") else row["updated_at"],
            "updated_by": row.get("updated_by") if hasattr(row, "get") else row["updated_by"],
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(tz=UTC).replace(microsecond=0).isoformat()

    def get_by_id(self, service_id: str) -> dict[str, Any] | None:
        with self._driver.session() as session:
            row = session.run(_GET_SERVICE_CATALOG_QUERY, service_id=service_id).single()
        return self._record(row)

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._driver.session() as session:
            result = session.run(_LIST_SERVICE_CATALOGS_QUERY, limit=limit)
            return [self._record(row) for row in result if self._record(row) is not None]

    def upsert(self, payload: ServiceCatalogCreate) -> dict[str, Any]:
        payload = (
            payload
            if isinstance(payload, ServiceCatalogCreate)
            else ServiceCatalogCreate(**payload)
        )
        now = self._now()
        with self._driver.session() as session:
            row = session.run(
                _CREATE_SERVICE_CATALOG_QUERY,
                service_id=payload.service_id,
                name=payload.name,
                owner_team=payload.owner_team,
                category=payload.category,
                tier=payload.tier,
                criticality=payload.criticality,
                sla_target_minutes=payload.sla_target_minutes,
                service_type=payload.service_type,
                active=payload.active,
                created_at=payload.created_at or now,
                updated_at=now,
                updated_by=payload.updated_by,
            ).single()
        return self._record(row) or {}

    def deactivate(self, service_id: str, updated_by: str | None = None) -> dict[str, Any] | None:
        with self._driver.session() as session:
            row = session.run(
                _DEACTIVATE_SERVICE_CATALOG_QUERY,
                service_id=service_id,
                updated_at=self._now(),
                updated_by=updated_by,
            ).single()
        return self._record(row)

    def update(self, service_id: str, payload: ServiceCatalogUpdate) -> dict[str, Any] | None:
        payload = (
            payload
            if isinstance(payload, ServiceCatalogUpdate)
            else ServiceCatalogUpdate(**payload)
        )
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return self.get_by_id(service_id)

        set_clauses: list[str] = [
            "sc.updated_at = datetime($updated_at)",
            "sc.updated_by = coalesce($updated_by, sc.updated_by)",
        ]
        if "name" in updates:
            set_clauses.append("sc.name = $name")
        if "owner_team" in updates:
            set_clauses.append("sc.owner_team = $owner_team")
        if "category" in updates:
            set_clauses.append("sc.category = $category")
        if "tier" in updates:
            set_clauses.append("sc.tier = $tier")
            set_clauses.append("sc.service_tier = $tier")
        if "criticality" in updates:
            set_clauses.append("sc.criticality = $criticality")
        if "sla_target_minutes" in updates:
            set_clauses.append("sc.sla_target_minutes = $sla_target_minutes")
            set_clauses.append("sc.sla_minutes = $sla_target_minutes")
        if "service_type" in updates:
            raise ValueError("service_type is immutable after catalog creation")
        if "active" in updates:
            set_clauses.append("sc.active = $active")

        update_query = """
        MATCH (sc:ServiceCatalog {service_id: $service_id})
        SET __SET_CLAUSES__
        RETURN
          sc.id AS id,
          sc.service_id AS service_id,
          sc.name AS name,
          sc.owner_team AS owner_team,
          sc.category AS category,
          sc.tier AS tier,
          sc.service_tier AS service_tier,
          sc.criticality AS criticality,
          sc.sla_target_minutes AS sla_target_minutes,
          sc.sla_minutes AS sla_minutes,
          sc.service_type AS service_type,
          sc.active AS active,
          sc.created_at AS created_at,
          sc.updated_at AS updated_at,
          sc.updated_by AS updated_by
        """.replace(
            "__SET_CLAUSES__", ",\n  ".join(set_clauses)
        )

        with self._driver.session() as session:
            row = session.run(
                update_query,
                service_id=service_id,
                updated_at=self._now(),
                updated_by=updates.get("updated_by"),
                name=updates.get("name"),
                owner_team=updates.get("owner_team"),
                category=updates.get("category"),
                tier=updates.get("tier"),
                criticality=updates.get("criticality"),
                sla_target_minutes=updates.get("sla_target_minutes"),
                active=updates.get("active"),
            ).single()
        return self._record(row)
