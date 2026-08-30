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
MATCH (seq:TicketSequence {name: 'ticket_folio'})
MATCH (sc:ServiceCatalog {service_id: $service_catalog_id})
WHERE coalesce(sc.active, true) = true AND sc.service_type = $type
SET seq.next_value = seq.next_value + 1
WITH seq.next_value AS ticket_id, sc
CREATE (tf:TicketFolio {
  ticket_id: ticket_id,
  type: $type,
  title: $title,
  description: $description,
  service_catalog_id: $service_catalog_id,
  assignee_username: $assignee_username,
  assignee_display_name: $assignee_display_name,
  assignee_active_at_assignment: $assignee_active_at_assignment,
  status: $status,
  archived: $archived,
  closed_reason: $closed_reason,
  created_at: datetime($created_at),
  updated_at: datetime($updated_at),
  updated_by: $updated_by
})
WITH tf, sc
MERGE (tf)-[:FOR_SERVICE]->(sc)
RETURN
  tf.ticket_id AS ticket_id,
  tf.type AS type,
  tf.title AS title,
  tf.description AS description,
  tf.service_catalog_id AS service_catalog_id,
  tf.assignee_username AS assignee_username,
  tf.assignee_display_name AS assignee_display_name,
  tf.assignee_active_at_assignment AS assignee_active_at_assignment,
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
  tf.assignee_username AS assignee_username,
  tf.assignee_display_name AS assignee_display_name,
  tf.assignee_active_at_assignment AS assignee_active_at_assignment,
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
  tf.assignee_username AS assignee_username,
  tf.assignee_display_name AS assignee_display_name,
  tf.assignee_active_at_assignment AS assignee_active_at_assignment,
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

        def _get(key: str) -> Any:
            return row.get(key) if hasattr(row, "get") else row[key]

        return {
            "ticket_id": _get("ticket_id"),
            "type": _get("type"),
            "title": _get("title"),
            "description": _get("description"),
            "service_catalog_id": _get("service_catalog_id"),
            "assignee_username": _get("assignee_username"),
            "assignee_display_name": _get("assignee_display_name"),
            "assignee_active_at_assignment": _get("assignee_active_at_assignment"),
            "assignee_currently_active": _get("assignee_currently_active"),
            "status": _get("status"),
            "archived": _get("archived"),
            "closed_reason": _get("closed_reason"),
            "created_at": _get("created_at"),
            "updated_at": _get("updated_at"),
            "updated_by": _get("updated_by"),
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

    def create_with_generated_id(self, payload: TicketFolioCreate) -> dict[str, Any]:
        """Allocate, create, and synchronize the service relation atomically.

        ``payload.assignee_display_name`` and ``payload.assignee_active_at_assignment``
        are populated by the service layer from the authoritative user row read
        while holding the per-user PostgreSQL advisory lock. Snapshot fields are
        required and persisted as-is; ``assignee_currently_active`` is recomputed
        at read time and not stored here.
        """
        payload = (
            payload if isinstance(payload, TicketFolioCreate) else TicketFolioCreate(**payload)
        )
        now = self._now()

        display_name = getattr(payload, "assignee_display_name", None) or ""
        # Default to True so the snapshot row records "active at assignment"
        # when the service layer did not annotate the payload explicitly.
        active_at_assignment = getattr(payload, "assignee_active_at_assignment", True)
        if active_at_assignment is None:
            active_at_assignment = True

        def write_transaction(tx):
            row = tx.run(
                _CREATE_TICKET_FOLIO_QUERY,
                type=payload.type,
                title=payload.title,
                description=payload.description,
                service_catalog_id=payload.service_catalog_id,
                assignee_username=payload.assignee_username,
                assignee_display_name=display_name,
                assignee_active_at_assignment=active_at_assignment,
                status=payload.status,
                archived=payload.archived,
                closed_reason=payload.closed_reason,
                created_at=payload.created_at or now,
                updated_at=now,
                updated_by=payload.updated_by,
            ).single()
            if row is None:
                raise RuntimeError(
                    "TicketSequence 'ticket_folio' or referenced ServiceCatalog is missing"
                )
            record = self._record(row) or {}
            record["assignee_currently_active"] = active_at_assignment
            return record

        with self._driver.session() as session:
            return session.execute_write(write_transaction)

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
        """.replace(
            "__SET_CLAUSES__", ",\n  ".join(set_clauses)
        )

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

    # ------------------------------------------------------------------
    # PR 4 — WU 7 atomic bulk ticket import. Every row commits in one
    # Neo4j write transaction; the caller MUST hold per-user locks for
    # the entire batch (sorted/deduped by normalized username).
    # ------------------------------------------------------------------

    def bulk_create_with_generated_ids(
        self,
        payloads: list[TicketFolioCreate],
        *,
        actor: str | None = None,
    ) -> list[dict[str, Any]]:
        """Atomically allocate an ID for and create every ticket in the batch."""

        if not payloads:
            return []

        now = self._now()
        normalized = [
            payload if isinstance(payload, TicketFolioCreate) else TicketFolioCreate(**payload)
            for payload in payloads
        ]

        def write_transaction(tx):
            created: list[dict[str, Any]] = []
            for payload_model in normalized:
                display_name = getattr(payload_model, "assignee_display_name", None) or payload_model.assignee_username
                active_at_assignment = getattr(payload_model, "assignee_active_at_assignment", True) or True
                row = tx.run(
                    _CREATE_TICKET_FOLIO_QUERY,
                    type=payload_model.type,
                    title=payload_model.title,
                    description=payload_model.description,
                    service_catalog_id=payload_model.service_catalog_id,
                    assignee_username=payload_model.assignee_username,
                    assignee_display_name=display_name,
                    assignee_active_at_assignment=active_at_assignment,
                    status=payload_model.status,
                    archived=payload_model.archived,
                    closed_reason=payload_model.closed_reason,
                    created_at=payload_model.created_at or now,
                    updated_at=now,
                    updated_by=actor,
                ).single()
                if row is None:
                    raise RuntimeError(
                        "bulk_create_with_generated_ids failed: missing TicketSequence or referenced ServiceCatalog"
                    )
                record = self._record(row) or {}
                record["assignee_currently_active"] = active_at_assignment
                created.append(record)
            return created

        with self._driver.session() as session:
            return session.execute_write(write_transaction)
