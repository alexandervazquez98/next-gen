"""Atomic XLSX ticket import — WU 7.

Imports a ticket workbook with three reference sheets. All-or-nothing: locks
per-user PostgreSQL advisory locks for every distinct assignee in sorted order,
holds them through the single Neo4j write transaction.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Protocol

from openpyxl import Workbook
from pydantic import ValidationError

from models.itsm import TicketFolioCreate
from services.user_lock import acquire_user_locks_in_order
from .errors import ImportValidationError
from .workbook import (
    DEFAULT_MAX_SIZE_BYTES,
    collect_header_errors,
    guard_xlsx_payload,
    open_workbook,
    read_data_rows,
    read_header_row,
)


TICKET_SHEET = "Ticket Import"
TICKET_REF_INCIDENT = "Ref - Incident Services"
TICKET_REF_SERVICE_REQUEST = "Ref - Service Request Services"
TICKET_REF_USERS = "Ref - Active Users"

TICKET_REQUIRED_HEADERS = (
    "type",
    "title",
    "description",
    "service_catalog_id",
    "assignee_username",
)


class CatalogRepository(Protocol):
    def get_by_id(self, service_id: str) -> dict | None: ...
    def list(self, limit: int = 100) -> list[dict]: ...


class UserRepository(Protocol):
    def get_by_username(self, db: Any, username: str) -> Any: ...


def build_ticket_template_workbook(
    *, catalog_repository: CatalogRepository, user_repository: UserRepository
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = TICKET_SHEET
    ws.append(list(TICKET_REQUIRED_HEADERS))

    services = catalog_repository.list(limit=500) or []
    inc_ref = wb.create_sheet(TICKET_REF_INCIDENT)
    inc_ref.append(["service_id", "name", "value_stream"])
    for s in services:
        if s.get("service_type") == "incident" and s.get("active", True):
            inc_ref.append([s.get("service_id"), s.get("name"), s.get("value_stream")])

    req_ref = wb.create_sheet(TICKET_REF_SERVICE_REQUEST)
    req_ref.append(["service_id", "name", "value_stream"])
    for s in services:
        if s.get("service_type") == "service_request" and s.get("active", True):
            req_ref.append([s.get("service_id"), s.get("name"), s.get("value_stream")])

    users_ref = wb.create_sheet(TICKET_REF_USERS)
    users_ref.append(["username", "display_name", "is_active"])
    list_active = getattr(user_repository, "list_active", None)
    if list_active is not None:
        try:
            rows = list_active()
        except Exception:  # noqa: BLE001 — never break template generation
            rows = []
        for row in rows or []:
            users_ref.append([row.get("username"), row.get("display_name"), row.get("is_active", True)])

    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def parse_ticket_workbook(
    payload: bytes,
    *,
    max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
    catalog_repository: CatalogRepository | None = None,
    user_repository: UserRepository | None = None,
) -> list[dict]:
    guard_xlsx_payload(payload, max_size_bytes=max_size_bytes)
    wb = open_workbook(payload)
    headers = read_header_row(wb, TICKET_SHEET)
    header_error = collect_header_errors(headers, TICKET_REQUIRED_HEADERS)
    if header_error.has_errors():
        raise header_error

    rows: list[dict] = []
    accumulated = ImportValidationError()
    for visible_row, cells in read_data_rows(wb, TICKET_SHEET):
        if not any(c.strip() for c in cells):
            continue
        normalized, row_error = _normalize_ticket_row(
            visible_row, cells, catalog_repository, user_repository
        )
        if row_error is not None:
            for err in row_error.errors:
                accumulated.add(row=err.row, field=err.field, code=err.code, reason=err.reason)
            continue
        rows.append(normalized)

    if accumulated.has_errors():
        raise accumulated
    return rows


def _normalize_ticket_row(
    visible_row: int,
    cells: tuple[str, ...],
    catalog_repository: CatalogRepository | None,
    user_repository: UserRepository | None,
) -> tuple[dict | None, ImportValidationError | None]:
    error = ImportValidationError()

    def fail(field: str, code: str, reason: str) -> None:
        error.add(row=visible_row, field=field, code=code, reason=reason)

    raw_type = _cell(cells, 0)
    raw_title = _cell(cells, 1)
    raw_description = _cell(cells, 2)
    raw_service = _cell(cells, 3)
    raw_assignee = _cell(cells, 4)

    if not raw_title:
        fail("title", "required", "title is required")
    if not raw_description:
        fail("description", "required", "description is required")
    if not raw_service:
        fail("service_catalog_id", "required", "service_catalog_id is required")
    if not raw_assignee:
        fail("assignee_username", "required", "assignee_username is required")

    if raw_type not in {"incident", "service_request"}:
        fail("type", "invalid_enum", "Must be one of: incident, service_request")

    if catalog_repository is not None and raw_service and raw_type in {"incident", "service_request"}:
        catalog = catalog_repository.get_by_id(raw_service)
        if catalog is None:
            fail("service_catalog_id", "service_not_found", f"Service '{raw_service}' does not exist")
        elif not catalog.get("active", True):
            fail("service_catalog_id", "service_inactive", f"Service '{raw_service}' is inactive")
        elif catalog.get("service_type") != raw_type:
            fail(
                "service_catalog_id",
                "service_type_mismatch",
                f"Service '{raw_service}' is type '{catalog.get('service_type')}', ticket is '{raw_type}'",
            )

    if user_repository is not None and raw_assignee:
        user_row = user_repository.get_by_username(None, raw_assignee)
        if user_row is None:
            fail("assignee_username", "user_not_found", f"User '{raw_assignee}' does not exist")
        elif not getattr(user_row, "is_active", True):
            fail("assignee_username", "user_inactive", f"User '{raw_assignee}' is inactive")

    if error.has_errors():
        return None, error

    return (
        {
            "type": raw_type,
            "title": raw_title,
            "description": raw_description,
            "service_catalog_id": raw_service,
            "assignee_username": raw_assignee,
        },
        None,
    )


def import_ticket_workbook(
    payload: bytes,
    *,
    actor: str | None,
    ticket_repository: Any,
    catalog_repository: CatalogRepository | None = None,
    user_repository: UserRepository | None = None,
    pg_session: Any,
    max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
) -> dict[str, Any]:
    rows = parse_ticket_workbook(
        payload,
        max_size_bytes=max_size_bytes,
        catalog_repository=catalog_repository,
        user_repository=user_repository,
    )

    normalized: list[TicketFolioCreate] = []
    error = ImportValidationError()
    for row in rows:
        try:
            normalized.append(TicketFolioCreate(**row))
        except ValidationError as exc:
            for issue in exc.errors():
                error.add(
                    row=None,
                    field=".".join(str(p) for p in issue["loc"]) or "workbook",
                    code="contract_violation",
                    reason=issue["msg"],
                )
    if error.has_errors():
        raise error

    # Lock-ordered full-batch acquisition — required by WU 7 to prevent
    # deadlock cycles when the same set of assignees is also being deactivated.
    if pg_session is not None and normalized:
        ordered_assignees = sorted({payload_model.assignee_username.lower() for payload_model in normalized})
        try:
            acquire_user_locks_in_order(pg_session, ordered_assignees)
        except RuntimeError as exc:
            if "user_lock_timeout" in str(exc):
                raise ImportValidationError() from exc
            raise

    created = ticket_repository.bulk_create_with_generated_ids(normalized, actor=actor)
    return {"status": "imported", "imported_count": len(created), "rows": created}


def _cell(cells: tuple[str, ...], index: int) -> str:
    return cells[index].strip() if len(cells) > index else ""


__all__ = [
    "TICKET_SHEET",
    "TICKET_REF_INCIDENT",
    "TICKET_REF_SERVICE_REQUEST",
    "TICKET_REF_USERS",
    "build_ticket_template_workbook",
    "import_ticket_workbook",
    "parse_ticket_workbook",
]
