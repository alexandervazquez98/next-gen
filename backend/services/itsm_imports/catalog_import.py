"""Atomic XLSX catalog import — WU 6.

Generates the ``Catalog Import`` template workbook with a ``SLA`` header (mapped
internally to ``sla_target_minutes``) and a ``Ref - Value Streams`` reference
sheet, parses uploads, validates row-by-row, and persists every valid row in
a single atomic repository call. Any validation error short-circuits before
the write.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Iterable, Protocol

from openpyxl import Workbook
from pydantic import ValidationError

from models.itsm import ServiceCatalogCreate
from .errors import ImportValidationError, IMPORT_VALIDATION_FAILED
from .workbook import (
    DEFAULT_MAX_SIZE_BYTES,
    guard_xlsx_payload,
    open_workbook,
    read_data_rows,
    read_header_row,
    reject_disallowed_headers,
    validate_required_headers,
)


# ---------------------------------------------------------------------------
# Template contract
# ---------------------------------------------------------------------------

CATALOG_SHEET = "Catalog Import"
CATALOG_REF_SHEET = "Ref - Value Streams"

CATALOG_REQUIRED_HEADERS = (
    "service_id",
    "name",
    "SLA",
    "description",
    "service_type",
    "value_stream",
    "active",
)

CATALOG_DISALLOWED_HEADERS = ("sla_target_minutes",)


# ---------------------------------------------------------------------------
# Value stream lookup seam — keeps the import path independent of the legacy
# dictionary surface so tests can inject any active set.
# ---------------------------------------------------------------------------


class ValueStreamLookup(Protocol):
    def list_active(self) -> Iterable[dict]: ...
    def is_active(self, value: str) -> bool: ...


# ---------------------------------------------------------------------------
# Template generation
# ---------------------------------------------------------------------------


def build_catalog_template_workbook(*, value_stream_lookup: ValueStreamLookup) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = CATALOG_SHEET
    ws.append(list(CATALOG_REQUIRED_HEADERS))
    ref = wb.create_sheet(CATALOG_REF_SHEET)
    ref.append(["value", "label"])
    for entry in value_stream_lookup.list_active():
        ref.append([entry["value"], entry.get("label", entry["value"])])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Parsing + validation
# ---------------------------------------------------------------------------


def parse_catalog_workbook(
    payload: bytes,
    *,
    max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
    value_stream_lookup: ValueStreamLookup | None = None,
) -> list[dict]:
    """Parse a catalog workbook into normalized row DTOs.

    Returns the list of normalized rows on success.
    Raises ``ImportValidationError`` if any header or row fails validation —
    the caller MUST treat that as zero-writes.
    """

    guard_xlsx_payload(payload, max_size_bytes=max_size_bytes)
    wb = open_workbook(payload)

    headers = read_header_row(wb, CATALOG_SHEET)

    header_error = validate_required_headers(headers, CATALOG_REQUIRED_HEADERS)
    if header_error:
        raise header_error

    disallowed_error = reject_disallowed_headers(headers, CATALOG_DISALLOWED_HEADERS)
    if disallowed_error:
        raise disallowed_error

    rows: list[dict] = []
    accumulated = ImportValidationError()
    for visible_row, cells in read_data_rows(wb, CATALOG_SHEET):
        # Treat fully-blank trailing rows as terminators, not errors.
        if not any(c.strip() for c in cells):
            continue
        normalized, row_error = _normalize_catalog_row(visible_row, cells, value_stream_lookup)
        if row_error is not None:
            for err in row_error.errors:
                accumulated.add(
                    row=err.row,
                    field=err.field,
                    code=err.code,
                    reason=err.reason,
                )
            continue
        rows.append(normalized)

    if accumulated.has_errors():
        raise accumulated
    return rows


def _normalize_catalog_row(
    visible_row: int,
    cells: tuple[str, ...],
    value_stream_lookup: ValueStreamLookup | None,
) -> tuple[dict | None, ImportValidationError | None]:
    """Normalize one row to a ``ServiceCatalogCreate``-shaped dict.

    Returns ``(normalized_dict, None)`` on success and ``(None, error)`` on
    failure — the caller accumulates errors across rows so a single workbook
    can surface the full report instead of stopping at the first failure.
    """

    error = ImportValidationError()

    def fail(field: str, code: str, reason: str) -> None:
        error.add(row=visible_row, field=field, code=code, reason=reason)

    raw_service_id = cells[0].strip() if len(cells) > 0 else ""
    raw_name = cells[1].strip() if len(cells) > 1 else ""
    raw_sla = cells[2].strip() if len(cells) > 2 else ""
    raw_description = cells[3].strip() if len(cells) > 3 else ""
    raw_service_type = cells[4].strip() if len(cells) > 4 else ""
    raw_value_stream = cells[5].strip() if len(cells) > 5 else ""
    raw_active = cells[6].strip().lower() if len(cells) > 6 else "true"

    if not raw_service_id:
        fail("service_id", "required", "service_id is required")
    if not raw_name:
        fail("name", "required", "name is required")
    if not raw_description:
        fail("description", "required", "description is required")
    if not raw_value_stream:
        fail("value_stream", "required", "value_stream is required")

    sla_value: int | None = None
    if not raw_sla:
        fail("sla_target_minutes", "required", "SLA is required")
    else:
        try:
            sla_value = int(raw_sla)
            if sla_value < 0:
                fail("sla_target_minutes", "out_of_range", "SLA must be >= 0")
        except ValueError:
            fail("sla_target_minutes", "invalid_integer", f"SLA must be an integer, got '{raw_sla}'")

    if raw_service_type not in {"incident", "service_request"}:
        fail("service_type", "invalid_enum", "Must be one of: incident, service_request")

    if value_stream_lookup is not None and raw_value_stream:
        try:
            if not value_stream_lookup.is_active(raw_value_stream):
                fail("value_stream", "inactive_value_stream", f"value_stream '{raw_value_stream}' is not active")
        except Exception:  # noqa: BLE001 — lookup failure must not block validation
            fail("value_stream", "lookup_failed", "value_stream lookup failed")

    active_value = raw_active in {"true", "1", "yes", "y", ""} if raw_active else True

    if error.has_errors():
        return None, error

    return (
        {
            "service_id": raw_service_id,
            "name": raw_name,
            "sla_target_minutes": sla_value,
            "description": raw_description,
            "service_type": raw_service_type,
            "value_stream": raw_value_stream,
            "active": active_value,
        },
        None,
    )


# ---------------------------------------------------------------------------
# Atomic persistence
# ---------------------------------------------------------------------------


def import_catalog_workbook(
    payload: bytes,
    *,
    actor: str | None,
    repository: Any,
    value_stream_lookup: ValueStreamLookup | None = None,
    max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
) -> dict[str, Any]:
    """Parse, validate, and atomically import a catalog workbook.

    On any validation failure, no rows are written to the repository and an
    ``ImportValidationError`` propagates. On success, returns a summary dict.
    """

    rows = parse_catalog_workbook(
        payload,
        max_size_bytes=max_size_bytes,
        value_stream_lookup=value_stream_lookup,
    )

    # Final Pydantic validation surfaces any drift between normalization and
    # the canonical contract. Failures here are deterministic 400s, not imports.
    normalized: list[dict] = []
    error = ImportValidationError()
    for row in rows:
        try:
            payload_model = ServiceCatalogCreate(**row)
        except ValidationError as exc:
            for issue in exc.errors():
                error.add(
                    row=None,
                    field=".".join(str(p) for p in issue["loc"]) or "workbook",
                    code="contract_violation",
                    reason=issue["msg"],
                )
            continue
        normalized.append(payload_model.model_dump())

    if error.has_errors():
        raise error

    created = repository.bulk_create(normalized, actor=actor)
    return {
        "status": "imported",
        "imported_count": len(created),
        "rows": created,
    }


__all__ = [
    "CATALOG_SHEET",
    "CATALOG_REF_SHEET",
    "ValueStreamLookup",
    "build_catalog_template_workbook",
    "import_catalog_workbook",
    "parse_catalog_workbook",
]
