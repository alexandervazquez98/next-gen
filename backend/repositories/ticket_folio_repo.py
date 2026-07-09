"""Repository patterns for ITSM Ticket/Folio nodes.

These methods focus on query intent for WU1 and intentionally avoid hard-delete
paths.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from database import get_db
from models.itsm import TicketFolioCreate, TicketFolioUpdate

_CREATE_TICKET_FOLIO_QUERY = """
MERGE (tf:TicketFolio {ticket_id: $ticket_id})
ON CREATE SET
  tf.type = $type,
  tf.title = $title,
  tf.description = $description,
  tf.service_catalog_id = $service_catalog_id,
  tf.status = $status,
  tf.archived = $archived,
  tf.closed_reason = $closed_reason,
  tf.created_at = datetime($created_at),
  tf.updated_at = datetime($updated_at),
  tf.updated_by = $updated_by
ON MATCH SET
  tf.type = coalesce($type, tf.type),
  tf.title = coalesce($title, tf.title),
  tf.description = coalesce($description, tf.description),
  tf.service_catalog_id = coalesce($service_catalog_id, tf.service_catalog_id),
  tf.status = coalesce($status, tf.status),
  tf.archived = coalesce($archived, tf.archived),
  tf.closed_reason = coalesce($closed_reason, tf.closed_reason),
  tf.updated_at = datetime($updated_at),
  tf.updated_by = coalesce($updated_by, tf.updated_by)
RETURN
  tf.ticket_id AS ticket_id,
  tf.type AS type,
  tf.title AS title,
  tf.description AS description,
  tf.service_catalog_id AS service_catalog_id,
  tf.status AS status,
  tf.archived AS archived,
  tf.closed_reason AS closed_reason,
  tf.created_at AS created_at,
  tf.updated_at AS updated_at,
  tf.updated_by AS updated_by
"""

_GET_TICKET_FOLIO_QUERY = """
MATCH (tf:TicketFolio {ticket_id: $ticket_id})
RETURN
  tf.ticket_id AS ticket_id,
  tf.type AS type,
  tf.title AS title,
  tf.description AS description,
  tf.service_catalog_id AS service_catalog_id,
  tf.status AS status,
  tf.archived AS archived,
  tf.closed_reason AS closed_reason,
  tf.created_at AS created_at,
  tf.updated_at AS updated_at,
  tf.updated_by AS updated_by
"""

_LIST_TICKET_FOLIO_QUERY = """
MATCH (tf:TicketFolio)
WHERE ($status IS NULL OR tf.status = $status)
  AND ($service_catalog_id IS NULL OR tf.service_catalog_id = $service_catalog_id)
  AND ($archived IS NULL OR tf.archived = $archived)
RETURN
  tf.ticket_id AS ticket_id,
  tf.type AS type,
  tf.title AS title,
  tf.description AS description,
  tf.service_catalog_id AS service_catalog_id,
  tf.status AS status,
  tf.archived AS archived,
  tf.closed_reason AS closed_reason,
  tf.created_at AS created_at,
  tf.updated_at AS updated_at,
  tf.updated_by AS updated_by
