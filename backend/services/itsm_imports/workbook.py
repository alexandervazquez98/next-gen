"""Shared XLSX parsing helpers used by the catalog and ticket import services."""

from __future__ import annotations

from collections.abc import Iterable
from io import BytesIO

from openpyxl import Workbook, load_workbook

from .errors import ImportValidationError

DEFAULT_MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


def guard_xlsx_payload(payload: bytes, *, max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES) -> bytes:
    if not isinstance(payload, (bytes, bytearray)) or len(payload) == 0:
        raise _error("workbook", "invalid_workbook", "Empty workbook payload")
    if len(payload) > max_size_bytes:
        raise _error(
            "workbook",
            "oversized",
            f"Workbook exceeds maximum size of {max_size_bytes} bytes",
        )
    return bytes(payload)


def open_workbook(payload: bytes) -> Workbook:
    try:
        return load_workbook(BytesIO(payload), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 — openpyxl raises a wide exception set
        raise _error("workbook", "invalid_workbook", "Workbook is not a valid .xlsx file") from None


def read_header_row(workbook: Workbook, sheet_name: str) -> list[str]:
    if sheet_name not in workbook.sheetnames:
        raise _error(
            sheet_name, "missing_sheet", f"Workbook is missing required sheet '{sheet_name}'"
        )
    ws = workbook[sheet_name]
    header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
    return [str(c).strip() if c is not None else "" for c in (header_row or [])]


def read_data_rows(workbook: Workbook, sheet_name: str) -> Iterable[tuple[int, tuple[str, ...]]]:
    """Yield ``(visible_row_number, cell_tuple)`` for every row after the header."""

    if sheet_name not in workbook.sheetnames:
        raise _error(
            sheet_name, "missing_sheet", f"Workbook is missing required sheet '{sheet_name}'"
        )
    ws = workbook[sheet_name]
    for visible_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        cells = tuple("" if c is None else str(c) for c in row)
        yield visible_idx, cells


def collect_header_errors(
    actual: list[str],
    required: tuple[str, ...],
    disallowed: tuple[str, ...] = (),
) -> ImportValidationError:
    """Aggregate missing + disallowed header errors into one structured container."""

    error = ImportValidationError()
    seen = {h.strip() for h in actual}
    for header in required:
        if header not in seen:
            error.add(
                row=None,
                field=header,
                code="missing_header",
                reason=f"Required header '{header}' is missing",
            )
    for header in disallowed:
        if header in seen:
            error.add(
                row=None,
                field=header,
                code="invalid_header",
                reason=f"Header '{header}' is not allowed; use 'SLA' instead",
            )
    return error


def _error(field: str, code: str, reason: str) -> ImportValidationError:
    err = ImportValidationError()
    err.add(row=None, field=field, code=code, reason=reason)
    return err


__all__ = [
    "DEFAULT_MAX_SIZE_BYTES",
    "collect_header_errors",
    "guard_xlsx_payload",
    "open_workbook",
    "read_data_rows",
    "read_header_row",
]