ORDER BY tf.updated_at DESC
LIMIT $limit
"""


class TicketFolioRepository:
    """Thin repository for TicketFolio nodes and logical state transitions."""

    def __init__(self, driver: Any | None = None):
        self._driver = driver if driver is not None else get_db()

    @staticmethod
    def _record(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "ticket_id": row.get("ticket_id") if hasattr(row, "get") else row["ticket_id"],
            "type": row.get("type") if hasattr(row, "get") else row["type"],
            "title": row.get("title") if hasattr(row, "get") else row["title"],
            "description": row.get("description") if hasattr(row, "get") else row["description"],
            "service_catalog_id": (
                row.get("service_catalog_id") if hasattr(row, "get") else row["service_catalog_id"]
            ),
            "status": row.get("status") if hasattr(row, "get") else row["status"],
            "archived": row.get("archived") if hasattr(row, "get") else row["archived"],
            "closed_reason": (
                row.get("closed_reason") if hasattr(row, "get") else row["closed_reason"]
            ),
            "created_at": row.get("created_at") if hasattr(row, "get") else row["created_at"],
            "updated_at": row.get("updated_at") if hasattr(row, "get") else row["updated_at"],
            "updated_by": row.get("updated_by") if hasattr(row, "get") else row["updated_by"],
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(tz=UTC).replace(microsecond=0).isoformat()

    def get(self, ticket_id: str) -> dict[str, Any] | None:
        with self._driver.session() as session:
            row = session.run(_GET_TICKET_FOLIO_QUERY, ticket_id=ticket_id).single()
        return self._record(row)

    def list(
        self,
        status: str | None = None,
        service_catalog_id: str | None = None,
        archived: bool | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._driver.session() as session:
            result = session.run(
                _LIST_TICKET_FOLIO_QUERY,
                status=status,
                service_catalog_id=service_catalog_id,
                archived=archived,
                limit=limit,
            )
            return [self._record(row) for row in result if self._record(row) is not None]

    def upsert(self, payload: TicketFolioCreate) -> dict[str, Any]:
        payload = (
            payload if isinstance(payload, TicketFolioCreate) else TicketFolioCreate(**payload)
        )
        now = self._now()
        with self._driver.session() as session:
            row = session.run(
                _CREATE_TICKET_FOLIO_QUERY,
                ticket_id=payload.ticket_id,
                type=payload.type,
                title=payload.title,
                description=payload.description,
                service_catalog_id=payload.service_catalog_id,
                status=payload.status,
                archived=payload.archived,
                closed_reason=payload.closed_reason,
                created_at=payload.created_at or now,
                updated_at=now,
                updated_by=payload.updated_by,
            ).single()
        return self._record(row) or {}

    def update(self, ticket_id: str, payload: TicketFolioUpdate) -> dict[str, Any] | None:
        payload = (
            payload if isinstance(payload, TicketFolioUpdate) else TicketFolioUpdate(**payload)
        )
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return self.get(ticket_id)

        set_clauses: list[str] = [
            "tf.updated_at = datetime($updated_at)",
            "tf.updated_by = coalesce($updated_by, tf.updated_by)",
        ]
        if "title" in updates:
            set_clauses.append("tf.title = $title")
        if "description" in updates:
            set_clauses.append("tf.description = $description")
        if "service_catalog_id" in updates:
            set_clauses.append("tf.service_catalog_id = $service_catalog_id")
        if "status" in updates:
            set_clauses.append("tf.status = $status")
        if "archived" in updates:
            set_clauses.append("tf.archived = $archived")
        if "closed_reason" in updates:
            set_clauses.append("tf.closed_reason = $closed_reason")

        query = """
        MATCH (tf:TicketFolio {ticket_id: $ticket_id})
        SET __SET_CLAUSES__
        RETURN
          tf.ticket_id AS ticket_id,
          tf.type AS type,
          tf.title AS title,
          tf.description AS description,
          tf.service_catalog_id AS service_catalog_id,
          tf.status AS status,
          tf.archived AS archived,
          tf.closed_reason AS closed_reason,
          tf.created_at AS created_at,
          tf.updated_at AS updated_at,
          tf.updated_by AS updated_by
        """.replace("__SET_CLAUSES__", ",\n  ".join(set_clauses))

        with self._driver.session() as session:
            row = session.run(
                query,
                ticket_id=ticket_id,
                updated_at=self._now(),
                title=updates.get("title"),
                description=updates.get("description"),
                service_catalog_id=updates.get("service_catalog_id"),
                status=updates.get("status"),
                archived=updates.get("archived"),
                closed_reason=updates.get("closed_reason"),
                updated_by=updates.get("updated_by"),
            ).single()
        return self._record(row)

    def sync_service_relationship(self, ticket_id: str, service_catalog_id: str | None) -> None:
        """Keep the property/reference relationship in sync for compatibility reads."""

        query = """
        MATCH (tf:TicketFolio {ticket_id: $ticket_id})
        OPTIONAL MATCH (tf)-[r:FOR_SERVICE]->()
        DELETE r
        WITH tf
        WHERE $service_catalog_id IS NOT NULL
        MATCH (sc:ServiceCatalog {service_id: $service_catalog_id})
        MERGE (tf)-[:FOR_SERVICE]->(sc)
        """
        with self._driver.session() as session:
            session.run(query, ticket_id=ticket_id, service_catalog_id=service_catalog_id)
